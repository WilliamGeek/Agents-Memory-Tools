"""豆包云端同步仓（cache/doubao_cloud）读取层。

`tools/doubao_sync.py` 负责把云端会话拉成规范化 JSON；本模块只做带签名的
只读加载，供 web_app 的列表 / 详情 / FTS 复用。签名按目录内文件
(mtime, size) 计算，同步写入后自动热更新，无需重启服务。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
import runtime_paths

CACHE_DIR = runtime_paths.CACHE_DIR / "doubao_cloud"
CONV_DIR = CACHE_DIR / "conversations"
MANIFEST = CACHE_DIR / "manifest.json"
COOKIE_CACHE = CACHE_DIR / ".cookies.json"

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"sig": (), "data": {}}


def signature() -> tuple[int, int, int]:
    """返回 (文件数, 最新 mtime_ns, 总大小)，用于缓存失效判断。"""
    if not CONV_DIR.exists():
        return (0, 0, 0)
    count = 0
    newest = 0
    total = 0
    for p in CONV_DIR.glob("*.json"):
        try:
            st = p.stat()
        except OSError:
            continue
        count += 1
        newest = max(newest, st.st_mtime_ns)
        total += st.st_size
    return (count, newest, total)


def load() -> dict[str, dict[str, Any]]:
    """返回 {conversation_id: {cid,title,ts,messages,dir,...}}。"""
    sig = signature()
    with _LOCK:
        if _CACHE["sig"] == sig:
            return _CACHE["data"]
        data: dict[str, dict[str, Any]] = {}
        for p in CONV_DIR.glob("*.json"):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            cid = str(obj.get("cid") or p.stem)
            obj["cid"] = cid
            obj["dir"] = str(p)
            obj["file"] = str(p)
            data[cid] = obj
        _CACHE["sig"] = sig
        _CACHE["data"] = data
        return data


def get(cid: str) -> dict[str, Any]:
    return load().get(str(cid)) or {}


def manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def last_sync_ts() -> int:
    return int(manifest().get("synced_at") or 0)


def entry(cid: str) -> dict[str, Any]:
    """返回单个云端会话的 manifest 条目；没有则空 dict。"""
    conv = (manifest().get("conversations") or {}).get(str(cid)) or {}
    return conv if isinstance(conv, dict) else {}


def is_stale(cid: str, max_age_seconds: int = 120) -> bool:
    """manifest 里的单会话检查时间是否超过阈值。

    优先用 checked_at（一次 --only 即使 skipped 也会更新时间），
    再退回 synced_at；两者都没有视为过期。
    """
    e = entry(cid)
    if not e:
        return True
    try:
        checked_at = int(e.get("checked_at") or e.get("synced_at") or 0)
    except (TypeError, ValueError):
        return True
    return (time.time() - checked_at) > max_age_seconds


def has_cookie_cache() -> bool:
    return COOKIE_CACHE.exists()
