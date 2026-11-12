"""会话详情：解析结果 LRU + slim 裁剪 + 轮分片 + 预解析 ETag。

为什么需要这一层（实测数字，最大会话 `1eaa5a8745ff40cb`）
---------------------------------------------------------
* 全量详情 **4,520,694 B / ~1,120 ms**，6635 条事件，而前端 `ClampedText`
  默认只显示 1200 字符；
* 其中 `kind == "opaque"` 占 4895 条（**73.7%**），而前端 `buildTurns`
  对 `opaque` 是**静默丢弃**（从未渲染，却占满带宽）；
* `tool_result.text` + `payload` 合计 2.80 MB / 4.52 MB（62%）。

于是 `slim=1` 的三条裁剪规则都是「砍掉用户从未看见的东西」：
  1. 丢弃 `kind == "opaque"` 事件；
  2. `tool_result` / `thinking` 的 `text` 截 1200 字符并标 `truncated: true`；
  3. `payload` 序列化后 > 1500 B 的替换为 `{"_omitted": true, "bytes": N}`。

⚠️ **`message` 事件的 text 全量不裁**：四段式正文必须完整（Markdown 渲染红线）。

缓存与 ETag
-----------
* LRU key = `(catalog_id, mtime_ns, size, PARSER_VERSION)`：
  `mtime` 用纳秒（秒级在同秒两次写入时会碰撞），`PARSER_VERSION` 一改就全量失效。
* 上限 24 条 / 192 MB（按 `estimate()` 估算值计，估算系数 ×2.5 是对 Python 对象
  相对 JSON 的实测放大），单条估算 ≥ 32 MB 直接不入缓存（防一个大会话挤掉全部）。
* **ETag 必须包含分片参数**，否则"第 81–85 轮"会命中"第 1–5 轮"的 ETag，
  304 让前端静默展示错误轮次。
* ETag 在**解析之前**就能算出来（只依赖 mtime_ns / size / 参数），因此 304 命中时
  一次文件解析都不做。
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from . import turns as turns_service

#: 解析器版本：`sanitize_session_events` / `_enrich_session_events_for_detail`
#: 语义一改就 +1，LRU 自动全量失效
PARSER_VERSION = 2

#: 与前端 `ClampedText` 默认值一致的裁剪点（裁剪点落在用户本就看不到的位置）
TR_CAP = 1200
#: payload 序列化超过这个字节数就整体省略（前端只在 tool_call 里抽一行摘要）
PAYLOAD_CAP_BYTES = 1500
#: `raw_text`（被清洗掉的原始用户输入）的裁剪点
RAW_TEXT_CAP = 4000

DEFAULT_TURN_LIMIT = 8
DEFAULT_MAX_BYTES = 393216

LRU_MAX_ENTRIES = 24
LRU_MAX_BYTES = 192 * 1024 * 1024
LRU_SINGLE_ENTRY_MAX = 32 * 1024 * 1024
ESTIMATE_FACTOR = 2.5

#: 一旦出现这些参数，就走「分片模式」；一个参数都不给 = 旧行为（全量）
SHARD_KEYS: tuple[str, ...] = ("turn_offset", "turn_limit", "slim", "max_bytes")

#: 无论是否为空都必须保留的键（消费方直接读，读到 undefined 会崩）
_ALWAYS_KEEP_EVENT_KEYS = frozenset({"kind", "role", "timestamp", "text"})
#: 允许在为空时省略的键（envelope 噪音，占体积的大头）
_OMITTABLE_EVENT_KEYS = frozenset(
    {"tool_name", "tool_call_id", "payload", "raw_text", "label", "summary", "collapsed", "toolName"}
)
#: 即便 slim 也必须整段丢弃的 kind（前端 buildTurns 从未渲染）
DROPPED_KINDS = frozenset({"opaque"})
#: text 需要裁剪的 kind（message 不允许出现在这里）
TEXT_TRUNCATED_KINDS = frozenset({"tool_result", "thinking"})


class DetailError(Exception):
    """详情构建失败（带 HTTP 状态码，由 web 层原样转成错误响应）。"""

    def __init__(self, message: str, status: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------
# 体积估算与 LRU
# --------------------------------------------------------------------------
def _approx_json_bytes(value: Any, depth: int = 0) -> int:
    """不序列化地估算一个 JSON 值的字节数（payload 可能几百 KB，序列化太贵）。"""
    if depth > 12:
        return 8
    if value is None:
        return 4
    if isinstance(value, bool):
        return 5
    if isinstance(value, (int, float)):
        return 8
    if isinstance(value, str):
        return len(value) + 2
    if isinstance(value, (list, tuple)):
        return 2 + sum(_approx_json_bytes(item, depth + 1) + 1 for item in value)
    if isinstance(value, dict):
        return 2 + sum(len(str(k)) + 3 + _approx_json_bytes(v, depth + 1) for k, v in value.items())
    return 8


def estimate_events_bytes(events: list[dict[str, Any]]) -> int:
    """估算事件数组常驻内存（按实测放大系数 ×2.5 计）。"""
    total = 0
    for event in events:
        total += 120  # dict 自身 + 7 个键的槽位
        total += len(str(event.get("text") or ""))
        total += len(str(event.get("raw_text") or ""))
        payload = event.get("payload")
        if payload is not None:
            total += _approx_json_bytes(payload)
    return int(total * ESTIMATE_FACTOR)


class _CacheEntry:
    __slots__ = ("key", "payload", "bytes")

    def __init__(self, key: tuple, payload: dict[str, Any], size_bytes: int) -> None:
        self.key = key
        self.payload = payload
        self.bytes = size_bytes


class DetailLRU:
    """解析结果 LRU：字节上限优先、条数上限兜底、single-flight 防击穿。"""

    def __init__(
        self,
        max_entries: int = LRU_MAX_ENTRIES,
        max_bytes: int = LRU_MAX_BYTES,
        single_entry_max: int = LRU_SINGLE_ENTRY_MAX,
    ) -> None:
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.single_entry_max = single_entry_max
        self._entries: OrderedDict[tuple, _CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._bytes = 0
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry.payload

    def put(self, key: tuple, payload: dict[str, Any], approx_bytes: int) -> None:
        if approx_bytes >= self.single_entry_max:
            return  # 单条太大：不入缓存，避免把别的会话全挤掉
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old.bytes
            entry = _CacheEntry(key, payload, approx_bytes)
            self._entries[key] = entry
            self._bytes += approx_bytes
            while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                if len(self._entries) <= 1:
                    break
                _, evicted = self._entries.popitem(last=False)
                self._bytes -= evicted.bytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "hits": self.hits,
                "misses": self.misses,
                "parser_version": PARSER_VERSION,
            }


#: 进程级单例（web 层直接复用）
DETAIL_CACHE = DetailLRU()


# --------------------------------------------------------------------------
# ETag
# --------------------------------------------------------------------------
def base_etag(mtime_ns: int, size: int) -> str:
    """只依赖文件元信息的基础指纹（解析前即可算出）。"""
    return hashlib.sha1(f"{int(mtime_ns)}:{int(size)}".encode("utf-8")).hexdigest()


def compute_etag(
    base: str,
    catalog_id: str,
    fmt: str,
    *,
    sharded: bool = True,
    turn_offset: int = 0,
    turn_limit: int = 0,
    slim: int = 1,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """详情响应 ETag：基础指纹 + 会话标识 + **全部分片参数**。

    分片参数必须进 ETag：否则同一文件的不同分片会算出同一个 ETag，
    条件请求会把「第 81–85 轮」当成「第 1–5 轮」304 掉。
    """
    raw = ":".join(
        [
            base,
            str(catalog_id or ""),
            str(fmt or ""),
            f"v{PARSER_VERSION}",
            "shard" if sharded else "full",
            str(int(turn_offset)),
            str(int(turn_limit)),
            str(int(slim)),
            str(int(max_bytes)),
        ]
    )
    return '"' + hashlib.sha1(raw.encode("utf-8")).hexdigest() + '"'


# --------------------------------------------------------------------------
# slim 裁剪
# --------------------------------------------------------------------------
def _truncate(text: str, cap: int) -> tuple[str, bool]:
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def slim_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """单事件裁剪；返回 `None` 表示整条丢弃（opaque）。"""
    kind = event.get("kind")
    if kind in DROPPED_KINDS:
        return None

    out: dict[str, Any] = {}
    hidden_chars = int(event.get("hidden_chars") or 0)
    truncated = bool(event.get("truncated") or False)
    # `truncated_chars` 只统计 **text 字段**被服务端隐藏的字符数（不含 raw_text）：
    # 前端据此提示"还有 N 字未显示"，并自行决定是否回源 /api/session/event。
    text_hidden = 0

    for key, value in event.items():
        if key in _OMITTABLE_EVENT_KEYS and _is_blank(value):
            continue
        if key not in _ALWAYS_KEEP_EVENT_KEYS and _is_blank(value):
            continue
        out[key] = value

    # text 裁剪：只对 tool_result / thinking（message 正文必须完整）
    text = out.get("text")
    if isinstance(text, str) and text and kind in TEXT_TRUNCATED_KINDS:
        clipped, was_truncated = _truncate(text, TR_CAP)
        if was_truncated:
            out["text"] = clipped
            text_hidden = len(text) - TR_CAP
            hidden_chars += text_hidden
            truncated = True

    # raw_text（被清洗掉的原始用户输入）同样限长
    raw_text = out.get("raw_text")
    if isinstance(raw_text, str) and len(raw_text) > RAW_TEXT_CAP:
        out["raw_text"] = raw_text[:RAW_TEXT_CAP]
        hidden_chars += len(raw_text) - RAW_TEXT_CAP
        truncated = True

    # payload：序列化后超过上限就整体省略（前端只从里面抽一行摘要）
    payload = out.get("payload")
    if payload is not None:
        payload_bytes = _approx_json_bytes(payload)
        if payload_bytes > PAYLOAD_CAP_BYTES:
            out["payload"] = {"_omitted": True, "bytes": payload_bytes}
        elif payload_bytes <= 0 or (isinstance(payload, (dict, list)) and len(payload) == 0):
            out.pop("payload", None)

    if truncated:
        out["truncated"] = True
        if hidden_chars > 0:
            out["hidden_chars"] = hidden_chars
        if text_hidden > 0:
            out["truncated_chars"] = text_hidden
    elif "truncated" in out:
        out.pop("truncated", None)

    return out


def _is_blank(value: Any) -> bool:
    """空值判定：只认 None / "" / [] / {}；0 与 False 不算空（语义位）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def slim_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量裁剪，保持顺序，丢弃 `None`。"""
    out: list[dict[str, Any]] = []
    for event in events:
        slimmed = slim_event(event)
        if slimmed is not None:
            out.append(slimmed)
    return out


# --------------------------------------------------------------------------
# 分片
# --------------------------------------------------------------------------
def _json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


#: 公开别名（web 层 `/api/session/event` 计算单事件体积用）
approx_json_bytes = _approx_json_bytes


def build_shard(
    events: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    turn_offset: int,
    turn_limit: int,
    slim: int,
    max_bytes: int,
) -> dict[str, Any]:
    """按轮切片 + 字节预算，返回分片结果（不含 meta）。

    字节预算是**整轮粒度**的：宁可少给一轮，也不给"半个轮次"——
    半个轮次会让四段式渲染缺段，用户看到的是坏数据而不是"还没加载"。
    """
    selected = turns_service.select_spans(spans, turn_offset, turn_limit)

    if not selected:
        return {
            "events": [],
            "turn_index": [],
            "event_index": [],
            "spans": [],
            "turn_offset": _first_turn_number(spans, turn_offset),
            "turn_limit": turn_limit,
            "has_more": False,
            "next_turn_offset": 0,
            "events_shipped": 0,
            "turns_dropped_by_budget": 0,
            "budget_hit": False,
        }

    chunks: list[list[dict[str, Any]]] = []
    chunk_indices: list[list[int]] = []
    used = 0
    budget_hit = False
    for span in selected:
        chunk: list[dict[str, Any]] = []
        chunk_idx: list[int] = []
        for offset, event in enumerate(events[span["start"]: span["end"]]):
            if slim:
                slimmed = slim_event(event)
                if slimmed is None:  # opaque 被丢弃，绝对下标随之跳过
                    continue
                chunk.append(slimmed)
            else:
                chunk.append(event)
            chunk_idx.append(span["start"] + offset)
        chunk_bytes = _json_bytes(chunk)
        if chunks and used + chunk_bytes > max_bytes:
            budget_hit = True
            break
        chunks.append(chunk)
        chunk_indices.append(chunk_idx)
        used += chunk_bytes

    kept_spans = selected[: len(chunks)]
    shipped_events: list[dict[str, Any]] = []
    # turn_index / event_index 必须**与裁剪后的事件数组逐项对齐**：slim 会丢弃
    # opaque 事件，若直接切全量数组的下标就会错位。每个 span 恰好是一轮，
    # 因此 turn 号按 span 广播，事件绝对下标逐条对应。
    shipped_turn_index: list[int] = []
    shipped_event_index: list[int] = []
    # 上一版这里直接透传 `compute_turn_spans` 的 span，导致 `turns[].start/end`
    # 落在**原始全量事件**（6635 条）的下标空间里，而客户端只收到 396 条 ——
    # 按最自然的 `events.slice(start,end)` 取第 1 轮会把全部事件并进第 1 轮。
    # 现在把 start/end **重映射到已下发 events 的下标空间**（永远可安全切片），
    # 原始下标改名 `raw_start/raw_end` 保留，仅供与 events_total_raw 对账/日志。
    remapped_spans: list[dict[str, Any]] = []
    cursor = 0
    for span, chunk, chunk_idx in zip(kept_spans, chunks, chunk_indices):
        shipped_events.extend(chunk)
        shipped_turn_index.extend([int(span["index"])] * len(chunk))
        shipped_event_index.extend(chunk_idx)
        remapped_spans.append({
            "index": span["index"],
            "start": cursor,
            "end": cursor + len(chunk),
            "events_count": len(chunk),
            "raw_start": span["start"],
            "raw_end": span["end"],
            "user_preview": span.get("user_preview", ""),
            "timestamp": span.get("timestamp", ""),
        })
        cursor += len(chunk)

    start_position = turns_service.resolve_start_position(spans, turn_offset)
    has_more = (start_position + len(kept_spans)) < len(spans)

    return {
        "events": shipped_events,
        "turn_index": shipped_turn_index,
        # 每条事件的**绝对下标**（对齐 events 数组），前端据此调 /api/session/event 回源全文
        "event_index": shipped_event_index,
        "spans": remapped_spans,
        "turn_offset": kept_spans[0]["index"],
        "turn_limit": turn_limit,
        "has_more": has_more,
        # 服务端把"下一页从哪一轮开始"直接告诉消费方。
        # 因为字节预算会整轮丢弃尾部（`turn_limit=8` 可能只回 5 轮），
        # 消费方若按 `offset += turn_limit` 推进就会永久漏轮；用这个字段推进才安全。
        "next_turn_offset": (kept_spans[-1]["index"] + 1) if has_more else 0,
        "events_shipped": len(shipped_events),
        "turns_dropped_by_budget": len(selected) - len(kept_spans),
        "budget_hit": budget_hit,
    }


def _first_turn_number(spans: list[dict[str, Any]], turn_offset: int) -> int:
    if not spans:
        return 0
    start_position = turns_service.resolve_start_position(spans, turn_offset)
    if start_position >= len(spans):
        return len(spans) + 1
    return spans[start_position]["index"]


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------
def query_int(query: dict[str, list[str]], name: str, default: int) -> int:
    """从 `parse_qs` 结果里取整数参数，非法值回落到默认值。"""
    raw = query.get(name, [None])[0]
    if raw is None or raw == "":
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def is_sharded(query: dict[str, list[str]]) -> bool:
    """是否走了"分片模式"（任一新增参数出现即为真）。"""
    return any(key in query for key in SHARD_KEYS)


# --------------------------------------------------------------------------
# 对外主入口
# --------------------------------------------------------------------------
def stat_path(path: Any) -> tuple[int, int]:
    """返回 `(mtime_ns, size)`；不存在或不可读时返回 `(0, 0)`。"""
    if path is None:
        return 0, 0
    try:
        stat = path.stat()
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return 0, 0


_stat_path = stat_path


def load_cached(probe: dict[str, Any], loader: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """带 LRU 的载荷加载（详情接口与"详情内检索"共用同一份缓存）。

    key = `(catalog_id, mtime_ns, size, PARSER_VERSION)`；文件不存在时不缓存
    （下一次请求会重新尝试，避免把"文件暂时缺失"固化成缓存）。
    """
    catalog_id = str(probe.get("catalog_id") or "")
    mtime_ns, size = stat_path(probe.get("path"))
    if mtime_ns:
        cached = DETAIL_CACHE.get((catalog_id, mtime_ns, size, PARSER_VERSION))
        if cached is not None:
            return cached
    payload = loader()
    if mtime_ns:
        DETAIL_CACHE.put(
            (catalog_id, mtime_ns, size, PARSER_VERSION),
            payload,
            estimate_events_bytes(payload.get("events") or []),
        )
    return payload


def serve(
    handler: Any,
    query: dict[str, list[str]],
    probe: dict[str, Any],
    loader: Callable[[], dict[str, Any]],
) -> None:
    """处理一次 `/api/session/detail` 请求。

    Args:
        handler: `web_app.RequestHandler` 实例（duck typing：需要 `headers`、
            `send_json`、`send_not_modified`）。
        query: `urllib.parse.parse_qs` 的结果。
        probe: 轻量探针结果（`catalog_id` / `format` / `path`），不含事件。
        loader: 真正解析并返回**全量** payload 的回调（可能抛 `DetailError`）。

    流程：算 ETag → 判 304（不解析） → LRU → 解析 → 分片 → 发送。
    """
    started = time.perf_counter()
    catalog_id = str(probe.get("catalog_id") or "")
    fmt = str(probe.get("format") or "")
    mtime_ns, size = stat_path(probe.get("path"))

    sharded = is_sharded(query)
    turn_offset = query_int(query, "turn_offset", 0)
    turn_limit = query_int(query, "turn_limit", DEFAULT_TURN_LIMIT) if sharded else 0
    slim = query_int(query, "slim", 1) if sharded else 0
    max_bytes = query_int(query, "max_bytes", DEFAULT_MAX_BYTES)
    if max_bytes <= 0:
        max_bytes = DEFAULT_MAX_BYTES

    etag = compute_etag(
        base_etag(mtime_ns, size),
        catalog_id,
        fmt,
        sharded=sharded,
        turn_offset=turn_offset,
        turn_limit=turn_limit,
        slim=slim,
        max_bytes=max_bytes,
    )

    # 预解析 304：一次文件解析都不做（这是"二次打开详情 ≤30 ms"的全部秘密）
    if str(handler.headers.get("If-None-Match") or "") == etag:
        handler.send_not_modified(etag, elapsed_ms=(time.perf_counter() - started) * 1000.0)
        return

    try:
        payload = load_cached(probe, loader)
    except DetailError as exc:
        handler.send_json({"error": exc.message}, status=exc.status)
        return
    except Exception as exc:  # noqa: BLE001 - 兜底，绝不让单个会话把服务打挂
        handler.send_json({"error": f"Failed to parse session content: {exc}"}, status=500)
        return

    response = _compose(payload, sharded, turn_offset, turn_limit, slim, max_bytes)
    response["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
    handler.send_json(response, etag=etag)


def _compose(
    payload: dict[str, Any],
    sharded: bool,
    turn_offset: int,
    turn_limit: int,
    slim: int,
    max_bytes: int,
) -> dict[str, Any]:
    """把全量 payload 组合成最终响应（旧模式 = 全量，分片模式 = 裁剪 + 切片）。"""
    events: list[dict[str, Any]] = list(payload.get("events") or [])
    spans = turns_service.compute_turn_spans(events)
    total_turns = len(spans)

    if not sharded:
        # 旧行为：events 一个不动（旧页 `/` 与脚本依赖全量），只做新增字段
        response: dict[str, Any] = dict(payload)
        response["events"] = events
        response["events_count"] = payload.get("events_count", len(events))
        response["events_total_raw"] = len(events)
        response["turns_total"] = total_turns
        response["turn_offset"] = 0
        response["turn_limit"] = 0
        response["has_more"] = False
        response["next_turn_offset"] = 0
        response["events_shipped"] = len(events)
        response["slim"] = 0
        response["turn_index"] = turns_service.turn_index_map(events)
        # 旧模式不裁剪 → 绝对下标就是 0..n-1，没必要再发一份（省 30 KB，
        # 保证无参响应字节数与改造前差异仍落在 ±1% 内）
        # turns[] 补齐与分片模式同形状的字段：此模式下 start/end 天然等于 raw_start/raw_end
        response["turns"] = [
            {
                "index": span["index"],
                "start": span["start"],
                "end": span["end"],
                "events_count": span["end"] - span["start"],
                "raw_start": span["start"],
                "raw_end": span["end"],
                "user_preview": span.get("user_preview", ""),
                "timestamp": span.get("timestamp", ""),
            }
            for span in spans
        ]
        return response

    shard = build_shard(events, spans, turn_offset, turn_limit, slim, max_bytes)
    response = dict(payload)
    response["events"] = shard["events"]
    # events_count 保持旧语义（解析后的**全量**事件数），前端用它显示"6635 条事件"
    response["events_count"] = payload.get("events_count", len(events))
    response["events_total_raw"] = len(events)
    response["events_shipped"] = shard["events_shipped"]
    response["turns_total"] = total_turns
    response["turn_offset"] = shard["turn_offset"]
    response["turn_limit"] = shard["turn_limit"]
    response["has_more"] = shard["has_more"]
    response["next_turn_offset"] = shard["next_turn_offset"]
    response["turns_dropped_by_budget"] = shard["turns_dropped_by_budget"]
    response["budget_hit"] = shard["budget_hit"]
    response["slim"] = 1 if slim else 0
    response["turn_index"] = shard["turn_index"]
    response["event_index"] = shard["event_index"]
    response["turns"] = shard["spans"]
    return response


# --------------------------------------------------------------------------
# 会话内检索（详情内检索走后端）
# --------------------------------------------------------------------------
def snippet_for(text: str, needle: str, radius: int = 60) -> str:
    """在文本里截一段命中上下文（小写匹配，保留原文大小写）。"""
    if not text:
        return ""
    lowered = text.lower()
    position = lowered.find(needle.lower()) if needle else -1
    if position < 0:
        head = text.strip().replace("\n", " ")
        return head[: radius * 2] + ("…" if len(head) > radius * 2 else "")
    start = max(0, position - radius)
    end = min(len(text), position + len(needle) + radius)
    body = text[start:end].replace("\n", " ")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{body}{suffix}"


def search_in_events(
    events: list[dict[str, Any]], needle: str, limit: int = 50
) -> list[dict[str, Any]]:
    """在事件数组里做内存全文检索（FTS 未覆盖该会话时的回退路径）。"""
    needle = (needle or "").strip()
    if not needle:
        return []
    index_map = turns_service.turn_index_map(events)
    matches: list[dict[str, Any]] = []
    seen_turns: set[int] = set()
    for position, event in enumerate(events):
        text = event.get("text") or ""
        if not isinstance(text, str) or not text:
            payload = event.get("payload")
            text = json.dumps(payload, ensure_ascii=False) if payload else ""
        if needle.lower() not in text.lower():
            continue
        turn_index = index_map[position] if position < len(index_map) else 0
        if turn_index in seen_turns:
            continue
        seen_turns.add(turn_index)
        matches.append(
            {
                "turn_index": turn_index,
                "snippet": snippet_for(text, needle),
                "kind": event.get("kind") or "",
                "role": event.get("role") or "",
            }
        )
        if len(matches) >= limit:
            break
    return matches
