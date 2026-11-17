"""轮次边界（唯一真源）。

轮边界的定义必须**同时**满足三个消费方：
  1. 前端四段式渲染 `buildTurns`（`SessionDetailModal.tsx:65-127`），
     它以 `kind === 'message' && role === 'user'` 为新轮起点；
  2. 详情分片 `/api/session/detail?turn_offset&turn_limit`；
  3. FTS 检索结果的 `turn_index`（"检索命中第 N 轮 → 详情跳到第 N 轮"）。

因此本模块是全后端**唯一**的轮边界实现，任何别处都不得再自己数轮次。

轮编号约定（务必与 FTS 对齐）
-----------------------------
* 轮编号 **1 基**：第一条用户消息所属轮 = 1。
* 首个用户消息**之前**的事件（前缀区，通常是 notice / 系统注入）并入第 1 轮，
  这样 `turn_index` 与 FTS 的 `user_turn_no`（从 1 开始计）严格一致。
* `turn_index(e)` = `max(1, 满足 b <= i 的边界个数)`，其中 b 是边界事件下标。
* `spans[k]` 覆盖 `[start, end)`，`end` 是下一轮的起点，首尾连续且覆盖全量事件。

历史 bug（本模块顺手修掉）
--------------------------
`extract_dialogue_turns_for_fts`（原 `web_app.py:2574`）只判 `role == "user"`、
**不判 `kind`**。Claude Code 的 `tool_result` 事件 role 也是 `user`，
于是 FTS 的 `turn_index` 会多算，导致"检索命中第 N 轮"跳到错误的轮。
本模块把判定统一为 `kind + role` 双条件，并输出对账结果供调用方决定是否 reindex。
"""
from __future__ import annotations

import bisect
from typing import Any, Callable, Iterable

#: 轮边界判定（与前端 `buildTurns` 完全一致，改这里必须同步改前端）
TURN_BOUNDARY_KIND = "message"
TURN_BOUNDARY_ROLE = "user"


def is_turn_boundary(event: dict[str, Any]) -> bool:
    """该事件是否是一个新轮的开始（用户真实指令）。"""
    if not isinstance(event, dict):
        return False
    return event.get("kind") == TURN_BOUNDARY_KIND and event.get("role") == TURN_BOUNDARY_ROLE


def boundary_indices(events: Iterable[dict[str, Any]]) -> list[int]:
    """返回所有轮边界事件的下标（升序）。"""
    return [index for index, event in enumerate(events) if is_turn_boundary(event)]


def compute_turn_spans(events: list[dict[str, Any]], preview_chars: int = 80) -> list[dict[str, Any]]:
    """把事件数组切成轮片段。

    Returns:
        [{index, start, end, user_preview, timestamp}, ...]，`index` 1 基、首尾连续。
        空事件数组返回 `[]`。
    """
    total = len(events or [])
    if total == 0:
        return []

    boundaries = boundary_indices(events)
    if not boundaries:
        # 没有任何用户消息：整段算 1 轮，避免前端拿到 0 轮把详情渲染成空白
        return [_make_span(1, 0, total, events, 0, preview_chars)]

    starts = [0] + boundaries[1:]
    ends = boundaries[1:] + [total]
    spans: list[dict[str, Any]] = []
    for position, (start, end) in enumerate(zip(starts, ends)):
        user_index = boundaries[position]
        spans.append(_make_span(position + 1, start, end, events, user_index, preview_chars))
    return spans


def _make_span(
    index: int,
    start: int,
    end: int,
    events: list[dict[str, Any]],
    user_index: int,
    preview_chars: int,
) -> dict[str, Any]:
    preview = ""
    timestamp = ""
    if 0 <= user_index < len(events):
        source = events[user_index]
        raw = str(source.get("text") or "").strip()
        preview = raw[:preview_chars]
        timestamp = str(source.get("timestamp") or "")
    return {
        "index": index,
        "start": start,
        "end": end,
        "user_preview": preview,
        "timestamp": timestamp,
    }


def turn_index_map(events: list[dict[str, Any]]) -> list[int]:
    """每个事件所属的轮编号（1 基），长度与 `events` 相等。"""
    if not events:
        return []
    boundaries = boundary_indices(events)
    if not boundaries:
        return [1] * len(events)
    mapping: list[int] = []
    for index in range(len(events)):
        position = bisect.bisect_right(boundaries, index)
        mapping.append(position if position >= 1 else 1)
    return mapping


def turns_total(events: list[dict[str, Any]]) -> int:
    """轮数（无用户消息时按 1 轮计，与 `compute_turn_spans` 一致）。"""
    return len(compute_turn_spans(events))


def demote_intermediate_assistant_messages(events: list[dict[str, Any]]) -> int:
    """同一轮内只保留最后一条 assistant message 为回复。

    许多 Agent（豆包、Antigravity、WorkBuddy、Trae、Codex）会把
    “我先定位…”“验证发现…”这类过程说明也写成 assistant message；
    如果全部渲染成回复，就会出现“一份用户指令对应多条回复”。
    这里按用户轮边界分组，把每组里除最后一条外的 assistant message
    改成 thinking，返回被改写的条数。
    """
    if not events:
        return 0
    boundaries = boundary_indices(events)
    if not boundaries:
        starts = [0]
        ends = [len(events)]
    else:
        starts = [0] + boundaries[1:]
        ends = boundaries[1:] + [len(events)]

    changed = 0
    for start, end in zip(starts, ends):
        reply_indices = [
            i
            for i in range(start, end)
            if isinstance(events[i], dict)
            and events[i].get("kind") == "message"
            and events[i].get("role") == "assistant"
            and str(events[i].get("text") or "").strip()
        ]
        if len(reply_indices) <= 1:
            continue
        for i in reply_indices[:-1]:
            events[i]["kind"] = "thinking"
            events[i]["role"] = "assistant"
            changed += 1
    return changed


def slice_events_by_turns(
    events: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    turn_offset: int,
    turn_limit: int,
) -> list[dict[str, Any]]:
    """按轮切片（`turn_offset` 为 1 基起始轮号，`turn_limit` <= 0 表示不限制）。"""
    selected = select_spans(spans, turn_offset, turn_limit)
    if not selected:
        return []
    return list(events[selected[0]["start"]: selected[-1]["end"]])


def resolve_start_position(spans: list[dict[str, Any]], turn_offset: int) -> int:
    """把 1 基轮号 `turn_offset` 换算成 `spans` 数组下标（0 或越界取边界值）。"""
    if not spans:
        return 0
    if turn_offset <= 1:
        return 0
    return min(turn_offset - 1, len(spans))


def select_spans(
    spans: list[dict[str, Any]], turn_offset: int, turn_limit: int
) -> list[dict[str, Any]]:
    """按 1 基轮号起点 + 轮数上限选出片段列表。"""
    start_position = resolve_start_position(spans, turn_offset)
    if start_position >= len(spans):
        return []
    if turn_limit <= 0:
        return spans[start_position:]
    return spans[start_position: start_position + turn_limit]


def audit_fts_alignment(
    fts_manager: Any,
    turn_extractor: Callable[[str, str], list[dict[str, Any]]],
    limit: int = 0,
    format_lookup: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """对账：FTS 索引里的 `turn_index` 是否与「kind+role」双条件一致。

    只在 FTS 有索引的会话上做，且只比较「最大 turn_index」（轮数）——
    比逐条比对快一个数量级，而"轮数不一致"正是错位的充要条件。

    Args:
        fts_manager: 提供 `_get_conn()` 的 `SessionFTSManager` 实例。
        turn_extractor: `(file_path, format) -> [{"role","turn_index",...}]`，
            即修好 kind 判定后的 `extract_dialogue_turns_for_fts`。
        limit: 最多检查多少篇（0 = 全量）。
        format_lookup: `catalog_id -> format`。**必须传**：靠 catalog_id 前缀
            猜格式会把 `antigravity` 的 catalog 型 cid 猜成 `claude`，
            从而用错解析器（实测把 2 篇会话的索引清空）。缺省只为向后兼容。

    Returns:
        {"checked": n, "divergent": m, "catalog_ids": [...], "scanned": k}
    """
    checked = 0
    scanned = 0
    divergent: list[str] = []
    with fts_manager._get_conn() as conn:
        rows = conn.execute(
            "SELECT catalog_id, session_id, CASE WHEN turn_index IS NULL THEN 0 ELSE turn_index END AS ti "
            "FROM conversation_fts"
        ).fetchall()
        metas = conn.execute(
            "SELECT catalog_id, file_path FROM fts_file_meta"
        ).fetchall()

    file_by_cid = {row["catalog_id"]: row["file_path"] for row in metas}
    max_turn: dict[str, int] = {}
    for row in rows:
        cid = row["catalog_id"]
        max_turn[cid] = max(max_turn.get(cid, 0), int(row["ti"] or 0))

    for cid, fts_turns in max_turn.items():
        if limit and scanned >= limit:
            break
        file_path = file_by_cid.get(cid)
        if not file_path:
            continue
        scanned += 1
        try:
            from pathlib import Path

            path = Path(file_path)
            if not path.exists():
                continue
            fmt = guess_format(cid, format_lookup)
            turns = turn_extractor(path, fmt)
        except Exception:
            continue
        checked += 1
        server_turns = max((int(t.get("turn_index") or 0) for t in turns), default=0)
        if server_turns != fts_turns:
            divergent.append(cid)

    return {
        "checked": checked,
        "divergent": len(divergent),
        "catalog_ids": divergent,
        "scanned": scanned,
    }


def guess_format(catalog_id: str, format_lookup: Callable[[str], str] | None = None) -> str:
    """推断会话格式：优先用调用方给的 catalog 查询，退化为前缀推断。"""
    if format_lookup is not None:
        try:
            resolved = format_lookup(catalog_id)
            if resolved:
                return resolved
        except Exception:
            pass
    if catalog_id.startswith("wb_"):
        return "workbuddy"
    if catalog_id.startswith("trae_"):
        return "trae"
    return "antigravity"
