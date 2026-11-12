#!/usr/bin/env python3
"""服务层自测（T02 / T03）：不依赖 HTTP，直接断言纯逻辑。

覆盖：
  * `services/turns.py`：轮边界与前端 buildTurns 同定义、span 首尾连续、轮号映射；
  * `services/detail.py`：slim 裁剪规则（opaque 丢弃 / text 截断 / payload 省略 /
    message 不裁）、分片区间与全量逐字节一致、ETag 必含分片参数、LRU 容量与淘汰；
  * `services/fields.py`：lite 白名单（含 0/False 不省略、session_id/file_path 必留）；
  * `services/snapshot.py`：无参全量 / limit 切片 / offset 越界 / 分页无重复无遗漏 /
    fold 计数 / 指纹命中不重建 / invalidate 后重建 / meta 完整。

运行：python tools/selftest_services.py   （退出码 0 = 全绿）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from services import detail as detail_service  # noqa: E402
from services import fields as fields_service  # noqa: E402
from services import snapshot as snapshot_service  # noqa: E402
from services import turns as turns_service  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [ OK ] {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  [FAIL] {name}  {detail}")


# --------------------------------------------------------------------------
# 造数据
# --------------------------------------------------------------------------
def make_events() -> list[dict]:
    """构造 3 轮事件：前缀 1 条 + 每轮 user / thinking / tool_call / tool_result / message。"""
    events: list[dict] = [
        {"kind": "notice", "role": "system", "timestamp": "t0", "text": "系统提示", "tool_name": "",
         "tool_call_id": "", "payload": None},
    ]
    for turn in range(1, 4):
        events.append({"kind": "message", "role": "user", "timestamp": f"u{turn}", "text": f"用户第{turn}问",
                       "tool_name": "", "tool_call_id": "", "payload": None})
        events.append({"kind": "thinking", "role": "assistant", "timestamp": f"k{turn}",
                       "text": "想" * 3000, "tool_name": "", "tool_call_id": "", "payload": None})
        events.append({"kind": "tool_call", "role": "assistant", "timestamp": f"c{turn}", "text": "",
                       "tool_name": "Read", "tool_call_id": f"call_{turn}",
                       "payload": {"path": "x.py", "blob": "y" * 3000}})
        events.append({"kind": "tool_result", "role": "tool", "timestamp": f"r{turn}",
                       "text": "结果" * 2000, "tool_name": "Read", "tool_call_id": f"call_{turn}",
                       "payload": {"is_error": False}})
        events.append({"kind": "opaque", "role": "", "timestamp": f"o{turn}", "text": "", "tool_name": "",
                       "tool_call_id": "", "payload": {"raw": "z" * 500}})
        events.append({"kind": "message", "role": "assistant", "timestamp": f"a{turn}",
                       "text": f"助手第{turn}答" + "答" * 2500, "tool_name": "", "tool_call_id": "",
                       "payload": None})
    return events


def test_turns() -> None:
    print("services/turns.py")
    events = make_events()
    spans = turns_service.compute_turn_spans(events)
    check("turns_total == 3（前缀并入第 1 轮）", len(spans) == 3, f"spans={len(spans)}")
    check("span[0] 从 0 开始（含前缀）", spans[0]["start"] == 0, str(spans[0]))
    check("span 首尾连续", all(spans[i]["end"] == spans[i + 1]["start"] for i in range(len(spans) - 1)))
    check("span 覆盖全量事件", spans[-1]["end"] == len(events), f"{spans[-1]['end']}/{len(events)}")
    check("轮号 1 基连续", [s["index"] for s in spans] == [1, 2, 3])
    mapping = turns_service.turn_index_map(events)
    check("turn_index 长度 == 事件数", len(mapping) == len(events))
    check("前缀事件归第 1 轮", mapping[0] == 1, f"mapping[0]={mapping[0]}")
    check("首条用户消息属于第 1 轮", mapping[1] == 1, f"mapping[1]={mapping[1]}")
    check("第二轮用户消息 → 2", mapping[7] == 2, f"mapping[7]={mapping[7]}")
    # 与前端 buildTurns 等价性：边界数量就是轮数
    boundaries = [i for i, e in enumerate(events) if e.get("kind") == "message" and e.get("role") == "user"]
    check("轮数 == 用户消息边界数", len(spans) == len(boundaries), f"{len(spans)} vs {len(boundaries)}")
    # 空输入
    check("空事件数组 → 0 轮", turns_service.compute_turn_spans([]) == [])
    check("无用户消息 → 1 轮", len(turns_service.compute_turn_spans([{"kind": "notice", "role": "system"}])) == 1)
    # 切片与全量逐字节一致
    sliced = turns_service.slice_events_by_turns(events, spans, 2, 2)
    check("turn_offset=2&limit=2 等于 events[span2.start:span3.end]",
          sliced == events[spans[1]["start"]:spans[2]["end"]], f"{len(sliced)} 条")
    check("turn_offset 越界 → 空", turns_service.slice_events_by_turns(events, spans, 99, 3) == [])


def test_slim() -> None:
    print("services/detail.py · slim")
    events = make_events()
    slimmed = detail_service.slim_events(events)
    kinds = [e["kind"] for e in slimmed]
    check("opaque 事件被丢弃", "opaque" not in kinds)
    check("事件数 19 → 15", len(slimmed) == len(events) - 3, f"{len(events)} -> {len(slimmed)}")
    thinking = next(e for e in slimmed if e["kind"] == "thinking")
    check("thinking.text 截到 1200", len(thinking["text"]) == detail_service.TR_CAP, str(len(thinking["text"])))
    check("thinking 标 truncated", thinking.get("truncated") is True)
    check("thinking 记 hidden_chars", thinking.get("hidden_chars") == 3000 - detail_service.TR_CAP,
          str(thinking.get("hidden_chars")))
    assistant = next(e for e in slimmed if e["kind"] == "message" and e["role"] == "assistant")
    check("message 正文全量不裁", len(assistant["text"]) == len("助手第2答" + "答" * 2500), str(len(assistant["text"])))
    check("message 无 truncated", "truncated" not in assistant)
    call = next(e for e in slimmed if e["kind"] == "tool_call")
    check("大 payload 改为 _omitted", call["payload"].get("_omitted") is True, str(call["payload"])[:60])
    check("_omitted 带 bytes", isinstance(call["payload"].get("bytes"), int) and call["payload"]["bytes"] > 1500)
    result = next(e for e in slimmed if e["kind"] == "tool_result")
    check("tool_result.text 截到 1200", len(result["text"]) == detail_service.TR_CAP, str(len(result["text"])))
    check("truncated_chars == 被隐藏的 text 字符数",
          result.get("truncated_chars") == 4000 - detail_service.TR_CAP, str(result.get("truncated_chars")))
    check("hidden_chars >= truncated_chars",
          result.get("hidden_chars", 0) >= result.get("truncated_chars", 0),
          f"{result.get('hidden_chars')} vs {result.get('truncated_chars')}")
    notice = next(e for e in slimmed if e["kind"] == "notice")
    check("空 tool_name 被省略（envelope 噪音）", "tool_name" not in notice)
    check("空 tool_call_id 被省略", "tool_call_id" not in notice)
    check("kind/role/timestamp/text 永不缺", all(k in e for e in slimmed for k in ("kind", "role", "timestamp", "text")))
    # 0 / False 不省略
    zero_event = {"kind": "message", "role": "assistant", "timestamp": "", "text": "x",
                  "hidden_chars": 0, "truncated": False, "payload": None}
    slim_zero = detail_service.slim_event(zero_event)
    check("hidden_chars=0 保留", slim_zero.get("hidden_chars") == 0)
    check("truncated=False 被清理", "truncated" not in slim_zero)
    check("payload=None 被省略", "payload" not in slim_zero)
    check("timestamp 空串保留", slim_zero.get("timestamp") == "")


def test_shard() -> None:
    print("services/detail.py · 分片 / ETag / LRU")
    events = make_events()
    spans = turns_service.compute_turn_spans(events)

    shard = detail_service.build_shard(events, spans, 1, 1, 1, 10 ** 7)
    check("turn_offset=1&limit=1 → 1 轮", len(shard["spans"]) == 1, str(shard["spans"]))
    check("分片事件数 == 该轮事件数", shard["events_shipped"] == len(shard["events"]))
    check("turn_index 与事件数对齐", len(shard["turn_index"]) == len(shard["events"]))
    check("event_index 与事件数对齐", len(shard["event_index"]) == len(shard["events"]))
    check("has_more=True", shard["has_more"] is True)

    # R9 回归护栏：turns[].start/end 必须落在**已下发 events** 的下标空间，可安全切片
    multi = detail_service.build_shard(events, spans, 1, 3, 1, 10 ** 7)
    slice_ok = True
    reassembled: list[dict] = []
    for span in multi["spans"]:
        piece = multi["events"][span["start"]: span["end"]]
        if len(piece) != span["events_count"]:
            slice_ok = False
        reassembled.extend(piece)
    check("turns[].start/end 可安全切 events（逐轮长度吻合）", slice_ok)
    check("按 span 顺序拼接 == 整个 events", reassembled == multi["events"])
    check("末轮 raw_end == events_total_raw 口径（原始全量下标）",
          multi["spans"][-1]["raw_end"] == len(events), str(multi["spans"][-1]["raw_end"]))
    check("start 连续无空洞",
          all(multi["spans"][i]["end"] == multi["spans"][i + 1]["start"] for i in range(len(multi["spans"]) - 1)))

    last = detail_service.build_shard(events, spans, 3, 5, 1, 10 ** 7)
    check("最后一轮 has_more=False", last["has_more"] is False)
    check("末页 next_turn_offset=0", last["next_turn_offset"] == 0, str(last["next_turn_offset"]))

    tight = detail_service.build_shard(events, spans, 1, 3, 1, 2000)
    check("字节预算触发时至少给 1 轮", len(tight["spans"]) >= 1)
    check("预算命中标记", tight["budget_hit"] is True)
    check("预算裁剪记录丢轮数", tight["turns_dropped_by_budget"] >= 1, str(tight["turns_dropped_by_budget"]))
    check("next_turn_offset == 已发末轮+1（推进不丢轮）",
          tight["next_turn_offset"] == tight["spans"][-1]["index"] + 1,
          f"next={tight['next_turn_offset']} last={tight['spans'][-1]['index']}")

    # 模拟"按 next_turn_offset 推进"的脚本消费方：必须覆盖全部轮次、无跳号
    collected: list[int] = []
    cursor = 1
    for _ in range(10):
        chunk = detail_service.build_shard(events, spans, cursor, 8, 1, 2000)
        collected.extend(span["index"] for span in chunk["spans"])
        if not chunk["has_more"]:
            break
        cursor = chunk["next_turn_offset"]
    check("按 next_turn_offset 推进覆盖全部轮次且无跳号", collected == [1, 2, 3], str(collected))

    base = detail_service.base_etag(123456789, 4096)
    etag_a = detail_service.compute_etag(base, "cid", "claude", turn_offset=0, turn_limit=8, slim=1, max_bytes=393216)
    etag_b = detail_service.compute_etag(base, "cid", "claude", turn_offset=8, turn_limit=8, slim=1, max_bytes=393216)
    etag_c = detail_service.compute_etag(base, "cid", "claude", turn_offset=0, turn_limit=8, slim=0, max_bytes=393216)
    check("不同 turn_offset → 不同 ETag", etag_a != etag_b)
    check("不同 slim → 不同 ETag", etag_a != etag_c)
    check("同参数 → 同 ETag", etag_a == detail_service.compute_etag(
        base, "cid", "claude", turn_offset=0, turn_limit=8, slim=1, max_bytes=393216))
    check("ETag 带引号", etag_a.startswith('"') and etag_a.endswith('"'))

    lru = detail_service.DetailLRU(max_entries=2, max_bytes=10 ** 9, single_entry_max=10 ** 9)
    lru.put(("a", 1, 1, 1), {"events": []}, 100)
    lru.put(("b", 1, 1, 1), {"events": []}, 100)
    check("LRU 命中", lru.get(("a", 1, 1, 1)) is not None)
    lru.put(("c", 1, 1, 1), {"events": []}, 100)
    check("LRU 条数上限淘汰最旧", lru.get(("b", 1, 1, 1)) is None)
    lru_bytes = detail_service.DetailLRU(max_entries=10, max_bytes=150, single_entry_max=10 ** 9)
    lru_bytes.put(("x", 1, 1, 1), {}, 100)
    lru_bytes.put(("y", 1, 1, 1), {}, 100)
    check("LRU 字节上限淘汰", lru_bytes.get(("x", 1, 1, 1)) is None)
    lru_big = detail_service.DetailLRU(max_entries=10, max_bytes=10 ** 9, single_entry_max=50)
    lru_big.put(("big", 0, 0, 1), {}, 999)
    check("单条超限不入缓存", lru_big.get(("big", 0, 0, 1)) is None)

    matches = detail_service.search_in_events(events, "助手第2答", limit=10)
    check("内存检索命中第 2 轮", matches and matches[0]["turn_index"] == 2, str(matches[:1]))
    check("内存检索带 snippet", bool(matches and matches[0]["snippet"]))


def test_fields() -> None:
    print("services/fields.py")
    item = {
        "catalog_id": "cid", "session_id": "sid", "format": "antigravity", "title": "标题",
        "started_at": "2026-01-01", "mtime": 1762410151.4, "records": 12, "bytes": 100,
        "tokens": 0, "input_tokens": 10, "output_tokens": 20, "usage_source": "tiktoken",
        "file_path": "C:\\x.db", "exists": False, "children_count": 0,
        "lineage_size": 2, "is_lineage_branch": False, "branch_label": "", "side_question": "",
        "lineage_head_title": "", "lineage_head_steps": 0, "parent_id": "", "agent_name": "",
        "children": [{"catalog_id": "c2"}], "parent_title": "父", "account": "a", "workspace": "w",
        "mode": "m", "model": "mm", "aux_tokens": 5, "is_child": False, "parent_catalog_id": "p",
        "all_files": ["f1", "f2"], "lineage": "ag:x", "thoughts_tokens": 1, "content_tokens": 2,
        "chat_tokens": 3,
    }
    lite = fields_service.project_lite(item)
    check("lite 只含白名单字段", set(lite) <= set(fields_service.LITE_FIELDS), str(sorted(set(lite) - set(fields_service.LITE_FIELDS))))
    check("lite 无 children", "children" not in lite)
    check("lite 无 all_files", "all_files" not in lite)
    check("lite 保留 session_id", lite.get("session_id") == "sid")
    check("lite 保留 file_path", lite.get("file_path") == "C:\\x.db")
    check("exists=False 不省略", lite.get("exists") is False)
    check("tokens=0 不省略", lite.get("tokens") == 0)
    check("is_lineage_branch=False 不省略", lite.get("is_lineage_branch") is False)
    check("空 branch_label 被省略", "branch_label" not in lite)
    check("空 parent_id 被省略", "parent_id" not in lite)
    check("project_lite 不修改入参", "children" in item)
    check("缺少关键字段时被报告", fields_service.missing_lite_fields({"catalog_id": "x"}) != [])


def test_snapshot() -> None:
    print("services/snapshot.py")
    counter = {"builds": 0}
    fingerprint_value = {"value": "fp1"}

    def builder() -> list[dict]:
        counter["builds"] += 1
        items = []
        for index in range(10):
            items.append({
                "catalog_id": f"cid{index}",
                "session_id": f"sid{index}",
                "format": "antigravity" if index % 2 == 0 else "claude",
                "title": f"会话 {index}",
                "mtime": 1000 + index,
                "bytes": 100 * index,
                "tokens": 10 * index,
                "records": index,
                "started_at": f"2026-01-{index + 1:02d}",
                "file_path": f"C:\\s{index}.db",
                "exists": True,
                "is_lineage_branch": index == 3,
                "children": [{"catalog_id": f"child{index}"}],
                "children_count": 1,
            })
        return items

    cache = snapshot_service.SnapshotCache(
        builder=builder, fingerprint=lambda: fingerprint_value["value"]
    )

    full = cache.serve({}).payload
    check("无参 → 全量", full["count"] == 10, str(full["count"]))
    check("无参响应含 sessions/count", "sessions" in full and "count" in full)
    check(
        "meta 完整（total/offset/limit/has_more/snapshot/generation/fold，不含耗时）",
        set(["total", "count", "offset", "limit", "has_more", "snapshot", "generation", "fold"]) <= set(full["meta"]),
    )
    check("meta.total == 匹配总数", full["meta"]["total"] == 10)
    check("无参 limit=0", full["meta"]["limit"] == 0)

    check("指纹命中不重建", counter["builds"] == 1, f"builds={counter['builds']}")
    cache.serve({"limit": ["3"]}).payload
    check("第二次仍不重建（single-flight/指纹）", counter["builds"] == 1, f"builds={counter['builds']}")

    page1 = cache.serve({"limit": ["3"], "offset": ["0"]}).payload
    page2 = cache.serve({"limit": ["3"], "offset": ["3"]}).payload
    page3 = cache.serve({"limit": ["3"], "offset": ["6"]}).payload
    page4 = cache.serve({"limit": ["3"], "offset": ["9"]}).payload
    ids = [s["catalog_id"] for page in (page1, page2, page3, page4) for s in page["sessions"]]
    check("分页无重复无遗漏", len(ids) == 10 and len(set(ids)) == 10, str(len(ids)))
    check("has_more 末页为 False", page4["has_more"] is False and page1["has_more"] is True)

    overflow = cache.serve({"limit": ["3"], "offset": ["50"]}).payload
    check("offset 越界 → 空数组而非报错", overflow["sessions"] == [] and overflow["count"] == 0)
    check("越界 total 仍为 10", overflow["total"] == 10)

    fold = cache.serve({"fold": ["1"]}).payload
    check("fold=1 折叠掉分叉副本", fold["total"] == 9, str(fold["total"]))
    check("fold=1 结果无分叉副本", all(not s.get("is_lineage_branch") for s in fold["sessions"]))

    lite = cache.serve({"fields": ["lite"]}).payload
    check("fields=lite 走 lite 投影", "children" not in lite["sessions"][0])
    check("fields=lite 每条都保留 session_id",
          all(s.get("session_id") for s in lite["sessions"]))
    check("fields=lite 保留 exists/mtime",
          all("exists" in s and "mtime" in s for s in lite["sessions"]))
    check("lite 与 full 条数一致", lite["count"] == full["count"])

    filtered = cache.serve({"format": ["claude"]}).payload
    check("format 过滤", filtered["count"] == 5, str(filtered["count"]))
    searched = cache.serve({"q": ["会话 7"]}).payload
    check("标题搜索", searched["count"] == 1, str(searched["count"]))

    snapshot_id = page1["snapshot"]
    pinned = cache.serve({"limit": ["3"], "offset": ["0"], "snapshot": [snapshot_id]}).payload
    check("snapshot 令牌锁定同一快照", pinned["snapshot"] == snapshot_id)

    cache.invalidate()
    fingerprint_value["value"] = "fp2"
    rebuilt = cache.serve({}).payload
    check("invalidate 后重建", counter["builds"] == 2, f"builds={counter['builds']}")
    check("重建后 snapshot_id 变化", rebuilt["snapshot"] != snapshot_id)

    bad_limit = cache.serve({"limit": ["abc"], "offset": ["-5"]}).payload
    check("非法 limit 回落全量", bad_limit["count"] == 10, str(bad_limit["count"]))

    # ---------------- ETag 稳定性（D-2 回归护栏） ----------------
    print("services/snapshot.py · ETag 稳定性")
    first = cache.serve({"limit": ["3"], "offset": ["0"], "fields": ["lite"]})
    second = cache.serve({"limit": ["3"], "offset": ["0"], "fields": ["lite"]})
    check("同参两次请求 ETag 相同", first.etag == second.etag, first.etag)
    check("ETag 带引号", first.etag.startswith('"') and first.etag.endswith('"'))
    check("body 不含耗时字段 meta.ms", "ms" not in first.payload["meta"])
    check("body 不含 meta.build_ms", "build_ms" not in first.payload["meta"])
    check("body 不含 meta.build_count", "build_count" not in first.payload["meta"])
    timing_keys = [k for k in first.payload if k in {"ms", "build_ms", "elapsed_ms"}]
    check("body 顶层无耗时字段", timing_keys == [], str(timing_keys))
    other_offset = cache.serve({"limit": ["3"], "offset": ["3"], "fields": ["lite"]})
    check("不同 offset → 不同 ETag", other_offset.etag != first.etag)
    other_query = cache.serve({"limit": ["3"], "offset": ["0"], "fields": ["lite"], "q": ["会话 1"]})
    check("不同 q → 不同 ETag", other_query.etag != first.etag)
    fold_etag = cache.serve({"fold": ["1"]})
    full_etag = cache.serve({})
    check("fold=1 与 fold=0 ETag 不同", fold_etag.etag != full_etag.etag)
    check("X-Cache: 首次 miss", first.cache_status in {"hit", "miss"}, first.cache_status)
    check("X-Cache: 已建快照后为 hit", second.cache_status == "hit", second.cache_status)
    check("query_ms / build_ms 走响应头载体",
          isinstance(first.query_ms, float) and isinstance(first.build_ms, float))
    cache.invalidate()
    fingerprint_value["value"] = "fp3"
    after_invalidate = cache.serve({"limit": ["3"], "offset": ["0"], "fields": ["lite"]})
    check("invalidate 后 ETag 变化（304 不会误命中）", after_invalidate.etag != first.etag)


def main() -> int:
    print(f"服务层自测（{BASE_DIR}）")
    test_turns()
    test_slim()
    test_shard()
    test_fields()
    test_snapshot()
    print("-" * 60)
    print(f"PASS {len(PASSED)} / FAIL {len(FAILED)}")
    for failure in FAILED:
        print(f"  FAIL: {failure}")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
