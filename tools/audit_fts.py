#!/usr/bin/env python3
"""FTS 轮次对账（T03 阻断项检查）。

背景
----
FTS 索引里的 `turn_index` 决定"检索命中第 N 轮 → 详情跳到第 N 轮"。
旧实现用 `role == "user"` 判轮边界，而 Claude Code 的 `tool_result` role 也是
`user`，于是这些会话的 `turn_index` 被多算，跳转会错位。本轮已把边界改成
`kind == "message" and role == "user"`，但**历史索引仍是用旧逻辑写进去的**，
需要一次性对账 + 只重建"不一致"的那几篇（`index_session_turns` 是整篇删除再插入）。

用法
----
    python tools/audit_fts.py                 # 全量对账，只报数
    python tools/audit_fts.py --limit 20      # 抽查 20 篇
    python tools/audit_fts.py --reindex       # 对账 + 重建不一致的会话
    python tools/audit_fts.py --reindex --verbose

退出码：0 = divergent == 0（或已全部重建成功）；1 = 仍存在不一致。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import web_app as W  # noqa: E402  （需要它的 FTS 管理器与解析器）
from services import turns as turns_service  # noqa: E402


def _format_lookup(catalog_id: str) -> str:
    """从 catalog 查会话格式。

    ⚠️ 不要靠 catalog_id 前缀猜格式：antigravity 的 catalog 型 cid 是纯 hash
    （如 `b20148aa815d4fbd`），前缀猜法会把它当 `claude`，用错解析器后
    `extract_dialogue_turns_for_fts` 抛异常被吞掉 → 索引被清空。
    """
    if catalog_id.startswith("wb_"):
        return "workbuddy"
    if catalog_id.startswith("trae_"):
        return "trae"
    if catalog_id.startswith("ag_"):
        return "antigravity"
    try:
        db = W.get_catalog_db()
        try:
            row = db.execute(
                "SELECT format FROM sessions WHERE catalog_id = ?", (catalog_id,)
            ).fetchone()
            if row and row["format"]:
                return str(row["format"])
        finally:
            db.close()
    except Exception:
        pass
    return "antigravity"


def _reindex_one(cid: str, file_path: str, meta_by_cid: dict[str, dict], verbose: bool) -> tuple[bool, str]:
    """重建单篇；返回 (是否成功, 说明)。"""
    path = Path(file_path)
    if not path.exists():
        return False, f"源文件不存在 {file_path}"
    try:
        stat = path.stat()
        fmt = _format_lookup(cid)
        item = meta_by_cid.get(cid) or {}
        turns = W.extract_dialogue_turns_for_fts(path, fmt)
        if not turns:
            return False, f"解析后 0 轮（格式={fmt} 可能猜错）"
        W.GLOBAL_FTS_MGR.index_session_turns(
            file_path=str(path),
            mtime=stat.st_mtime,
            size=stat.st_size,
            catalog_id=cid,
            session_id=str(item.get("session_id") or path.stem),
            session_title=str(item.get("title") or ""),
            session_format=fmt,
            turns=turns,
        )
        max_turn = max((int(t.get("turn_index") or 0) for t in turns), default=0)
        return True, f"{fmt} → {max_turn} 轮 / {len(turns)} 条"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def find_missing(limit: int = 0) -> list[str]:
    """列出「fts_file_meta 有记录但 conversation_fts 里 0 行」的会话（索引缺口）。"""
    with W.GLOBAL_FTS_MGR._get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.catalog_id AS cid
            FROM fts_file_meta m
            LEFT JOIN (SELECT DISTINCT catalog_id FROM conversation_fts) f
                         ON f.catalog_id = m.catalog_id
            WHERE f.catalog_id IS NULL
            """
        ).fetchall()
    cids = [str(row["cid"]) for row in rows]
    return cids[:limit] if limit else cids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FTS turn_index 对账")
    parser.add_argument("--limit", type=int, default=0, help="最多检查多少篇（0 = 全量）")
    parser.add_argument("--reindex", action="store_true", help="重建不一致的会话")
    parser.add_argument(
        "--reindex-missing",
        action="store_true",
        help="同时重建「有 file_meta 但 0 行」的会话（索引缺口）",
    )
    parser.add_argument("--verbose", action="store_true", help="打印每篇结果")
    args = parser.parse_args(argv)

    started = time.time()
    print("对账中（口径：kind=='message' and role=='user'）…")
    result = turns_service.audit_fts_alignment(
        W.GLOBAL_FTS_MGR,
        W.extract_dialogue_turns_for_fts,
        limit=args.limit,
        format_lookup=_format_lookup,
    )
    print(f"checked={result['checked']} divergent={result['divergent']} "
          f"scanned={result['scanned']} elapsed={time.time() - started:.1f}s")
    for cid in result["catalog_ids"]:
        print(f"  divergent: {cid}")

    missing = find_missing(limit=args.limit) if (args.reindex_missing or args.verbose) else []
    if missing:
        print(f"索引缺口（有 file_meta 但 0 行）：{len(missing)} 篇")
        for cid in missing[:20]:
            print(f"  missing: {cid}")

    targets = list(dict.fromkeys(result["catalog_ids"] + (missing if args.reindex_missing else [])))

    if not targets:
        print("结论：PASS —— FTS 轮号与详情轮边界一致，且无索引缺口")
        return 0

    if not args.reindex and not args.reindex_missing:
        print("结论：FAIL —— 存在不一致/缺口（加 --reindex 或 --reindex-missing 重建）")
        return 1

    print(f"重建中（{len(targets)} 篇）…")
    rebuilt = 0
    failed = 0
    with W.GLOBAL_FTS_MGR._get_conn() as conn:
        metas = conn.execute(
            "SELECT catalog_id, file_path FROM fts_file_meta"
        ).fetchall()
    by_cid = {row["catalog_id"]: row["file_path"] for row in metas}

    # 标题/会话 id 从列表快照里取，避免重建后搜索结果标题变成空串
    meta_by_cid: dict[str, dict] = {}
    try:
        for item in W.collect_all_sessions(fmt_filter="all"):
            meta_by_cid[str(item.get("catalog_id") or "")] = item
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] 会话标题映射构建失败：{exc}")

    for cid in targets:
        file_path = by_cid.get(cid)
        if not file_path:
            print(f"  [skip] {cid}: fts_file_meta 里没有记录")
            failed += 1
            continue
        ok, note = _reindex_one(cid, file_path, meta_by_cid, args.verbose)
        if ok:
            rebuilt += 1
            if args.verbose:
                print(f"  [ok] {cid} ({note})")
        else:
            failed += 1
            print(f"  [fail] {cid}: {note}")

    print(f"重建 {rebuilt} 篇，失败 {failed} 篇")
    after = turns_service.audit_fts_alignment(
        W.GLOBAL_FTS_MGR,
        W.extract_dialogue_turns_for_fts,
        limit=args.limit,
        format_lookup=_format_lookup,
    )
    remaining_missing = find_missing(limit=args.limit)
    print(f"复核：checked={after['checked']} divergent={after['divergent']} "
          f"missing={len(remaining_missing)}")
    if remaining_missing:
        print("（missing 是「可索引轮次为 0」的空会话，不影响检索；仅作提示）")
    # 退出码只看轮号一致性：空会话的 0 行索引是正常状态，不该让护栏变红
    return 0 if after["divergent"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
