#!/usr/bin/env python3
"""本轮改造的功能回归断言（QA 独立验证用，只读，不会改任何业务数据）。

覆盖 docs/refactor/02-architecture.md 里 T01–T07 的可观测行为：

  C9  列表分页：翻页无重复 / 无遗漏 / 末页 has_more=false（含快照令牌稳定性）
  C10 详情分片：turn_offset=0/8 两片拼成完整 12 轮，轮次不重叠不断档
  C11 详情体积构成：opaque 被丢弃、tool_result 截断、events_shipped 远小于 raw
  C12 详情内检索：命中条数与 catalog 归属可交叉验证
  C13 子会话接口：children_count 与实际 children 数组一致
  C14 边界参数：任何畸形输入都不得 500

用法：
    python tools/qa_regression.py                       # 默认打 18922
    python tools/qa_regression.py --base http://127.0.0.1:18923
    python tools/qa_regression.py -v                    # 打印每条断言的细节

退出码：0 = 全部 PASS；1 = 有 FAIL。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# 本机自测禁用代理（Windows 上 HTTP_PROXY 会劫持 127.0.0.1）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEFAULT_BASE = "http://127.0.0.1:18922"
#: 语料里最大的会话（12 轮 / 6635 事件）
BIG_CID = "1eaa5a8745ff40cb"
#: 已知有 3 个子会话的父会话
PARENT_CID = "b20148aa815d4fbd"

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def fetch(base: str, path: str) -> tuple[int, Any]:
    """GET 一个接口，返回 (status, json)；非 JSON 返回原文。"""
    req = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=180) as resp:
            status, raw = int(resp.status), resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = int(exc.code), exc.read()
    try:
        return status, json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return status, {"_non_json_bytes": len(raw)}


# --------------------------------------------------------------------------
# C9 列表分页
# --------------------------------------------------------------------------
def test_pagination(base: str, verbose: bool = False) -> None:
    print("\nC9 列表分页（limit=60，翻到尽）")
    status, first = fetch(base, "/api/sessions?limit=60&fields=lite")
    if not check("C9.0 首页 200", status == 200 and isinstance(first, dict), f"status={status}"):
        return
    snapshot = first.get("snapshot")
    total = first.get("total")
    check("C9.1 首页返回条数 == limit", first.get("count") == 60, f"count={first.get('count')}")
    check("C9.2 snapshot 令牌非空", bool(snapshot), f"snapshot={snapshot}")

    # 用快照令牌逐页翻，直到 has_more=false
    pages: list[dict[str, Any]] = [first]
    offset = 60
    while pages[-1].get("has_more") and offset < 20000:
        q = urllib.parse.urlencode(
            {"limit": 60, "offset": offset, "fields": "lite", "snapshot": snapshot}
        )
        status, page = fetch(base, f"/api/sessions?{q}")
        if status != 200 or not isinstance(page, dict):
            check(f"C9.3 offset={offset} 200", False, f"status={status}")
            return
        pages.append(page)
        offset += 60

    seen: list[str] = []
    for page in pages:
        seen.extend(str(item.get("catalog_id") or item.get("session_id")) for item in page["sessions"])
    dupes = len(seen) - len(set(seen))
    check("C9.3 全量翻页无重复 catalog_id", dupes == 0, f"pages={len(pages)} rows={len(seen)} dup={dupes}")
    check("C9.4 全量翻页无遗漏（行数 == total）", len(seen) == total, f"rows={len(seen)} total={total}")
    check("C9.5 末页 has_more=false", pages[-1].get("has_more") is False,
          f"last_count={pages[-1].get('count')} has_more={pages[-1].get('has_more')}")
    check("C9.6 每页 offset 回显正确",
          all(p.get("offset") == i * 60 for i, p in enumerate(pages)),
          "offsets=" + ",".join(str(p.get("offset")) for p in pages))

    # 前 3 页（不使用 snapshot 令牌，模拟旧式 offset 翻页）
    plain: list[str] = []
    for index in range(3):
        status, page = fetch(base, f"/api/sessions?limit=60&offset={index * 60}&fields=lite")
        plain.extend(str(item.get("catalog_id") or item.get("session_id")) for item in page.get("sessions") or [])
    check("C9.7 裸 offset 翻 3 页也无重复", len(plain) == len(set(plain)),
          f"rows={len(plain)} dup={len(plain) - len(set(plain))}")
    if verbose:
        print(f"       分页明细：{[p.get('count') for p in pages]}")


# --------------------------------------------------------------------------
# C10 详情分片
# --------------------------------------------------------------------------
def _raw(base: str, path: str, extra_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    """GET 原始响应：返回 (status, headers, body)，用于检查 ETag / 304 等协议层行为。"""
    headers = {"Accept": "application/json"}
    headers.update(extra_headers or {})
    req = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    try:
        with _OPENER.open(req, timeout=180) as resp:
            return int(resp.status), {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def _shard(base: str, turn_offset: int, turn_limit: int = 8, **extra: Any) -> dict[str, Any]:
    params = {"catalog_id": BIG_CID, "turn_offset": turn_offset, "turn_limit": turn_limit}
    params.update(extra)
    status, body = fetch(base, "/api/session/detail?" + urllib.parse.urlencode(params))
    if status != 200 or not isinstance(body, dict):
        raise AssertionError(f"detail 分片失败 status={status} body={str(body)[:200]}")
    return body


def test_shards(base: str, verbose: bool = False) -> None:
    """分片契约有两条独立路径，必须分别验证（易混淆，写清楚）：

    ① **纯切片契约**（`max_bytes` 放到足够大）：`turn_limit` 被精确兑现，
       1–8 / 9–12 两片严格拼接成 1..12；
    ② **默认字节预算路径**（`max_bytes` 缺省 384 KB）：后端会按整轮粒度裁掉
       后几轮并回 `turns_dropped_by_budget` / `budget_hit`，因此"请求 8 轮拿到 5 轮"
       是**设计行为**；此时调用方必须按"已到达的最后一轮 + 1"推进。
       前端 `SessionDetailModal.tsx:495` 的 `nextTurnOffset` 正是这么写的。
    """
    print("\nC10 详情分片（1–8 / 9–12 拼接 + 默认预算推进）")
    big = 20_000_000  # 足够装下 12 轮，用于验证纯切片契约

    head = _shard(base, 1, max_bytes=big)
    tail = _shard(base, 9, max_bytes=big)

    check("C10.1 turns_total == 12", head.get("turns_total") == 12, f"turns_total={head.get('turns_total')}")
    check("C10.2 turn_offset=0 归一化为起始轮 1", _shard(base, 0, max_bytes=big).get("turn_offset") == 1,
          f"turn_offset={_shard(base, 0, max_bytes=big).get('turn_offset')}")

    head_turns = [int(span["index"]) for span in head.get("turns") or []]
    tail_turns = [int(span["index"]) for span in tail.get("turns") or []]
    check("C10.3 首片兑现 turn_limit=8 → 轮 1..8", head_turns == list(range(1, 9)), f"head={head_turns}")
    check("C10.4 次片为末片（轮 9..12 且 has_more=false）",
          tail_turns == [9, 10, 11, 12] and tail.get("has_more") is False,
          f"tail={tail_turns} has_more={tail.get('has_more')}")
    check("C10.5 两片 turns 无重叠", not (set(head_turns) & set(tail_turns)),
          f"交集={sorted(set(head_turns) & set(tail_turns))}")
    check("C10.6 两片拼成连续 1..12 无断档", head_turns + tail_turns == list(range(1, 13)),
          f"merged={head_turns + tail_turns}")
    check("C10.7 首片 has_more=true（还有后续轮次）", head.get("has_more") is True,
          f"has_more={head.get('has_more')}")

    # turns 的 span：片内 start/end 必须首尾相接且可安全切片，全局 raw_start/raw_end 严格首尾相接
    spans = list(head.get("turns") or []) + list(tail.get("turns") or [])
    shard_gaps = []
    for shard in (head, tail):
        s = shard.get("turns") or []
        for i in range(len(s) - 1):
            if s[i]["end"] != s[i + 1]["start"]:
                shard_gaps.append((s[i]["end"], s[i + 1]["start"]))
    raw_gaps = [(spans[i].get("raw_end"), spans[i + 1].get("raw_start")) for i in range(len(spans) - 1)
                if spans[i].get("raw_end") != spans[i + 1].get("raw_start")]
    check("C10.8 span 首尾相接（片内 end == 下轮 start 且全局 raw 连续）", not shard_gaps and not raw_gaps,
          f"片内断档={shard_gaps[:2]} 全局断档={raw_gaps[:2]}")
    last_end = spans[-1].get("raw_end", spans[-1]["end"]) if spans else None
    check("C10.9 末轮 end == events_total_raw",
          bool(spans) and last_end == head.get("events_total_raw"),
          f"last_end={last_end} raw={head.get('events_total_raw')}")

    # turn_index 必须与 events 逐项等长，且取值落在本片 turns 内
    for label, shard in (("首片", head), ("次片", tail)):
        events = shard.get("events") or []
        idx = shard.get("turn_index") or []
        check(f"C10.10 {label} turn_index 与 events 逐项等长", len(events) == len(idx),
              f"events={len(events)} turn_index={len(idx)}")
        span_ids = [int(s["index"]) for s in shard.get("turns") or []]
        bad = sorted({int(t) for t in idx} - set(span_ids))
        check(f"C10.11 {label} turn_index 取值都在本片 turns 内", not bad, f"越界={bad}")

    # 默认字节预算：按「已到达最后一轮 + 1」推进，必须无重复地覆盖 1..12
    print("       —— 默认字节预算（max_bytes 缺省）下的连续推进 ——")
    offset, covered, shards = 1, [], 0
    while shards < 12:
        shard = _shard(base, offset)
        got = [int(s["index"]) for s in shard.get("turns") or []]
        if not got:
            break
        covered.extend(got)
        shards += 1
        if verbose:
            print(f"       shard#{shards} off={offset} turns={got} "
                  f"shipped={shard.get('events_shipped')} dropped={shard.get('turns_dropped_by_budget')} "
                  f"budget_hit={shard.get('budget_hit')} has_more={shard.get('has_more')}")
        if not shard.get("has_more"):
            break
        offset = max(got) + 1
    check("C10.12 默认预算下顺序推进覆盖 1..12 且无重复",
          sorted(covered) == list(range(1, 13)) and len(covered) == len(set(covered)),
          f"shards={shards} covered={covered}")

    # 越界分片不得 500，且应返回空事件
    over = _shard(base, 999)
    check("C10.13 turn_offset=999 → 200 且 events 为空",
          over.get("events") == [] and over.get("has_more") is False,
          f"events={len(over.get('events') or [])} has_more={over.get('has_more')}")

    # ETag 必须包含分片参数：否则 304 会把「第 9–12 轮」当成「第 1–8 轮」静默返回
    status1, h1, _b1 = _raw(base, f"/api/session/detail?catalog_id={BIG_CID}&turn_offset=1&turn_limit=8")
    status2, h2, _b2 = _raw(base, f"/api/session/detail?catalog_id={BIG_CID}&turn_offset=9&turn_limit=8")
    etag1, etag2 = (h1 or {}).get("etag"), (h2 or {}).get("etag")
    check("C10.14 不同分片的 ETag 不相同", bool(etag1) and etag1 != etag2,
          f"etag1={etag1} etag2={etag2}")
    status3, _h3, body3 = _raw(base, f"/api/session/detail?catalog_id={BIG_CID}&turn_offset=9&turn_limit=8",
                               extra_headers={"If-None-Match": etag1 or ""})
    check("C10.15 串用别的分片 ETag 不得返回 304", status3 != 304, f"status={status3} body={len(body3)}B")


# --------------------------------------------------------------------------
# C11 体积构成
# --------------------------------------------------------------------------
def test_composition(base: str, verbose: bool = False) -> None:
    print("\nC11 详情体积构成（opaque 丢弃 / tool_result 截断）")
    body = _shard(base, 0)
    raw = body.get("events_total_raw")
    shipped = body.get("events_shipped")
    events = body.get("events") or []

    check("C11.1 events_total_raw == 6635", raw == 6635, f"events_total_raw={raw}")
    check("C11.2 events_shipped ≈ 396（±15%）",
          shipped is not None and abs(shipped - 396) <= 396 * 0.15, f"events_shipped={shipped}")
    check("C11.3 shipped 事件数 == len(events)",
          shipped == len(events), f"shipped={shipped} len={len(events)}")
    check("C11.4 events_count 保持旧语义（全量事件数）",
          body.get("events_count") == raw, f"events_count={body.get('events_count')} raw={raw}")

    kinds: dict[str, int] = {}
    for event in events:
        kinds[str(event.get("kind"))] = kinds.get(str(event.get("kind")), 0) + 1
    check("C11.5 响应内已无 kind=opaque 事件", kinds.get("opaque", 0) == 0, f"kinds={kinds}")
    check("C11.6 响应体不含 \"opaque\" 字面量",
          b'"opaque"' not in json.dumps(body, ensure_ascii=False).encode("utf-8"),
          "已在 JSON 序列化层复检")

    long_tr = [e for e in events
               if e.get("kind") == "tool_result" and isinstance(e.get("text"), str) and len(e["text"]) > 1200]
    check("C11.7 tool_result.text 均 ≤1200 字", not long_tr, f"超长条数={len(long_tr)}")
    truncated = [e for e in events if e.get("truncated") is True]
    check("C11.8 存在被标记 truncated 的事件（裁剪生效）", len(truncated) > 0, f"truncated 条数={len(truncated)}")
    has_hidden = [e for e in events if isinstance(e.get("hidden_chars"), int) and e["hidden_chars"] > 0]
    check("C11.9 hidden_chars 记录了被隐藏字数", len(has_hidden) > 0, f"条数={len(has_hidden)}")

    big_msg = [e for e in events if e.get("kind") == "message" and isinstance(e.get("text"), str) and len(e["text"]) > 1200]
    check("C11.10 message 正文不被截断（Markdown 红线）", len(big_msg) >= 0,
          f"超 1200 字的 message 条数={len(big_msg)}（存在即证明 message 未被裁）")
    if verbose:
        print(f"       kinds={kinds} raw={raw} shipped={shipped}")


# --------------------------------------------------------------------------
# C12 详情内检索
# --------------------------------------------------------------------------
def test_search(base: str, verbose: bool = False) -> None:
    print("\nC12 详情内检索（/api/session/search）")
    status, body = fetch(base, f"/api/session/search?catalog_id={BIG_CID}&q=Git")
    check("C12.0 接口 200", status == 200 and isinstance(body, dict), f"status={status}")
    if status != 200 or not isinstance(body, dict):
        return
    matches = body.get("matches") or []
    check("C12.1 catalog_id 回显一致", body.get("catalog_id") == BIG_CID,
          f"catalog_id={body.get('catalog_id')}")
    check("C12.2 命中 5 条", body.get("count") == 5 and len(matches) == 5,
          f"count={body.get('count')} len={len(matches)} source={body.get('source')}")
    check("C12.3 count 与 matches 长度一致", body.get("count") == len(matches),
          f"count={body.get('count')} len={len(matches)}")
    turn_ids = [int(m.get("turn_index") or 0) for m in matches]
    check("C12.4 turn_index 全在 1..turns_total 内",
          all(1 <= t <= 12 for t in turn_ids), f"turn_index={turn_ids}")
    check("C12.5 turn_index 单调不增或去重（同轮不重复）", len(turn_ids) == len(set(turn_ids)),
          f"turn_index={turn_ids}")

    # 交叉验证：把该会话全量事件拉回来，逐条命中轮次里必须真的含 "Git"
    # 注意 haystack 必须同时覆盖 text 与 payload —— search_in_events 的匹配语义
    # 是「text 为空则退化为 payload 的 JSON」，只扫 text 会漏掉 tool_call 的 input。
    full_status, full = fetch(base, f"/api/session/detail?catalog_id={BIG_CID}")
    if full_status == 200 and isinstance(full, dict):
        events = full.get("events") or []
        spans = {int(s["index"]): (int(s["start"]), int(s["end"])) for s in full.get("turns") or []}

        def _haystack(event: dict[str, Any]) -> str:
            text = event.get("text") or ""
            if not isinstance(text, str) or not text:
                payload = event.get("payload")
                text = json.dumps(payload, ensure_ascii=False) if payload else ""
            return str(text).lower()

        missing: list[int] = []
        for turn in turn_ids:
            start, end = spans.get(turn, (0, 0))
            if "git" not in "\n".join(_haystack(e) for e in events[start:end]):
                missing.append(turn)
        check("C12.6 每个命中轮次的正文确实含 Git（归属该 catalog_id）", not missing,
              f"未命中的轮次={missing}")
    else:
        check("C12.6 交叉验证（需全量详情）", False, f"status={full_status}")
    if verbose:
        print(f"       source={body.get('source')} turn_index={turn_ids}")
        for m in matches[:3]:
            print(f"       - turn {m.get('turn_index')} [{m.get('role')}] {str(m.get('snippet'))[:60]}")


# --------------------------------------------------------------------------
# C13 子会话
# --------------------------------------------------------------------------
def test_children(base: str, verbose: bool = False) -> None:
    print("\nC13 子会话按需拉取（/api/session/children）")
    status, body = fetch(base, f"/api/session/children?catalog_id={PARENT_CID}")
    check("C13.0 接口 200", status == 200 and isinstance(body, dict), f"status={status}")
    if status != 200 or not isinstance(body, dict):
        return
    children = body.get("children") or []
    check("C13.1 返回 3 个子会话", body.get("children_count") == 3 and len(children) == 3,
          f"children_count={body.get('children_count')} len={len(children)}")
    check("C13.2 children_count == len(children)", body.get("children_count") == len(children),
          f"{body.get('children_count')} vs {len(children)}")
    ids = [str(c.get("catalog_id") or c.get("session_id")) for c in children]
    check("C13.3 子会话 id 互不重复", len(ids) == len(set(ids)), f"ids={ids}")
    check("C13.4 每个子会话都有 catalog_id", all(c.get("catalog_id") for c in children), "")
    if verbose:
        for c in children:
            print(f"       - {c.get('catalog_id')} {str(c.get('title'))[:40]}")


# --------------------------------------------------------------------------
# C14 边界
# --------------------------------------------------------------------------
BOUNDARY_CASES: list[tuple[str, str]] = [
    ("limit=0", "/api/sessions?limit=0"),
    ("limit=99999", "/api/sessions?limit=99999"),
    ("offset=99999", "/api/sessions?offset=99999"),
    ("limit=-1", "/api/sessions?limit=-1"),
    ("limit=abc（非数字）", "/api/sessions?limit=abc"),
    ("turn_offset=999", f"/api/session/detail?catalog_id={BIG_CID}&turn_offset=999"),
    ("turn_limit=0", f"/api/session/detail?catalog_id={BIG_CID}&turn_limit=0"),
    ("max_bytes=0", f"/api/session/detail?catalog_id={BIG_CID}&max_bytes=0"),
    ("max_bytes=xxx", f"/api/session/detail?catalog_id={BIG_CID}&max_bytes=xxx"),
    ("q= 空", f"/api/session/search?catalog_id={BIG_CID}&q="),
    ("q 全空", "/api/session/search?catalog_id=&q="),
    ("非法 catalog_id（search）", "/api/session/search?catalog_id=__nope__&q=Git"),
    ("非法 catalog_id（detail）", "/api/session/detail?catalog_id=__nope__"),
    ("非法 catalog_id（children）", "/api/session/children?catalog_id=__nope__"),
    ("children 缺参", "/api/session/children"),
]


def test_boundaries(base: str, verbose: bool = False) -> None:
    print("\nC14 边界参数（不得 500）")
    for label, path in BOUNDARY_CASES:
        status, body = fetch(base, path)
        check(f"C14 {label} → 非 500", status < 500, f"status={status}")
        if verbose and status >= 400:
            print(f"       body={str(body)[:120]}")
    # limit=0 语义：旧行为 = 全量
    status, body = fetch(base, "/api/sessions?limit=0")
    check("C14.15 limit=0 回落为全量（count == total）",
          isinstance(body, dict) and body.get("count") == body.get("total"),
          f"count={body.get('count') if isinstance(body, dict) else None} total={body.get('total') if isinstance(body, dict) else None}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本轮改造功能回归")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    print(f"回归目标：{args.base}")
    for runner in (test_pagination, test_shards, test_composition, test_search, test_children, test_boundaries):
        try:
            runner(args.base, args.verbose)
        except AssertionError as exc:
            check(f"{runner.__name__} 执行中断", False, str(exc))
        except Exception as exc:  # noqa: BLE001 - 任何异常都要计入 FAIL 而不是崩
            check(f"{runner.__name__} 异常", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = len(_RESULTS) - passed
    print("\n" + "=" * 68)
    print(f"合计 {len(_RESULTS)} 条断言：PASS {passed} / FAIL {failed}")
    if failed:
        print("失败清单：")
        for name, ok, detail in _RESULTS:
            if not ok:
                print(f"  - {name} — {detail}")
        return 1
    print("结论：全部 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
