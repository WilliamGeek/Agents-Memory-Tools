"""列表快照：内容指纹 + single-flight + 分页 + 折叠 + lite 投影。

为什么不是 TTL
--------------
原实现是「4 秒 TTL + 过期全量重算」：数据变不变跟 4 秒无关，
它只是把"重算频率"写成了一个魔数，于是出现两种坏状态——
用户在 4 秒内看到陈旧数据（文件刚改完），或者每次敲键都撞上过期点重算 589 ms。

改成**内容指纹**驱动：
    fingerprint = sha1(roots + catalog(count,max_id) + antigravity_dirs(count,max_mtime_ns) + generation)
* 文件没变 → 指纹不变 → 零重算（single-flight 保证并发请求只构建一次）；
* 文件变了 → 指纹变 → 建新快照并保留最近 3 个，供"分页途中的漂移请求"命中，
  `snapshot` 令牌把"同一批切片"锁定在同一个快照上，翻页不会重复或漏条；
* 写入类接口（delete / batch_delete / migrate / add_root / remove_root / refresh）
  调 `invalidate()` 使 `generation + 1`，指纹必然变化；
* `MAX_AGE=1800s` 只作为"指纹漏判"的兜底，不是新鲜度来源。

兼容性
------
`limit` 缺省或 0 → 全量返回，且响应字段与改造前**完全一致**
（`{sessions, count}` 是旧消费方唯一读的东西，`total/offset/limit/snapshot/meta`
都是新增键，旧页面 `/` 读不到也不会坏）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from . import fields as fields_service

#: 最近保留多少个快照（分页/漂移期间需要命中旧快照）
MAX_SNAPSHOTS = 3
#: 指纹兜底过期时间：只防"指纹漏判"，不作为新鲜度来源
MAX_AGE_SECONDS = 1800.0
#: 会话快照结构版本：新增子会话/Token 字段后必须递增，避免旧磁盘快照
#: 在没有数据变更时被直接复用，导致新字段缺失。
SNAPSHOT_SCHEMA_VERSION = 2


class Snapshot:
    """一次全量构建的结果（full + 惰性 lite 两份投影）。"""

    __slots__ = (
        "snapshot_id",
        "fingerprint",
        "generation",
        "built_at",
        "items_full",
        "build_ms",
        "_items_lite",
    )

    def __init__(
        self,
        snapshot_id: str,
        fingerprint: str,
        generation: int,
        items_full: list[dict[str, Any]],
        build_ms: float,
    ) -> None:
        self.snapshot_id = snapshot_id
        self.fingerprint = fingerprint
        self.generation = generation
        self.built_at = time.time()
        self.items_full = items_full
        self.build_ms = build_ms
        self._items_lite: list[dict[str, Any]] | None = None

    @property
    def items_lite(self) -> list[dict[str, Any]]:
        """惰性投影：只有真的有人请求 `fields=lite` 才付这份 CPU。"""
        if self._items_lite is None:
            self._items_lite = fields_service.project_lite_many(self.items_full)
        return self._items_lite

    def age_seconds(self, now: float | None = None) -> float:
        return (now or time.time()) - self.built_at


class SnapshotCache:
    """单例快照缓存：指纹判定 + single-flight + 排序 / 折叠 / 切片。"""

    def __init__(
        self,
        builder: Callable[[], list[dict[str, Any]]],
        fingerprint: Callable[[], str],
        max_snapshots: int = MAX_SNAPSHOTS,
        max_age: float = MAX_AGE_SECONDS,
        persist_path: Path | None = None,
    ) -> None:
        self._builder = builder
        self._fingerprint = fingerprint
        self._max_snapshots = max_snapshots
        self._max_age = max_age
        self._persist_path = persist_path
        self._seeded = False
        self._bg_building = False
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._snapshots: OrderedDict[str, Snapshot] = OrderedDict()
        self._current_id: str | None = None
        self._generation = 0
        self.build_count = 0
        self._seed_from_disk()

    # ---------------- 落盘 / 预热 ----------------
    def _seed_from_disk(self) -> None:
        """启动时直接载入上次快照：先让首屏有数据，再后台校验指纹。"""
        if self._seeded:
            return
        self._seeded = True
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = gzip.decompress(self._persist_path.read_bytes()).decode("utf-8")
            data = json.loads(raw)
            if int(data.get("schema") or 0) != SNAPSHOT_SCHEMA_VERSION:
                return
            items = data.get("items") or []
            if not isinstance(items, list) or not items:
                return
            sid = str(data.get("snapshot_id") or "seed")
            fingerprint = str(data.get("fingerprint") or "")
            snap = Snapshot(sid, fingerprint, int(data.get("generation") or 0), items,
                            float(data.get("build_ms") or 0.0))
            with self._lock:
                self._snapshots[sid] = snap
                self._current_id = sid
        except Exception:
            return

    def _persist(self, snapshot: Snapshot) -> None:
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": snapshot.snapshot_id,
                "fingerprint": snapshot.fingerprint,
                "generation": snapshot.generation,
                "build_ms": snapshot.build_ms,
                "items": snapshot.items_full,
            }
            tmp = self._persist_path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"), 6))
            tmp.replace(self._persist_path)
        except Exception:
            pass

    def _refresh_async(self) -> None:
        """后台重建：不阻塞当前请求，single-flight 只跑一份。"""
        with self._lock:
            if self._bg_building:
                return
            self._bg_building = True

        def run() -> None:
            try:
                with self._build_lock:
                    self._build()
            except Exception:
                pass
            finally:
                with self._lock:
                    self._bg_building = False

        threading.Thread(target=run, daemon=True, name="SnapshotRefresh").start()

    # ---------------- 失效与构建 ----------------
    def invalidate(self) -> None:
        """显式失效：generation + 1，下一次请求必然重建（保留旧快照供分页命中）。"""
        with self._lock:
            self._generation += 1

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def _build(self) -> Snapshot:
        started = time.perf_counter()
        items = self._builder()
        build_ms = (time.perf_counter() - started) * 1000.0
        fingerprint = self._fingerprint()
        snapshot_id = hashlib.sha1(f"{fingerprint}:{self.generation}".encode("utf-8")).hexdigest()[:12]
        snapshot = Snapshot(snapshot_id, fingerprint, self.generation, items, build_ms)
        with self._lock:
            self.build_count += 1
            self._snapshots[snapshot_id] = snapshot
            self._snapshots.move_to_end(snapshot_id)
            self._current_id = snapshot_id
            while len(self._snapshots) > self._max_snapshots:
                self._snapshots.popitem(last=False)
        self._persist(snapshot)
        return snapshot

    def get(self, snapshot_id: str | None = None, allow_stale: bool = False) -> tuple[Snapshot, str]:
        """取快照，同时返回缓存状态。

        Args:
            allow_stale: True 时若指纹已变化但仍有旧快照，立即返回旧快照并后台重建
                （`cache_status="stale"`），用于把冷启动 12 s 的构建移出首屏路径。
            `(snapshot, cache_status)`，`cache_status ∈ {"hit", "miss", "stale"}`
        * 传了 `snapshot` 且命中 → 直接复用（分页稳定性优先，不再判指纹）；
        * 否则比对指纹，命中当前快照则复用，否则 single-flight 重建。
        """
        now = time.time()
        with self._lock:
            if snapshot_id:
                cached = self._snapshots.get(snapshot_id)
                if cached is not None and cached.age_seconds(now) <= self._max_age:
                    self._snapshots.move_to_end(snapshot_id)
                    return cached, "hit"
            current = self._snapshots.get(self._current_id or "")

        fingerprint = self._fingerprint()
        if current is not None and current.fingerprint == fingerprint and current.age_seconds(now) <= self._max_age:
            return current, "hit"
        if allow_stale and current is not None:
            self._refresh_async()
            return current, "stale"

        # single-flight：构建期间其他线程阻塞在同一把锁上，不重复构建
        with self._build_lock:
            with self._lock:
                current = self._snapshots.get(self._current_id or "")
            if (
                current is not None
                and current.fingerprint == fingerprint
                and current.age_seconds() <= self._max_age
            ):
                return current, "hit"
            return self._build(), "miss"

    def latest_items(self) -> list[dict[str, Any]]:
        """当前快照的全量条目（供标题映射等只读用途）。"""
        with self._lock:
            current = self._snapshots.get(self._current_id or "")
        if current is None:
            return []
        return current.items_full

    # ---------------- 请求处理 ----------------
    def serve(self, query: dict[str, list[str]]) -> "ServeResult":
        """处理一次 `/api/sessions` 请求，返回 `ServeResult`（body + ETag + 诊断信息）。

        ⚠️ **耗时/时间戳一律不进 body**：body 一旦含 `ms`，`md5(body)` 型的 ETag 就
        每请求都变，`If-None-Match` 永远不可能命中（实测连发 4 次得到 4 个 ETag）。
        因此 ETag 改为由**稳定输入**派生（`compute_list_etag`），耗时走响应头
        `X-Query-Ms` / `X-Build-Ms` / `X-Cache`。
        """
        started = time.perf_counter()
        snapshot, cache_status = self.get(_first(query, "snapshot") or None, allow_stale=True)

        search = (_first(query, "q") or "").strip().lower()
        fmt_filter = (_first(query, "format") or "").strip()
        sort_by = (_first(query, "sort_by") or "mtime").strip()
        sort_order = (_first(query, "order") or "desc").strip().lower()
        is_desc = sort_order != "asc"
        fold = _int_param(query, "fold", 0) == 1
        limit = max(0, _int_param(query, "limit", 0))
        offset = max(0, _int_param(query, "offset", 0))
        fields_param = (_first(query, "fields") or "").strip().lower()
        use_lite = fields_param == "lite"
        if use_lite:
            source_items = snapshot.items_lite
        else:
            source_items = snapshot.items_full

        filtered: list[dict[str, Any]] = []
        for item in source_items:
            if fmt_filter and fmt_filter != "all" and item.get("format") != fmt_filter:
                continue
            if search:
                haystack = (
                    f"{item.get('title', '')} {item.get('session_id', '')} "
                    f"{item.get('format', '')} {item.get('file_path', '')}"
                ).lower()
                if search not in haystack:
                    continue
            if fold and item.get("is_lineage_branch"):
                # 同源分叉折叠：必须与服务端同一快照内完成，否则跨页会重复出现
                continue
            filtered.append(item)

        filtered.sort(key=lambda item: _sort_key(item, sort_by), reverse=is_desc)

        total = len(filtered)
        stats = {
            "bytes": sum(int(item.get("bytes") or 0) for item in filtered),
            "tokens": sum(int(item.get("tokens") or 0) for item in filtered),
            # top-level 数量不随分页加载多少而变；子代理已收进父卡片抽屉。
            "top_level_total": sum(1 for item in filtered if not item.get("is_child")),
            "child_total": sum(1 for item in filtered if item.get("is_child")),
        }
        if limit > 0:
            page = filtered[offset: offset + limit]
        else:
            page = filtered[offset:] if offset else filtered

        has_more = (offset + len(page)) < total
        meta = {
            "total": total,
            # 与顶层 count 同值：团规定的 meta 键集里含 count，这里显式给一份，
            # 免得消费方还要记"count 只在顶层"。**不含任何耗时字段**（否则 304 永不命中）
            "count": len(page),
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "snapshot": snapshot.snapshot_id,
            "generation": snapshot.generation,
            "fold": fold,
            "fields": "lite" if use_lite else "full",
        }
        response: dict[str, Any] = {
            "sessions": page,
            # 统计只针对**全部过滤结果**，不能由前端按已加载页累加（分页时会低报）
            "stats": stats,
            # count 语义保持旧约定：**本次返回条数**（不是总数），旧前端读它不会坏
            "count": len(page),
            "total": total,
            "offset": offset,
            "limit": limit,
            "snapshot": snapshot.snapshot_id,
            "has_more": has_more,
            "meta": meta,
        }
        etag = compute_list_etag(
            snapshot_id=snapshot.snapshot_id,
            generation=snapshot.generation,
            fingerprint=snapshot.fingerprint,
            limit=limit,
            offset=offset,
            fields=fields_param,
            fold=fold,
            sort_by=sort_by,
            order=sort_order,
            q=search,
            fmt=fmt_filter,
        )
        return ServeResult(
            payload=response,
            etag=etag,
            cache_status=cache_status,
            query_ms=round((time.perf_counter() - started) * 1000.0, 2),
            build_ms=round(snapshot.build_ms, 2),
        )


class ServeResult:
    """一次列表请求的产物：响应体 + 稳定 ETag + 诊断信息（耗时只进响应头）。"""

    __slots__ = ("payload", "etag", "cache_status", "query_ms", "build_ms")

    def __init__(
        self,
        payload: dict[str, Any],
        etag: str,
        cache_status: str,
        query_ms: float,
        build_ms: float,
    ) -> None:
        self.payload = payload
        self.etag = etag
        self.cache_status = cache_status
        self.query_ms = query_ms
        self.build_ms = build_ms


def compute_list_etag(
    *,
    snapshot_id: str,
    generation: int,
    fingerprint: str,
    limit: int,
    offset: int,
    fields: str,
    fold: bool,
    sort_by: str,
    order: str,
    q: str,
    fmt: str,
) -> str:
    """列表响应的**稳定** ETag。

    只由「决定这份 body 内容的输入」构成：快照身份（含指纹与 generation）+ 全部
    查询参数。**不含任何耗时/时间戳**，否则 304 永远不可能命中。

    分片参数同样必须进哈希：否则 `offset=0` 的 ETag 会被 `offset=60` 命中，
    304 让前端把第 1 页当成第 2 页（与详情接口 `compute_etag` 是同一个坑）。
    """
    raw = "|".join(
        [
            snapshot_id,
            f"gen{int(generation)}",
            fingerprint,
            f"limit={int(limit)}",
            f"offset={int(offset)}",
            f"fields={fields or 'full'}",
            f"fold={1 if fold else 0}",
            f"sort={sort_by}",
            f"order={order}",
            f"q={q}",
            f"format={fmt}",
        ]
    )
    return '"' + hashlib.sha1(raw.encode("utf-8")).hexdigest() + '"'


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name)
    if not values:
        return ""
    return str(values[0] or "")


def _int_param(query: dict[str, list[str]], name: str, default: int) -> int:
    """非法值一律回落到默认值（旧行为 = 全量），绝不 500。"""
    raw = _first(query, name)
    if raw == "":
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _sort_key(item: dict[str, Any], sort_by: str) -> Any:
    """排序键；同时间戳追加记录数作为稳定次序，避免共享 mtime 时随机排列。"""
    try:
        if sort_by == "mtime":
            return (float(item.get("mtime") or 0), int(item.get("records") or 0))
        if sort_by == "started_at":
            return (str(item.get("started_at") or ""), int(item.get("records") or 0))
        if sort_by == "bytes":
            return int(item.get("bytes") or 0)
        if sort_by == "tokens":
            return int(item.get("tokens") or 0)
        if sort_by == "records":
            return int(item.get("records") or 0)
        if sort_by == "title":
            return str(item.get("title") or "").lower()
        if sort_by == "format":
            return str(item.get("format") or "").lower()
    except (TypeError, ValueError):
        return 0
    return float(item.get("mtime") or 0)
