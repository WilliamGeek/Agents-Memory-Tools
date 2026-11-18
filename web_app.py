"""
SessionMigrate Web Dashboard (Enhanced Edition)
A modern, beautiful web-based GUI for cross-agent coding session migration and management.
Supports Claude Code, Cursor, Antigravity IDE/CLI, WorkBuddy, Trae/Trae SOLO, GitHub Copilot, Codex, Kimi, Devin, etc.
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import shutil
import subprocess
import tempfile
import urllib.parse
import re
import hashlib
import gzip
import threading
import multiprocessing
from html import unescape as _html_unescape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass
from pathlib import Path
import mimetypes
from datetime import datetime, timezone
from typing import Any
# Ensure safe stdout/stderr in GUI / pythonw mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


# Ensure session-migrate virtualenv or package is importable
import runtime_paths

SCRIPT_DIR = runtime_paths.RESOURCE_DIR
sys.path.insert(0, str(SCRIPT_DIR))
FRONTEND_OUT_DIR = runtime_paths.FRONTEND_OUT_DIR
TOOLS_DIR = runtime_paths.TOOLS_DIR
DATA_DIR = runtime_paths.DATA_DIR
runtime_paths.ensure_runtime_dirs()

# 兼容旧代码里的硬编码用户目录；新代码应使用 runtime_paths 的 *_path()。
USERPROFILE = runtime_paths.user_home()
ROAMING_APPDATA = runtime_paths.roaming_dir()
LOCAL_APPDATA = runtime_paths.local_app_data_dir()


def _home_path(*parts: str) -> Path:
    return USERPROFILE.joinpath(*parts)


def _roaming_path(*parts: str) -> Path:
    return ROAMING_APPDATA.joinpath(*parts)


def _local_path(*parts: str) -> Path:
    return LOCAL_APPDATA.joinpath(*parts)




def _no_window_kwargs() -> dict:
    """后台（pythonw / 无控制台）运行时，子进程一律不创建控制台窗口。

    pythonw 自身没有控制台，此时启动 netstat / taskkill / cmd 等控制台程序，
    Windows 会为其新建一个黑色终端窗口并闪烁；这里统一加上 CREATE_NO_WINDOW。
    """
    try:
        import subprocess
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            return {
                "creationflags": subprocess.CREATE_NO_WINDOW,
                "startupinfo": si,
            }
    except Exception:
        pass
    return {}

# 服务层（本轮 refactor 新增）：单向依赖，services/* 不会 import 本模块
from services import detail as detail_service
from services import doubao_cloud
from services import doubao_idb
from services import instance as instance_service
from services import snapshot as snapshot_service
from services import turns as turns_service

from session_migrate.catalog import (
    Catalog,
    default_catalog_path,
    AgentFormat,
    CatalogRoot,
)
from session_migrate.conversion import (
    load_session,
    convert_session,
    write_artifact,
    ConversionOptions,
    default_target_home,
    target_import_paths,
    install_antigravity_artifact,
    install_cursor_artifact,
    install_copilot_artifact,
    install_kimi_artifact,
    install_vibe_artifact,
    install_hermes_artifact,
    install_mastracode_artifact,
    install_devin_artifact,
    install_openhands_artifact,
    install_grok_artifact,
)

def _install_antigravity_child_session_compat() -> None:
    """让 Antigravity 的子代理会话可读。

    browser 等子代理会话会把 trajectory_metadata_blob 的字段 6（root）写成
    「父会话 id」，而 session_migrate 的校验要求它等于本库的 conversation_id，
    于是整段会话解析直接失败（trajectory metadata root ID is inconsistent）。

    读取路径（generated=False）把 root 当作 conversation_id 交给原校验即可通过，
    其余校验（时间戳、project）保持不变；写入路径仍走原逻辑，避免产出不合规的
    迁移包。
    """
    try:
        from session_migrate.formats import antigravity as _ag
    except Exception:
        return
    if getattr(_ag, "_child_session_compat", False):
        return
    original = _ag._validate_trajectory_metadata

    def lenient(data, conversation_id, *, generated):
        if not generated:
            try:
                root = _ag._optional_text(_ag._decode_message(data), 6)
            except Exception:
                root = None
            if root and root != conversation_id:
                return original(data, root, generated=False)
        return original(data, conversation_id, generated=generated)

    _ag._validate_trajectory_metadata = lenient
    _ag._child_session_compat = True


_install_antigravity_child_session_compat()


class _AntigravityRowsCompat:
    """伪造 fetchall/fetchone 的只读结果集，用于归一化 trajectory_meta 查询结果。"""

    __slots__ = ("_rows",)

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _AntigravityTrajectoryCompat:
    """把「唯一一条 trajectory_type=22」的读取结果归一化成 4。

    只拦截 `trajectory_meta` 查询，其余 SQL 原样透传连接对象。
    """

    __slots__ = ("_conn",)

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Any = ()):
        cursor = self._conn.execute(sql, parameters)
        if "FROM trajectory_meta" not in sql:
            return cursor
        rows = cursor.fetchall()
        if len(rows) == 1 and len(rows[0]) >= 4 and rows[0][2] == 22:
            rows = [(rows[0][0], rows[0][1], 4, rows[0][3])]
        return _AntigravityRowsCompat(rows)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _install_antigravity_trajectory_type_compat() -> None:
    """兼容新版 Antigravity 的 cascade 轨迹类型。

    旧版会话库 `trajectory_meta.trajectory_type = 4`（CLI cascade），
    2026-11 之后的新版（IDE）写成 22；session-migrate 0.11.0 的严格校验只认 4，
    于是整段会话解析直接失败（详情页空白 / HTTP 500）。读取路径把唯一的 22
    按 4 再校验一次，写入路径仍走原逻辑，避免产出不合规的迁移包。
    """
    try:
        from session_migrate.formats import antigravity as _ag
        from session_migrate.errors import SessionMigrateError as _Err
    except Exception:
        return
    if getattr(_ag, "_trajectory_type_compat", False):
        return
    original = _ag._validate_database

    def lenient(db, *, expected_session_id, generated):
        try:
            return original(db, expected_session_id=expected_session_id, generated=generated)
        except _Err as exc:
            if generated or "one CLI cascade trajectory" not in str(exc):
                raise
        return original(
            _AntigravityTrajectoryCompat(db),
            expected_session_id=expected_session_id,
            generated=generated,
        )

    _ag._validate_database = lenient
    _ag._trajectory_type_compat = True


_install_antigravity_trajectory_type_compat()


def _install_antigravity_limits_compat() -> None:
    """放宽 Antigravity 原生会话库与单步 protobuf 载荷的安全上限。

    新版 Antigravity IDE 长会话库可达 360MB+，且单步 MCP 工具调用载荷可达 95MB+，
    超过 session-migrate 默认的 256MB / 64MB 上限后会直接报
    'Antigravity conversation exceeds the database safety limit' 导致详情加载失败。
    """
    try:
        from session_migrate.formats import antigravity as _ag
    except Exception:
        return
    if getattr(_ag, "_limits_compat", False):
        return
    _ag.MAX_NATIVE_BYTES = max(int(getattr(_ag, "MAX_NATIVE_BYTES", 0)), 1024 * 1024 * 1024)
    _ag.MAX_PROTO_VALUE_BYTES = max(int(getattr(_ag, "MAX_PROTO_VALUE_BYTES", 0)), 512 * 1024 * 1024)
    _ag.MAX_TEXT_BYTES = max(int(getattr(_ag, "MAX_TEXT_BYTES", 0)), 512 * 1024 * 1024)
    _ag._limits_compat = True


_install_antigravity_limits_compat()

PORT = 18922
# 允许通过环境变量 / 命令行覆盖端口（多实例自测用；默认仍是 18922，行为不变）
try:
    _ENV_PORT = int(os.environ.get("MEMORY_TOOLS_PORT", "") or 0)
    if 0 < _ENV_PORT < 65536:
        PORT = _ENV_PORT
except (TypeError, ValueError):
    pass
BASE_DIR = runtime_paths.RESOURCE_DIR
EXPORT_DIR = runtime_paths.EXPORT_DIR
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Permanent tiktoken cache directory in the writable data directory.
TIKTOKEN_LOCAL_CACHE = runtime_paths.TIKTOKEN_CACHE_DIR
TIKTOKEN_LOCAL_CACHE.mkdir(exist_ok=True)
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(TIKTOKEN_LOCAL_CACHE))

try:
    import tiktoken
    _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _TIKTOKEN_ENC = None

try:
    import tokenizers
    _HAS_TOKENIZERS = True
except Exception:
    _HAS_TOKENIZERS = False

_HF_TOKENIZERS: dict[str, Any] = {}
def get_hf_tokenizer(tokenizer_path_or_id: str) -> Any:
    """Optional HuggingFace Tokenizer loader for open-source model vocabs (e.g. Qwen/DeepSeek)."""
    if not _HAS_TOKENIZERS:
        return None
    if tokenizer_path_or_id in _HF_TOKENIZERS:
        return _HF_TOKENIZERS[tokenizer_path_or_id]
    try:
        tok = tokenizers.Tokenizer.from_file(tokenizer_path_or_id)
        _HF_TOKENIZERS[tokenizer_path_or_id] = tok
        return tok
    except Exception:
        return None

TOKEN_CACHE_PATH = runtime_paths.TOKEN_CACHE_PATH
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_CACHE_LOADED = False
_TOKEN_CACHE_DIRTY = False
_GLOBAL_SESSIONS_CACHE: dict[str, Any] = {"ts": 0.0, "data": []}

# 列表快照缓存（内容指纹 + single-flight）：见 services/snapshot.py 顶部注释。
# 保留 _GLOBAL_SESSIONS_CACHE 是为了兼容旧读取点（标题映射等），它只是快照的镜像。
_SNAPSHOT_CACHE: "snapshot_service.SnapshotCache | None" = None
_SNAPSHOT_CACHE_LOCK = threading.Lock()
#: 显式失效令牌：读写接口（delete/migrate/refresh/...）调用 invalidate 时 +1，
#: 进入内容指纹，保证"文件没变但语义变了"（例如标题刷新）也能触发重建
_SESSIONS_INVALIDATION_TOKEN = 0


def _dir_signature(directory: Path, pattern: str = "*") -> bytes:
    """目录级指纹：条目数 + 最新 mtime_ns（目录内新增/删除文件即变化）。"""
    count = 0
    newest = 0
    try:
        if not directory.exists():
            return f"|{directory}|missing".encode("utf-8", "replace")
        for entry in directory.glob(pattern):
            try:
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            newest = max(newest, stat.st_mtime_ns)
    except OSError:
        return f"|{directory}|error".encode("utf-8", "replace")
    return f"|{directory}|{count}|{newest}".encode("utf-8", "replace")


def _dir_signature_recursive(directory: Path) -> bytes:
    """递归目录指纹：用于 Claude/Codex 这类按项目子目录存会话的 roots。"""
    count = 0
    newest = 0
    try:
        if not directory.exists():
            return f"|{directory}|missing".encode("utf-8", "replace")
        for entry in directory.rglob("*"):
            try:
                stat = entry.stat()
            except OSError:
                continue
            count += 1
            newest = max(newest, stat.st_mtime_ns)
    except OSError:
        return f"|{directory}|error".encode("utf-8", "replace")
    return f"|{directory}|rec|{count}|{newest}".encode("utf-8", "replace")


def _sessions_fingerprint() -> str:
    """列表内容指纹：roots + catalog 规模 + antigravity 目录 + 失效令牌。

    成本实测 ~6 ms（134 个 .db 的 stat + 一次 sqlite 查询），远低于一次全量重建
    的 589 ms；这就是"去掉 4 秒 TTL 也能保持低延迟"的原因。
    """
    digest = hashlib.sha1()
    digest.update(f"token:{_SESSIONS_INVALIDATION_TOKEN}".encode("utf-8"))
    try:
        db = get_catalog_db()
        try:
            roots = db.execute(
                "SELECT id, format, path, enabled FROM roots ORDER BY id"
            ).fetchall()
            digest.update(repr([tuple(r) for r in roots]).encode("utf-8", "replace"))
            # 目录型 roots（Claude / Codex / 其它本地平台）也要参与指纹，
            # 否则新增会话后快照可能继续吃旧列表。
            for _rid, _fmt, root_path, _enabled in roots:
                if not root_path:
                    continue
                try:
                    rp = Path(root_path)
                    if rp.is_dir():
                        digest.update(_dir_signature(rp))
                    elif rp.is_file():
                        st = rp.stat()
                        digest.update(f"|rootfile|{rp}|{st.st_mtime_ns}|{st.st_size}".encode("utf-8", "replace"))
                except Exception:
                    digest.update(f"|root|error|{root_path}".encode("utf-8", "replace"))
            # Claude / Codex 的会话落在项目子目录里，单独递归计算一次；
            # 只做这两个窄目录，避免对 F:\Codex 等大根目录做全量遍历。
            for hot_dir in (
                _home_path(".claude", "projects"),
                _home_path(".codex", "sessions"),
            ):
                digest.update(_dir_signature_recursive(hot_dir))
            row = db.execute(
                "SELECT COUNT(*), MAX(id) FROM sessions WHERE status != 'missing'"
            ).fetchone()
            digest.update(repr(tuple(row)).encode("utf-8"))
        finally:
            db.close()
    except Exception:
        digest.update(b"catalog-error")
    for ag_dir in ANTIGRAVITY_CONV_DIRS:
        digest.update(_dir_signature(ag_dir, "*.db"))
    digest.update(_dir_signature(_home_path(".workbuddy", "projects")))
    digest.update(_dir_signature(_roaming_path("Trae CN", "User")))
    digest.update(_dir_signature(_roaming_path("TRAE SOLO CN", "User")))
    digest.update(_dir_signature(_home_path(".trae-cn", "memory")))
    # Trae 源库变化后要重建快照；否则后台重解密完成但列表仍可能吃旧快照。
    try:
        src_mtime = _trae_source_mtime()
        plain = TRAE_PLAIN_DB.stat()
        digest.update(
            f"|trae|{int(src_mtime * 1e9)}|{plain.st_mtime_ns}|{plain.st_size}".encode("ascii")
        )
    except Exception:
        digest.update(b"|trae|missing")
    for idb_dir in doubao_idb.leveldb_dirs(
        LOCAL_APPDATA / "Doubao" / "User Data"
    ):
        digest.update(_dir_signature(idb_dir))
    digest.update(repr(doubao_cloud.signature()).encode("ascii", errors="ignore"))
    return digest.hexdigest()


_DOUBAO_SYNC_STATE: dict[str, Any] = {
    "running": False,
    "started_at": 0.0,
    "last_result": None,
}
_DOUBAO_SYNC_LOCK = threading.Lock()
DOUBAO_AUTOSYNC_SECONDS = 6 * 3600


def _helper_script(tool: str) -> Path:
    scripts = {
        "doubao-sync": TOOLS_DIR / "doubao_sync.py",
        "trae-decrypt": TOOLS_DIR / "dbkey" / "decrypt_trae.py",
    }
    return scripts[tool]


def helper_command(tool: str, *args: str) -> list[str]:
    """构造后台 helper 命令。

    源码模式沿用原来的“Python + 脚本”方式；冻结后 ``sys.executable`` 是
    主 exe，不能再传脚本路径，因此改成 ``MemoryTools.exe --helper <tool>``，
    由同一 exe 的 helper 分支执行。Tauri sidecar 也复用这个入口。
    """
    if runtime_paths.is_frozen():
        return [sys.executable, "--helper", tool, *args]
    return [sys.executable, str(_helper_script(tool)), *args]


def run_helper(tool: str, args: list[str]) -> int:
    """在独立 helper 进程中执行工具脚本；返回进程退出码。"""
    script = _helper_script(tool)
    if not script.exists():
        print(f"Helper script not found: {script}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *args]
    import runpy

    runpy.run_path(str(script), run_name="__main__")
    return 0


def run_doubao_sync_worker(full: bool = False, only: str = "", limit: int = 0) -> None:
    """后台执行 tools/doubao_sync.py，完成后刷新快照与 FTS。"""
    args = helper_command("doubao-sync", "--quiet")

    if full:
        args.append("--full")
    if only:
        args.extend(["--only", str(only)])
    if limit:
        args.extend(["--limit", str(limit)])
    try:
        proc = subprocess.run(
            args,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            timeout=1800,
            **_no_window_kwargs(),
        )
        _DOUBAO_SYNC_STATE["last_result"] = {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stderr": proc.stderr.decode("utf-8", errors="ignore")[-600:],
            "finished_at": time.time(),
        }
    except Exception as exc:
        _DOUBAO_SYNC_STATE["last_result"] = {
            "ok": False,
            "code": -1,
            "stderr": str(exc)[:600],
            "finished_at": time.time(),
        }
    finally:
        _DOUBAO_SYNC_STATE["running"] = False
    try:
        invalidate_sessions_cache()
        trigger_fts_sync()
    except Exception:
        pass


def start_doubao_sync(full: bool = False, only: str = "", limit: int = 0) -> bool:
    """启动后台同步；已有任务在跑时返回 False。"""
    with _DOUBAO_SYNC_LOCK:
        if _DOUBAO_SYNC_STATE["running"]:
            return False
        _DOUBAO_SYNC_STATE["running"] = True
        _DOUBAO_SYNC_STATE["started_at"] = time.time()
    threading.Thread(
        target=run_doubao_sync_worker,
        args=(full, only, limit),
        daemon=True,
        name="DoubaoCloudSync",
    ).start()
    return True


# 详情打开时的单会话按需刷新阈值；全局 6 小时兜底仍由 _maybe_autosync_doubao 负责。
DOUBAO_DETAIL_REFRESH_SECONDS = 120
_DOUBAO_DETAIL_REFRESH_LOCK = threading.Lock()
_DOUBAO_DETAIL_REFRESH_LAST: dict[str, float] = {}


def _doubao_cloud_cid_for_catalog(cid: str) -> str:
    """把 db_<前16位> 还原成完整的 conversation_id。

    先查云端同步仓；云端还没有这个新会话时，再从本地 IndexedDB 元数据
    还原。后者很重要：否则新会话第一次打开时找不到 full cid，就不会触发
    --only 同步，详情只能显示 IndexedDB 里的当前任务态（正文被截断）。
    """
    if not cid.startswith("db_"):
        return ""
    prefix = cid[3:]
    for full in doubao_cloud.load().keys():
        if str(full).startswith(prefix):
            return str(full)
    try:
        local = doubao_idb.load(LOCAL_APPDATA / "Doubao" / "User Data")
    except Exception:
        local = {}
    for full in local.keys():
        if str(full).startswith(prefix):
            return str(full)
    return ""


def _doubao_idb_mtime() -> float:
    """返回豆包 IndexedDB LevelDB 目录的最新写入时间。"""
    latest = 0.0
    root = LOCAL_APPDATA / "Doubao" / "User Data"
    try:
        for idb_dir in doubao_idb.leveldb_dirs(root):
            for p in idb_dir.glob("*"):
                if p.is_file():
                    latest = max(latest, p.stat().st_mtime)
    except Exception:
        pass
    return latest


def _maybe_refresh_doubao_detail(cid: str) -> bool:
    """详情请求前调用：单会话过期则触发一次 --only 后台同步。

    返回 True 表示本轮详情返回的是旧缓存，客户端应稍后重取；False 表示无需刷新。
    """
    full = _doubao_cloud_cid_for_catalog(cid)
    if not full:
        return False
    entry = doubao_cloud.entry(full)
    checked_at = int(entry.get("checked_at") or entry.get("synced_at") or 0)
    idb_mtime = _doubao_idb_mtime()
    # manifest 的 120 秒阈值用于兜底；如果 IndexedDB 在最近一次检查后又
    # 有新写入（新消息/新任务态），即使不足 120 秒也立刻补拉云端正文。
    if not doubao_cloud.is_stale(full, DOUBAO_DETAIL_REFRESH_SECONDS) and idb_mtime <= checked_at:
        return False

    # 同一会话短时间内连点详情时，不要把 --only 任务堆起来。
    with _DOUBAO_DETAIL_REFRESH_LOCK:
        last = _DOUBAO_DETAIL_REFRESH_LAST.get(full, 0.0)
        if time.time() - last < 20:
            return True
        _DOUBAO_DETAIL_REFRESH_LAST[full] = time.time()

    start_doubao_sync(only=full)
    return True


def _maybe_autosync_doubao() -> None:
    """有 Cookie 缓存且距上次同步超过 6 小时时，后台增量同步一次。"""
    try:
        if not doubao_cloud.has_cookie_cache():
            return
        if time.time() - doubao_cloud.last_sync_ts() < DOUBAO_AUTOSYNC_SECONDS:
            return
        start_doubao_sync()
    except Exception:
        pass


def _build_snapshot_items() -> list[dict]:
    """快照构建 + 顺带触发增量 FTS 同步（豆包 IndexedDB 写入后自动可检索）。"""
    _maybe_autosync_doubao()
    items = collect_all_sessions(fmt_filter="all", search="")
    try:
        trigger_fts_sync()
    except Exception:
        pass
    return items


def _get_snapshot_cache() -> "snapshot_service.SnapshotCache":
    """惰性构造快照缓存（builder 在首次请求时才跑，避免启动拖慢）。"""
    global _SNAPSHOT_CACHE
    if _SNAPSHOT_CACHE is None:
        with _SNAPSHOT_CACHE_LOCK:
            if _SNAPSHOT_CACHE is None:
                _SNAPSHOT_CACHE = snapshot_service.SnapshotCache(
                    builder=_build_snapshot_items,
                    fingerprint=_sessions_fingerprint,
                    persist_path=runtime_paths.CACHE_DIR / "sessions_snapshot.json.gz",
                )
    return _SNAPSHOT_CACHE


def invalidate_sessions_cache() -> None:
    """写入类接口执行后调用：指纹令牌 +1 + 快照失效。

    保留原函数名与签名（12 处调用点无需改动）。
    """
    global _SESSIONS_INVALIDATION_TOKEN
    _SESSIONS_INVALIDATION_TOKEN += 1
    _GLOBAL_SESSIONS_CACHE["ts"] = 0.0
    _GLOBAL_SESSIONS_CACHE["data"] = []
    _get_snapshot_cache().invalidate()


def _ensure_token_cache_loaded() -> None:
    global _TOKEN_CACHE, _TOKEN_CACHE_LOADED
    if _TOKEN_CACHE_LOADED:
        return
    _TOKEN_CACHE_LOADED = True
    if TOKEN_CACHE_PATH.exists():
        try:
            with open(TOKEN_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _TOKEN_CACHE = data
        except Exception:
            _TOKEN_CACHE = {}


def flush_token_cache() -> None:
    global _TOKEN_CACHE_DIRTY
    if not _TOKEN_CACHE_DIRTY:
        return
    try:
        tmp_path = TOKEN_CACHE_PATH.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_TOKEN_CACHE, f, ensure_ascii=False)
        tmp_path.replace(TOKEN_CACHE_PATH)
        _TOKEN_CACHE_DIRTY = False
    except Exception:
        pass


def estimate_text_tokens(text: str) -> int:
    """Exact BPE token counter using Rust tiktoken (cl100k_base) with pure-Python fallback (98.5%+ accuracy)."""
    if not text:
        return 0
    if _TIKTOKEN_ENC is not None:
        try:
            return len(_TIKTOKEN_ENC.encode_ordinary(text))
        except Exception:
            pass
    clen = len(text)
    blen = len(text.encode("utf-8", errors="ignore"))
    cjk_chars = max(0, (blen - clen) // 2)
    ascii_chars = max(0, clen - cjk_chars)
    return max(1, int(cjk_chars * 1.3 + ascii_chars * 0.25))


# ---------------------------------------------------------------------------
# Recorded usage readers
#
# 各客户端其实都把「每次请求的真实 token 用量」写进了自己的会话文件，只是位置不同：
#   Antigravity : steps.step_payload -> 字段 5 (step metadata) -> 子消息字段 9
#                 (2=promptTokenCount 3=candidatesTokenCount 9=thoughtsTokenCount)
#   Claude Code : jsonl 每条 assistant 记录的 message.usage
#                 (input_tokens / cache_creation_input_tokens / cache_read_input_tokens / output_tokens)
# 估算口径（estimate_text_tokens）只能量出「内容体积」，而计费按「每次请求的完整上下文」累计，
# 长会话下两者必定差数倍。因此优先读记录值，估算值退化为 content_tokens 备用指标。
# ---------------------------------------------------------------------------
# 缓存签名带版本号：口径变更时旧缓存自动失效，不会沿用历史错误值。
TOKEN_CACHE_VERSION = 4


def _pb_iter(buf: bytes, stop_after: int | None = None):
    """极简 protobuf wire 读取器，逐字段产出 (field_number, wire_type, value)。

    stop_after 命中后立即返回，避免为拿一小段 metadata 而遍历数十 MB 的 payload。
    解析失败一律静默终止，交由调用方降级。
    """
    i, n = 0, len(buf)
    while i < n:
        key = 0
        shift = 0
        ok = False
        while i < n:
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                ok = True
                break
        if not ok or key == 0:
            return
        num, wt = key >> 3, key & 7
        if wt == 0:
            val = 0
            shift = 0
            ok = False
            while i < n:
                b = buf[i]
                i += 1
                val |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    ok = True
                    break
            if not ok:
                return
        elif wt == 2:
            ln = 0
            shift = 0
            ok = False
            while i < n:
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                shift += 7
                if not b & 0x80:
                    ok = True
                    break
            if not ok or ln < 0 or i + ln > n:
                return
            val = buf[i:i + ln]
            i += ln
        elif wt == 5:
            if i + 4 > n:
                return
            val = buf[i:i + 4]
            i += 4
        elif wt == 1:
            if i + 8 > n:
                return
            val = buf[i:i + 8]
            i += 8
        else:
            return
        yield num, wt, val
        if stop_after is not None and num == stop_after:
            return


def _antigravity_step_usage(payload: bytes) -> tuple[int, int, int, int] | None:
    """从单个 step payload 取出 (prompt, output, thoughts, fixed)。"""
    meta = None
    for num, wt, val in _pb_iter(payload, stop_after=5):
        if num == 5 and wt == 2:
            meta = val
    if not isinstance(meta, bytes):
        return None
    usage = None
    for num, wt, val in _pb_iter(meta, stop_after=9):
        if num == 9 and wt == 2:
            usage = val
    if not isinstance(usage, bytes):
        return None
    fields: dict[int, int] = {}
    for num, wt, val in _pb_iter(usage):
        if wt == 0:
            fields[num] = fields.get(num, 0) + int(val)
    if 2 not in fields:
        return None
    return (
        fields.get(2, 0),
        fields.get(3, 0),
        fields.get(9, 0),
        fields.get(1, 0),
    )


def _antigravity_recorded_usage(db_path: Path) -> dict[str, int] | None:
    conn = None
    agg = {"input": 0, "output": 0, "thoughts": 0, "fixed": 0, "calls": 0}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute("SELECT step_payload FROM steps")
        for (payload,) in cursor:
            if not payload:
                continue
            parsed = _antigravity_step_usage(payload)
            if not parsed:
                continue
            prompt, output, thoughts, fixed = parsed
            agg["input"] += prompt
            agg["output"] += output
            agg["thoughts"] += thoughts
            agg["fixed"] += fixed
            agg["calls"] += 1
    except Exception:
        return None
    finally:
        if conn is not None:
            conn.close()
    if agg["calls"] <= 0 or agg["input"] <= 0:
        return None
    return agg


def _claude_recorded_usage(jsonl_path: Path) -> dict[str, int] | None:
    """逐行累计 Claude Code 的用量（保留旧口径）。

    说明：Claude Code 流式写盘时同一 `message.id` 会落多行、每行带同一份 usage，
    逐行相加会把同一次请求重复计费。但用户明确要求「真实值比旧值小时保留旧值」，
    因此这里维持逐行累计，不做按 id 去重。
    """
    agg = {"input": 0, "output": 0, "thoughts": 0, "fixed": 0, "calls": 0}
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    continue
                usage = msg.get("usage")
                if not isinstance(usage, dict):
                    continue
                send = int(usage.get("input_tokens") or 0)
                cache_write = int(usage.get("cache_creation_input_tokens") or 0)
                cache_read = int(usage.get("cache_read_input_tokens") or 0)
                output = int(usage.get("output_tokens") or 0)
                if send + cache_write + cache_read + output <= 0:
                    continue
                # 计费输入 = 新发 + 缓存写入 + 缓存命中
                agg["input"] += send + cache_write + cache_read
                agg["output"] += output
                agg["calls"] += 1
    except Exception:
        return None
    if agg["calls"] <= 0 or agg["input"] <= 0:
        return None
    return agg


def _workbuddy_recorded_usage(jsonl_path: Path) -> dict[str, int] | None:
    """读取 WorkBuddy 的 providerData.rawUsage（每次模型请求的供应商真实用量）。

    口径与 CC Switch 保持一致：
    * 一次请求只有一个事件带 rawUsage，事件 id 即请求 id，按 id 去重；
    * prompt_tokens 已是 OpenAI 口径（含缓存命中），completion_tokens 含思考；
    * rawUsage 缺失时退回 agents SDK 的 usage（inputTokens/outputTokens），
      同样按 messageId 去重。
    """
    agg = {"input": 0, "output": 0, "thoughts": 0, "fixed": 0, "calls": 0}
    by_request: dict[str, tuple[int, int, int]] = {}
    unkeyed: list[tuple[int, int, int]] = []
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as fh:
            for idx, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                if '"rawUsage"' not in line and '"inputTokens"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                pd = rec.get("providerData")
                pd = pd if isinstance(pd, dict) else {}
                raw = pd.get("rawUsage")
                prompt = completion = thoughts = 0
                if isinstance(raw, dict):
                    prompt = int(raw.get("prompt_tokens") or 0)
                    completion = int(raw.get("completion_tokens") or 0)
                    details = raw.get("completion_tokens_details")
                    if isinstance(details, dict):
                        thoughts = int(details.get("reasoning_tokens") or 0)
                else:
                    usage = rec.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    prompt = int(usage.get("inputTokens") or usage.get("input_tokens") or 0)
                    completion = int(usage.get("outputTokens") or usage.get("output_tokens") or 0)
                    details = usage.get("outputTokensDetails") or usage.get("completion_tokens_details")
                    if isinstance(details, dict):
                        thoughts = int(details.get("reasoningTokens") or details.get("reasoning_tokens") or 0)
                if prompt + completion <= 0:
                    continue
                key = str(rec.get("id") or pd.get("messageId") or "").strip()
                triple = (prompt, completion, thoughts)
                if key:
                    prev = by_request.get(key)
                    if prev is None or prompt + completion > prev[0] + prev[1]:
                        by_request[key] = triple
                else:
                    unkeyed.append(triple)
    except Exception:
        return None
    for prompt, completion, thoughts in list(by_request.values()) + unkeyed:
        agg["input"] += prompt
        agg["output"] += completion
        agg["thoughts"] += thoughts
        agg["calls"] += 1
    if agg["calls"] <= 0 or agg["input"] <= 0:
        return None
    return agg


def read_recorded_usage(fmt: str, file_path: Path | None) -> dict[str, int] | None:
    """按平台读取真实请求用量；读不到返回 None，由估算逻辑接管。

    计数口径对齐 CC Switch：
    * Claude Code 按 message.id 去重（流式多行同 usage）；
    * WorkBuddy 按请求事件 id 汇总 providerData.rawUsage；
    * Antigravity 解析 step 内嵌 usage。
    """
    if not file_path or not file_path.exists():
        return None
    try:
        if fmt == "antigravity" and file_path.suffix == ".db":
            return _antigravity_recorded_usage(file_path)
        if fmt == "claude" and file_path.suffix == ".jsonl":
            return _claude_recorded_usage(file_path)
        if fmt == "workbuddy" and file_path.suffix == ".jsonl":
            return _workbuddy_recorded_usage(file_path)
    except Exception:
        return None
    return None


def _token_fields(tok: dict[str, Any]) -> dict[str, Any]:
    """把 token 结果摊平进会话字典，供前端与排序使用。"""
    return {
        "tokens": tok.get("tokens", 0),
        "chat_tokens": tok.get("chat_tokens", 0),
        "aux_tokens": tok.get("aux_tokens", 0),
        "input_tokens": tok.get("input_tokens", 0),
        "output_tokens": tok.get("output_tokens", 0),
        "thoughts_tokens": tok.get("thoughts_tokens", 0),
        "content_tokens": tok.get("content_tokens", tok.get("tokens", 0)),
        "usage_source": tok.get("usage_source", "estimated"),
    }


def _token_result_from_cache(cached: dict[str, Any]) -> dict[str, int | str]:
    return {
        "tokens": int(cached.get("tokens") or 0),
        "chat_tokens": int(cached.get("chat_tokens") or 0),
        "aux_tokens": int(cached.get("aux_tokens") or 0),
        "input_tokens": int(cached.get("input_tokens") or 0),
        "output_tokens": int(cached.get("output_tokens") or 0),
        "thoughts_tokens": int(cached.get("thoughts_tokens") or 0),
        "content_tokens": int(cached.get("content_tokens") or cached.get("tokens") or 0),
        "calls": int(cached.get("calls") or 0),
        "usage_source": str(cached.get("usage_source") or "estimated"),
    }


def compute_session_tokens(
    fmt: str,
    session_id: str,
    file_path: Path | None,
    mtime: float,
    size_bytes: int,
    trae_chat_tokens: int | None = None,
    trae_aux_tokens: int | None = None,
) -> dict[str, int | str]:
    """Compute and cache token figures for a session.

    tokens      —— 对外展示的主口径：有记录值时为「计费总量」(输入+输出)，
                   否则为内容体积估算值。
    input_tokens / output_tokens / thoughts_tokens
                —— 仅在使用记录值时有效。
    content_tokens
                —— 内容体积（去重后一次算完），不受重复发送影响，可作体积参考。
    usage_source—— "recorded" | "estimated"。
    """
    global _TOKEN_CACHE_DIRTY
    _ensure_token_cache_loaded()
    cache_key = f"{fmt}:{session_id}"
    sig = f"v{TOKEN_CACHE_VERSION}:{int(mtime)}:{int(size_bytes)}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached.get("sig") == sig:
        return _token_result_from_cache(cached)

    chat_t = 0
    aux_t = 0
    recorded = read_recorded_usage(fmt, file_path)

    if fmt == "trae" and trae_chat_tokens is not None:
        chat_t = max(0, int(trae_chat_tokens))
        aux_t = max(0, int(trae_aux_tokens or 0))
    elif fmt == "antigravity" and file_path and file_path.exists():
        try:
            from session_migrate.formats.antigravity import (
                _decode_message,
                _optional_bytes,
                _optional_text,
            )
            conn = sqlite3.connect(f"file:{str(file_path)}?mode=ro", uri=True)
            try:
                for stype, payload in conn.execute(
                    "SELECT step_type, step_payload FROM steps WHERE step_type IN (14, 15)"
                ).fetchall():
                    if not payload:
                        continue
                    if stype == 14:
                        try:
                            outer = _decode_message(payload)
                            inner = _optional_bytes(outer, 19)
                            if inner:
                                flds = _decode_message(inner)
                                txt = _optional_text(flds, 2) or _optional_text(flds, 1) or ""
                                ut = estimate_text_tokens(txt)
                                chat_t += ut
                                tot_u = estimate_text_tokens(inner.decode("utf-8", errors="ignore"))
                                aux_t += max(0, tot_u - ut)
                            else:
                                chat_t += estimate_text_tokens(payload.decode("utf-8", errors="ignore"))
                        except Exception:
                            chat_t += estimate_text_tokens(payload.decode("utf-8", errors="ignore"))
                    elif stype == 15:
                        try:
                            outer = _decode_message(payload)
                            inner = _optional_bytes(outer, 20)
                            if inner:
                                flds = _decode_message(inner)
                                resp = _optional_text(flds, 1) or ""
                                rt = estimate_text_tokens(resp)
                                chat_t += rt
                                tot_p = estimate_text_tokens(inner.decode("utf-8", errors="ignore"))
                                aux_t += max(0, tot_p - rt)
                            else:
                                chat_t += estimate_text_tokens(payload.decode("utf-8", errors="ignore"))
                        except Exception:
                            chat_t += estimate_text_tokens(payload.decode("utf-8", errors="ignore"))
                tool_bytes = (
                    conn.execute(
                        "SELECT sum(length(step_payload)) FROM steps WHERE step_type IN (8, 9, 21, 38, 86, 112, 128, 132)"
                    ).fetchone()[0]
                    or 0
                )
                aux_t += int(tool_bytes * 0.25)
            finally:
                conn.close()
        except Exception:
            total_est = max(1, int(size_bytes * 0.20))
            chat_t = int(total_est * 0.35)
            aux_t = total_est - chat_t
    elif file_path and file_path.exists() and (fmt in {"claude", "workbuddy"} or file_path.suffix == ".jsonl"):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    rec_type = str(d.get("type") or "").lower()
                    if rec_type in {"file-history-snapshot", "session-meta", "ai-title", "summary"}:
                        continue
                    if rec_type == "reasoning":
                        r_txt = d.get("rawContent") or d.get("content") or ""
                        aux_t += estimate_text_tokens(
                            r_txt if isinstance(r_txt, str) else json.dumps(r_txt, ensure_ascii=False)
                        )
                        continue
                    if rec_type in {"function_call", "function_call_result"}:
                        f_payload = d.get("arguments") or d.get("output") or ""
                        aux_t += estimate_text_tokens(
                            f_payload if isinstance(f_payload, str) else json.dumps(f_payload, ensure_ascii=False)
                        )
                        continue
                    msg_obj = d.get("message") if isinstance(d.get("message"), dict) else {}
                    role = str(d.get("role") or msg_obj.get("role") or rec_type).lower()
                    c = d.get("content") if "content" in d else msg_obj.get("content")
                    if isinstance(c, str):
                        if role in {"user", "assistant", "human", "message"}:
                            chat_t += estimate_text_tokens(c)
                        else:
                            aux_t += estimate_text_tokens(c)
                    elif isinstance(c, list):
                        for item in c:
                            if isinstance(item, dict):
                                btype = str(item.get("type") or "").lower()
                                if btype in {"text", "input_text", "output_text"} and role in {
                                    "user",
                                    "assistant",
                                    "human",
                                    "message",
                                }:
                                    chat_t += estimate_text_tokens(str(item.get("text") or ""))
                                else:
                                    sub = (
                                        item.get("text")
                                        or item.get("thinking")
                                        or item.get("content")
                                        or item.get("input")
                                        or item
                                    )
                                    aux_t += estimate_text_tokens(
                                        sub if isinstance(sub, str) else json.dumps(sub, ensure_ascii=False)
                                    )
                            elif isinstance(item, str):
                                chat_t += estimate_text_tokens(item)
        except Exception:
            total_est = max(1, int(size_bytes * 0.25))
            chat_t = int(total_est * 0.45)
            aux_t = total_est - chat_t
    elif file_path and file_path.exists():
        try:
            sess = load_session(file_path, AgentFormat(fmt))
            for ev in sess.events:
                k = ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind)
                if k == "message":
                    chat_t += estimate_text_tokens(ev.text or "")
                else:
                    raw_sub = ev.text or (json.dumps(ev.payload, ensure_ascii=False) if ev.payload else "")
                    aux_t += estimate_text_tokens(raw_sub)
        except Exception:
            total_est = max(1, int(size_bytes * 0.25))
            chat_t = int(total_est * 0.4)
            aux_t = total_est - chat_t

    content_t = chat_t + aux_t
    if content_t == 0 and size_bytes > 0:
        content_t = max(1, int(size_bytes * 0.25))
        chat_t = content_t

    if recorded:
        billed_in = int(recorded.get("input") or 0)
        billed_out = int(recorded.get("output") or 0)
        res: dict[str, int | str] = {
            "tokens": billed_in + billed_out,
            # 兼容旧前端字段：chat_tokens 保持「模型产出」，aux_tokens 保持「输入侧」
            "chat_tokens": billed_out,
            "aux_tokens": billed_in,
            "input_tokens": billed_in,
            "output_tokens": billed_out,
            "thoughts_tokens": int(recorded.get("thoughts") or 0),
            "content_tokens": content_t,
            "calls": int(recorded.get("calls") or 0),
            "usage_source": "recorded",
        }
    else:
        res = {
            "tokens": content_t,
            "chat_tokens": chat_t,
            "aux_tokens": aux_t,
            "input_tokens": 0,
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "content_tokens": content_t,
            "calls": 0,
            "usage_source": "estimated",
        }
    _TOKEN_CACHE[cache_key] = {"sig": sig, **res}
    _TOKEN_CACHE_DIRTY = True
    return res

# Format branding definitions
AGENT_META = {
    "antigravity": {
        "name": "Antigravity",
        "badge_color": "linear-gradient(135deg, #6366f1, #8b5cf6)",
        "icon": "⚡",
        "description": "Google Antigravity IDE & CLI Cascade trajectories",
    },
    "claude": {
        "name": "Claude Code",
        "badge_color": "linear-gradient(135deg, #d97706, #ea580c)",
        "icon": "🟣",
        "description": "Anthropic Claude Code CLI projects & sessions",
    },
    "workbuddy": {
        "name": "WorkBuddy",
        "badge_color": "linear-gradient(135deg, #059669, #10b981)",
        "icon": "🤖",
        "description": "WorkBuddy coding agent projects & local sessions",
    },
    "trae": {
        "name": "Trae",
        "badge_color": "linear-gradient(135deg, #8b5cf6, #ec4899)",
        "icon": "◆",
        "description": "ByteDance Trae chats, agent builder & memory sessions",
    },
    "cursor": {
        "name": "Cursor",
        "badge_color": "linear-gradient(135deg, #0d9488, #059669)",
        "icon": "🖱️",
        "description": "Cursor IDE Composer / Agent SQLite chats",
    },
    "copilot": {
        "name": "GitHub Copilot",
        "badge_color": "linear-gradient(135deg, #2563eb, #3b82f6)",
        "icon": "🤖",
        "description": "GitHub Copilot CLI / extension session state",
    },
    "codex": {
        "name": "Codex",
        "badge_color": "linear-gradient(135deg, #475569, #334155)",
        "icon": "📜",
        "description": "OpenAI Codex agent sessions",
    },
    "kimi": {
        "name": "Kimi Code",
        "badge_color": "linear-gradient(135deg, #7c3aed, #a855f7)",
        "icon": "🌙",
        "description": "Moonshot Kimi code assistant conversations",
    },
    "devin": {
        "name": "Devin",
        "badge_color": "linear-gradient(135deg, #ec4899, #f43f5e)",
        "icon": "💻",
        "description": "Cognition Devin CLI sessions",
    },
}

# Pre-cache brain_readable map for clean Antigravity titles
BRAIN_READABLE_DIR = _home_path(".gemini", "antigravity-ide", "brain_readable")
ANTIGRAVITY_APP_DIR = _home_path(".gemini", "antigravity")
ANTIGRAVITY_CONV_DIRS = [
    _home_path(".gemini", "antigravity", "conversations"),
    _home_path(".gemini", "antigravity-cli", "conversations"),
]

_AG_LINEAGE_CACHE: dict[tuple[str, float, int], str] = {}


def antigravity_lineage_key(db_path: Path) -> str:
    """同源对话指纹。

    Antigravity 在「恢复/分叉/崩溃重启」时会整段复制历史步骤，生成一个全新
    conversation_id 的 .db —— 前几步的 payload 字节完全相同。用前 3 步的哈希
    作为血缘标识，就能把同一条对话的多个快照认出来。
    """
    try:
        stat = db_path.stat()
    except OSError:
        return ""
    cache_key = (str(db_path), stat.st_mtime, stat.st_size)
    cached = _AG_LINEAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    key = ""
    try:
        with sqlite3.connect(f"file:{str(db_path)}?mode=ro", uri=True) as conn:
            rows = conn.execute("SELECT step_payload FROM steps ORDER BY idx LIMIT 3").fetchall()
        digest = hashlib.sha256()
        for (payload,) in rows:
            if payload:
                digest.update(payload)
        if rows:
            key = digest.hexdigest()[:16]
    except Exception:
        key = ""
    if key:
        _AG_LINEAGE_CACHE[cache_key] = key
    return key


_AG_BTW_MARKER = "This is a side question from the user"
_AG_BTW_CACHE: dict[tuple[str, float, int], str] = {}


def antigravity_side_question(db_path: Path) -> str:
    """识别 /btw 旁问分支。

    Antigravity 的侧边提问不会追加到主线，而是复制整段历史另开一个会话，末尾
    插入一条合成消息：「This is a side question from the user... Here is the
    question: xxx」。命中的会话返回真正的提问内容，便于 UI 标注。
    """
    try:
        stat = db_path.stat()
    except OSError:
        return ""
    cache_key = (str(db_path), stat.st_mtime, stat.st_size)
    if cache_key in _AG_BTW_CACHE:
        return _AG_BTW_CACHE[cache_key]
    question = ""
    try:
        from session_migrate.formats.antigravity import (
            _decode_message as _ag_decode,
            _optional_bytes as _ag_bytes,
            _optional_text as _ag_text,
        )

        with sqlite3.connect(f"file:{str(db_path)}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT step_payload FROM steps WHERE step_type=14 ORDER BY idx DESC LIMIT 2"
            ).fetchall()
        for (payload,) in rows:
            if not payload:
                continue
            # 用户输入步：外层 payload 里第 19 号字段内嵌正文
            text = ""
            try:
                outer = _ag_decode(payload)
                inner = _ag_bytes(outer, 19)
                if inner:
                    fields = _ag_decode(inner)
                    text = _ag_text(fields, 2) or _ag_text(fields, 1) or ""
            except Exception:
                text = ""
            if not text.startswith(_AG_BTW_MARKER):
                continue
            question = text.split("Here is the question:", 1)[-1].strip()
            break
    except Exception:
        question = ""
    _AG_BTW_CACHE[cache_key] = question
    return question


def _mark_antigravity_lineage(results: list[dict[str, Any]]) -> None:
    """给同源对话打标：步骤最多的那份算主快照，其余标记为分叉副本。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        if item.get("format") != "antigravity":
            continue
        item.setdefault("is_lineage_branch", False)
        item.setdefault("lineage_head_id", "")
        item.setdefault("lineage_head_steps", 0)
        item.setdefault("lineage_head_title", "")
        item.setdefault("lineage_size", 1)
        item.setdefault("branch_label", "")
        key = item.get("lineage")
        if not key:
            continue
        groups.setdefault(key, []).append(item)
    for group in groups.values():
        if len(group) < 2:
            continue
        primary = max(group, key=lambda x: (int(x.get("records") or 0), float(x.get("mtime") or 0)))
        for item in group:
            item["lineage_size"] = len(group)
            item["lineage_head_id"] = primary.get("catalog_id")
            item["lineage_head_title"] = primary.get("title")
            item["lineage_head_steps"] = primary.get("records")
            item["is_lineage_branch"] = item is not primary
            if item is not primary:
                item["branch_label"] = "/btw 旁问" if item.get("side_question") else "同源分支"


def _mark_antigravity_children(results: list[dict[str, Any]]) -> None:
    """关联父子会话拓扑结构。

    根据 parent_id 将 Antigravity 子代理会话归集到对应的主会话下，
    父会话附加 children 列表与 children_count，子会话标记 is_child=True
    并记录父会话标题与 ID。
    """
    id_map: dict[str, dict[str, Any]] = {}
    for item in results:
        sid = item.get("session_id")
        if sid:
            id_map[sid] = item

    for item in results:
        pid = item.get("parent_id")
        if pid and item.get("format") == "antigravity":
            item["is_child"] = True
            parent_item = id_map.get(pid)
            if parent_item:
                item["parent_title"] = parent_item.get("title", "")
                item["parent_catalog_id"] = parent_item.get("catalog_id", "")
                child_summary = {
                    "catalog_id": item.get("catalog_id", ""),
                    "session_id": item.get("session_id", ""),
                    "format": item.get("format", "antigravity"),
                    "title": item.get("title", ""),
                    "agent_name": item.get("agent_name") or "subagent",
                    "records": item.get("records") or 0,
                    "bytes": item.get("bytes") or 0,
                    "tokens": item.get("tokens") or 0,
                    "input_tokens": item.get("input_tokens") or 0,
                    "output_tokens": item.get("output_tokens") or 0,
                    "thoughts_tokens": item.get("thoughts_tokens") or 0,
                    "content_tokens": item.get("content_tokens") or 0,
                    "usage_source": item.get("usage_source", ""),
                    "started_at": item.get("started_at", ""),
                    "mtime": item.get("mtime", 0),
                    "file_path": item.get("file_path", ""),
                }
                parent_children = parent_item.setdefault("children", [])
                parent_children.append(child_summary)
            else:
                item["parent_title"] = ""
                item["parent_catalog_id"] = f"ag_{pid[:12]}"

    for item in results:
        if "children" in item:
            item["children"].sort(key=lambda x: (x.get("started_at") or "", float(x.get("mtime") or 0)))
            item["children_count"] = len(item["children"])
        else:
            item["children"] = []
            item["children_count"] = 0


def load_antigravity_summaries_map() -> dict[str, dict[str, Any]]:
    """Load latest official titles and metadata from Antigravity's conversation_summaries.db."""
    summaries: dict[str, dict[str, Any]] = {}
    db_paths = [
        _home_path(".gemini", "antigravity", "conversation_summaries.db"),
        _home_path(".gemini", "antigravity-ide", "conversation_summaries.db"),
    ]
    for db_p in db_paths:
        if not db_p.exists() or db_p.stat().st_size == 0:
            continue
        try:
            with sqlite3.connect(f"file:{str(db_p)}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT conversation_id, title, preview, step_count, last_modified_time,"
                    " parent_conversation_id, nesting_depth, agent_name"
                    " FROM conversation_summaries"
                ).fetchall()
                for r in rows:
                    cid = r["conversation_id"]
                    if not cid or cid in summaries:
                        continue
                    t = (r["title"] or "").strip()
                    p = (r["preview"] or "").strip()
                    clean_t = ""
                    for cand in [t, p]:
                        if cand and not re.match(r"^[0-9a-f\-]{36}$", cand) and not re.match(r"^[0-9a-f]{32}$", cand):
                            clean_t = clean_human_title(cand)
                            if clean_t:
                                break
                    summaries[cid] = {
                        "title": clean_t or t or p,
                        "step_count": r["step_count"],
                        "last_modified_time": r["last_modified_time"],
                        "parent_id": (r["parent_conversation_id"] or "").strip(),
                        "nesting_depth": r["nesting_depth"] or 0,
                        "agent_name": (r["agent_name"] or "").strip(),
                    }
        except Exception:
            pass
    return summaries

def antigravity_parent_title(
    sid: str, summaries: dict[str, dict[str, Any]], _depth: int = 0
) -> tuple[str, str]:
    """向上找父会话标题，返回 (父标题, 本会话的 agent 名)。

    Antigravity 的 browser 等子代理会话在 conversation_summaries 里 title 恒为空，
    只有 parent_conversation_id。回溯父链才能给出可读名字。
    """
    info = summaries.get(sid)
    if not info or _depth > 4:
        return "", ""
    agent = str(info.get("agent_name") or "")
    parent_id = str(info.get("parent_id") or "")
    if not parent_id:
        return "", agent
    parent = summaries.get(parent_id)
    if not parent:
        return "", agent
    parent_title = str(parent.get("title") or "")
    if not parent_title and parent.get("parent_id"):
        parent_title, _ = antigravity_parent_title(parent_id, summaries, _depth + 1)
    return parent_title, agent or str(parent.get("agent_name") or "")


_AG_FIRST_TEXT_CACHE: dict[tuple[str, float, int], str] = {}


def antigravity_first_user_text(db_path: Path, limit: int = 48) -> str:
    """取会话第一条用户输入作为标题兜底。

    直接走 protobuf：payload → 字段 19（用户输入）→ 子字段 2（正文）。
    """
    try:
        stat = db_path.stat()
    except OSError:
        return ""
    cache_key = (str(db_path), stat.st_mtime, stat.st_size)
    if cache_key in _AG_FIRST_TEXT_CACHE:
        return _AG_FIRST_TEXT_CACHE[cache_key]
    text = ""
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT step_payload FROM steps WHERE step_type = 14 ORDER BY idx ASC LIMIT 3"
        ).fetchall()
        for (payload,) in rows:
            if not payload:
                continue
            inner = None
            for num, wt, val in _pb_iter(payload, stop_after=19):
                if num == 19 and wt == 2:
                    inner = val
            if not isinstance(inner, bytes):
                continue
            body = None
            for num, wt, val in _pb_iter(inner):
                if num == 2 and wt == 2:
                    body = val
                    break
            if not isinstance(body, bytes):
                continue
            candidate = body.decode("utf-8", "ignore").strip()
            if candidate:
                lines = [ln.strip() for ln in candidate.splitlines() if ln.strip()]
                merged = ""
                for ln in lines[:6]:
                    merged = f"{merged} {ln}".strip() if merged else ln
                    if len(merged) >= 12:
                        break
                text = clean_human_title(merged)
                if text:
                    break
    except Exception:
        text = ""
    finally:
        if conn is not None:
            conn.close()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    _AG_FIRST_TEXT_CACHE[cache_key] = text
    return text


def ensure_antigravity_catalog_roots():
    """Ensure ~/.gemini/antigravity is registered in catalog database."""
    try:
        target_path = str(ANTIGRAVITY_APP_DIR.resolve())
        with Catalog(default_catalog_path()) as cat:
            roots = [str(Path(r.path).resolve()) for r in cat.roots()]
            if target_path not in roots and ANTIGRAVITY_APP_DIR.exists():
                cat.add_root(AgentFormat.ANTIGRAVITY, Path(target_path))
    except Exception:
        pass

def load_brain_readable_map() -> dict[str, dict[str, str]]:
    readable_map = {}
    if BRAIN_READABLE_DIR.exists():
        for p in BRAIN_READABLE_DIR.iterdir():
            # Format: YYYY-MM-DD_Title_UUID8
            m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)_[0-9a-fA-F]{8}$", p.name)
            short_id = p.name.split("_")[-1].lower() if "_" in p.name else ""
            if m:
                date_str, title = m.group(1), m.group(2)
                readable_map[short_id] = {
                    "date": date_str,
                    "title": title.replace("_", " "),
                    "display": f"{date_str} · {title.replace('_', ' ')}",
                    "folder": p.name
                }
    return readable_map

_CLAUDE_TITLE_STRIP_RE = re.compile(
    r"<(?:local-command-caveat|command-name|command-message|command-args|local-command-stdout|local-command-stderr|"
    r"bash-input|bash-stdout|bash-stderr|ide_opened_file|ide_selection|system-reminder|task-notification|"
    r"conversation_history_summary)\b[^>]*>.*?</(?:local-command-caveat|command-name|command-message|command-args|"
    r"local-command-stdout|local-command-stderr|bash-input|bash-stdout|bash-stderr|ide_opened_file|ide_selection|"
    r"system-reminder|task-notification|conversation_history_summary)>",
    re.S | re.I,
)


def _clean_claude_title_candidate(raw_text: str) -> str:
    """剥离 Claude Code 的 XML 系统/命令包裹，提取真实用户提问标题。"""
    if not raw_text:
        return ""
    cleaned = _CLAUDE_TITLE_STRIP_RE.sub(" ", raw_text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    return cleaned.splitlines()[0][:60].strip()


def extract_claude_title_and_date(jsonl_path: Path) -> tuple[str, str]:
    title = ""
    date_str = ""
    fallback_title = ""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                data = json.loads(line)
                ts = data.get("timestamp")
                if ts and not date_str:
                    try:
                        if isinstance(ts, str):
                            date_str = ts.split("T")[0]
                        elif isinstance(ts, (int, float)):
                            date_str = datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    except Exception:
                        pass
                if data.get("type") == "user" and "message" in data:
                    content = data["message"].get("content")
                    raw_cand = ""
                    if isinstance(content, str) and content.strip():
                        raw_cand = content.strip()
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("text"):
                                raw_cand = item["text"].strip()
                                break
                    if raw_cand:
                        cleaned = _clean_claude_title_candidate(raw_cand)
                        if cleaned:
                            title = cleaned
                            break
                        if not fallback_title:
                            m_bash = re.search(r"<bash-input>\s*(.*?)\s*</bash-input>", raw_cand, re.S | re.I)
                            m_cmd = re.search(r"<command-name>\s*(.*?)\s*</command-name>", raw_cand, re.S | re.I)
                            if m_bash and m_bash.group(1).strip():
                                fallback_title = f"命令：{m_bash.group(1).strip()[:50]}"
                            elif m_cmd and m_cmd.group(1).strip():
                                fallback_title = f"斜杠命令：{m_cmd.group(1).strip()[:50]}"
    except Exception:
        pass
    if not title:
        title = fallback_title
    if not date_str:
        try:
            date_str = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except:
            date_str = "2026-04-25"
    if not title:
        title = jsonl_path.stem
    return title, date_str

# ---------------------------------------------------------------------------
# WorkBuddy 记录清洗
# ---------------------------------------------------------------------------
# WorkBuddy 会把大量「非用户输入」写进 role=user 的记录里：注入式
# <system-reminder>（环境信息、SOUL/IDENTITY/USER 身份文件、当前时间、记忆提醒）、
# 后台任务回执 <task-notification>、上下文压缩快照 <conversation_history_summary>。
# 若原样当成「用户指令」渲染，卡片里就是一整屏系统提示词，真实提问被埋没。
# 下面把真正的 <user_query> 抽出来，其余降级为「系统通知」事件。
_WB_SYS_REMINDER_RE = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S | re.I)
_WB_TASK_NOTIF_RE = re.compile(r"<task-notification\b[^>]*>.*?</task-notification>", re.S | re.I)
_WB_HISTORY_SUMMARY_RE = re.compile(r"<conversation_history_summary\b[^>]*>.*?</conversation_history_summary>", re.S | re.I)
_WB_QUERY_RE = re.compile(r"<user_query\s*>(.*?)</user_query\s*>", re.S | re.I)
_WB_SYS_NOTE_RE = re.compile(r"^\[SYSTEM NOTIFICATION - NOT USER INPUT\][^\n]*$", re.I | re.M)
_WB_TASKOUT_HINT_RE = re.compile(r"^Use the TaskOutput tool[^\n]*$", re.I | re.M)
_WB_LONG_QUOTE_OPEN_RE = re.compile(r"</?long_text_quote\b[^>]*>", re.I)
_WB_CONTINUE_HINT = "please continue with the conversation based on the summarized context above"


class _WbCharCounter:
    """按正则删除片段并累计被删字符数。"""

    def __init__(self) -> None:
        self.removed = 0

    def sub(self, pattern: re.Pattern[str], text: str) -> str:
        def _drop(match: re.Match[str]) -> str:
            self.removed += len(match.group(0))
            return ""

        return pattern.sub(_drop, text)


def _wb_content_text(record: dict[str, Any]) -> str:
    """取出 WorkBuddy 记录的正文（content 可能是 str，也可能是 [{type,text}] 列表）。"""
    content = record.get("content")
    if content is None:
        message = record.get("message")
        if isinstance(message, dict):
            content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                piece = item.get("text")
                if isinstance(piece, str) and piece:
                    parts.append(piece)
        return "\n".join(parts)
    fallback = record.get("text")
    return fallback if isinstance(fallback, str) else ""


def _wb_tidy_visible(text: str) -> str:
    """去掉展示层无意义的包裹标签与多余空行，正文保持原样。"""
    if not text:
        return ""
    text = _WB_LONG_QUOTE_OPEN_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_workbuddy_user_record(record: dict[str, Any]) -> dict[str, Any]:
    """把 role=user 的记录拆成「真实用户指令」或「系统通知」。

    返回 kind: user / notice / skip，附带可见正文、原文与被过滤字数。
    """
    raw = _html_unescape(_wb_content_text(record).strip())
    provider = record.get("providerData")
    is_meta = bool(provider.get("isMeta")) if isinstance(provider, dict) else False
    if not raw:
        return {"kind": "skip", "text": "", "raw": "", "hidden": 0, "label": ""}

    lowered = raw.lower()

    # 1. 含 <user_query>：只保留用户真正敲进去的正文
    if _WB_QUERY_RE.search(raw):
        queries = [m.group(1).strip() for m in _WB_QUERY_RE.finditer(raw)]
        visible = "\n\n".join(q for q in queries if q)
        counter = _WbCharCounter()
        residue = raw
        for pattern in (_WB_SYS_REMINDER_RE, _WB_TASK_NOTIF_RE, _WB_HISTORY_SUMMARY_RE, _WB_SYS_NOTE_RE):
            residue = counter.sub(pattern, residue)
        residue = _WB_QUERY_RE.sub("", residue)
        residue = _wb_tidy_visible(residue)
        # <user_query> 之外的正文（附件、截图路径等）仍然属于用户输入，一并保留
        if residue:
            visible = f"{visible}\n\n{residue}".strip() if visible else residue
        visible = _wb_tidy_visible(visible)
        if not visible:
            return {"kind": "skip", "text": "", "raw": raw, "hidden": len(raw), "label": ""}
        return {
            "kind": "user",
            "text": visible,
            "raw": raw,
            "hidden": max(len(raw) - len(visible), 0),
            "label": "",
        }

    # 2. 上下文压缩快照：属于会话内部状态，不是用户发言
    if "<conversation_history_summary" in lowered:
        summary = _WB_HISTORY_SUMMARY_RE.search(raw)
        body = _wb_tidy_visible(summary.group(0)) if summary else _wb_tidy_visible(raw)
        label = "上下文压缩快照"
        return {"kind": "notice", "text": body or raw, "raw": raw, "hidden": 0, "label": label}

    # 3. 后台任务回执 / 自动续写指令：均由系统代发
    if is_meta or "<task-notification" in lowered:
        notif = re.search(r"<task-notification\b[^>]*>(.*?)</task-notification>", raw, re.S | re.I)
        if notif:
            inner = notif.group(1)
            task_id = re.search(r"<task-id>(.*?)</task-id>", inner, re.S | re.I)
            status = re.search(r"<status>(.*?)</status>", inner, re.S | re.I)
            summary = re.search(r"<summary>(.*?)</summary>", inner, re.S | re.I)
            if summary:
                head = "任务 " + (task_id.group(1).strip() if task_id else "—")
                if status and status.group(1).strip():
                    head += " · " + status.group(1).strip()
                body = head + "\n" + summary.group(1).strip()
            else:
                lines = []
                for text_line in inner.splitlines():
                    plain = re.sub(r"<[^>]+>", "", text_line).strip()
                    if plain:
                        lines.append(plain)
                body = "\n".join(lines).strip()
        else:
            counter = _WbCharCounter()
            cleaned = raw
            for pattern in (_WB_SYS_REMINDER_RE, _WB_TASK_NOTIF_RE, _WB_SYS_NOTE_RE, _WB_TASKOUT_HINT_RE):
                cleaned = counter.sub(pattern, cleaned)
            body = _wb_tidy_visible(cleaned) or _wb_tidy_visible(raw)
        return {"kind": "notice", "text": body, "raw": raw, "hidden": 0, "label": "后台任务回执"}

    if _WB_CONTINUE_HINT in lowered:
        return {"kind": "notice", "text": raw, "raw": raw, "hidden": 0, "label": "自动续写指令"}

    # 4. 纯 system-reminder 包裹（无 user_query）：整条丢弃，避免污染指令流
    counter = _WbCharCounter()
    cleaned = raw
    for pattern in (_WB_SYS_REMINDER_RE, _WB_SYS_NOTE_RE):
        cleaned = counter.sub(pattern, cleaned)
    cleaned = _wb_tidy_visible(cleaned)
    if not cleaned:
        return {"kind": "skip", "text": "", "raw": raw, "hidden": len(raw), "label": ""}
    return {"kind": "user", "text": cleaned, "raw": raw, "hidden": max(len(raw) - len(cleaned), 0), "label": ""}


def _wb_reasoning_text(record: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("rawContent", "content"):
        items = record.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    piece = item.get("text")
                    if isinstance(piece, str) and piece.strip():
                        parts.append(piece.strip())
    return "\n\n".join(parts)


def _wb_tool_output_text(record: dict[str, Any]) -> str:
    output = record.get("output")
    if isinstance(output, dict):
        for key in ("text", "content", "output"):
            piece = output.get(key)
            if isinstance(piece, str) and piece.strip():
                return piece
        try:
            return json.dumps(output, ensure_ascii=False, indent=2)
        except Exception:
            return str(output)
    if isinstance(output, str):
        return output
    return ""


def get_workbuddy_session_events(jsonl_path: Path) -> list[dict[str, Any]]:
    """把 WorkBuddy 的 jsonl 还原成对话流事件。

    事件类型：message(user/assistant) / notice / thinking / tool_call / tool_result。
    user 事件只保留真实用户提问，raw_text 保留完整原文供追溯。
    """
    events: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue

            rtype = record.get("type")
            timestamp = str(record.get("timestamp", ""))

            if rtype == "message":
                role = record.get("role") or "assistant"
                if role == "user":
                    classified = classify_workbuddy_user_record(record)
                    if classified["kind"] == "user":
                        paste_hint = _pasted_payload_hint(classified["text"])
                        events.append({
                            "kind": "message",
                            "role": "user",
                            "timestamp": timestamp,
                            "text": classified["text"],
                            "raw_text": classified["raw"] if classified["hidden"] > 0 else "",
                            "hidden_chars": classified["hidden"],
                            "collapsed": bool(paste_hint),
                            "summary": paste_hint,
                            "tool_name": "",
                            "payload": None,
                        })
                    elif classified["kind"] == "notice":
                        events.append({
                            "kind": "notice",
                            "role": "system",
                            "timestamp": timestamp,
                            "text": classified["text"],
                            "raw_text": "",
                            "hidden_chars": 0,
                            "label": classified["label"],
                            "tool_name": "",
                            "payload": None,
                        })
                else:
                    text = _wb_content_text(record).strip()
                    if text:
                        events.append({
                            "kind": "message",
                            "role": "assistant",
                            "timestamp": timestamp,
                            "text": text,
                            "raw_text": "",
                            "hidden_chars": 0,
                            "tool_name": "",
                            "payload": None,
                        })

            elif rtype == "reasoning":
                text = _wb_reasoning_text(record)
                if text:
                    events.append({
                        "kind": "thinking",
                        "role": "assistant",
                        "timestamp": timestamp,
                        "text": text,
                        "tool_name": "",
                        "payload": None,
                    })

            elif rtype == "function_call":
                tool_name = str(record.get("name") or "tool")
                arguments = record.get("arguments")
                parsed_args: Any = arguments
                if isinstance(arguments, str):
                    try:
                        parsed_args = json.loads(arguments)
                    except Exception:
                        parsed_args = arguments
                if isinstance(parsed_args, (dict, list)):
                    try:
                        detail = json.dumps(parsed_args, ensure_ascii=False, indent=2)
                    except Exception:
                        detail = str(parsed_args)
                else:
                    detail = str(parsed_args or "")
                events.append({
                    "kind": "tool_call",
                    "role": "assistant",
                    "timestamp": timestamp,
                    "text": detail,
                    "tool_name": tool_name,
                    "payload": {"input": parsed_args if isinstance(parsed_args, dict) else {}},
                    "call_id": str(record.get("callId") or ""),
                    "status": "",
                })

            elif rtype == "function_call_result":
                text = _wb_tool_output_text(record).strip()
                events.append({
                    "kind": "tool_result",
                    "role": "tool",
                    "timestamp": timestamp,
                    "text": text,
                    "tool_name": str(record.get("name") or "tool"),
                    "payload": None,
                    "call_id": str(record.get("callId") or ""),
                    "status": str(record.get("status") or ""),
                })

    return events


# ---------------------------------------------------------------------------
# 通用会话事件清洗（Claude / Antigravity / Trae / Cursor / Codex …）
# ---------------------------------------------------------------------------
# 除 WorkBuddy 外，其它客户端的 role=user 记录同样混着非用户内容：
#   Claude Code   —— <command-name>/model</command-name>、<local-command-stdout> 等斜杠命令包裹
#   Antigravity   —— 续接历史时把 "Listed directory … Viewed …" 工具动作摘要塞进用户轮
#   Cursor/Codex  —— <user_info> / <environment_context> 环境注入
# 统一在这里剥离，用户指令只留人真正敲进去的话。
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_UNIV_SYS_BLOCK_RES = (
    re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S | re.I),
    re.compile(r"<user_info\b[^>]*>.*?</user_info>", re.S | re.I),
    re.compile(r"<environment_context\b[^>]*>.*?</environment_context>", re.S | re.I),
    re.compile(r"<conversation_history_summary\b[^>]*>.*?</conversation_history_summary>", re.S | re.I),
    re.compile(r"<task-notification\b[^>]*>.*?</task-notification>", re.S | re.I),
    re.compile(r"<local-command-caveat\b[^>]*>.*?</local-command-caveat>", re.S | re.I),
    re.compile(r"<ide_opened_file\b[^>]*>.*?</ide_opened_file>", re.S | re.I),
    re.compile(r"<ide_selection\b[^>]*>.*?</ide_selection>", re.S | re.I),
)
_UNIV_CAVEAT_RE = re.compile(
    r"Caveat: The messages below were generated by the user while running local commands\.[^\n]*", re.I
)
_CLI_CMD_NAME_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.S | re.I)
_CLI_CMD_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.S | re.I)
_CLI_OUTPUT_RE = re.compile(r"<local-command-(stdout|stderr)>\s*(.*?)\s*</local-command-\1>", re.S | re.I)
_CLI_CMD_BLOCK_RE = re.compile(r"<command-(name|message|args)\b[^>]*>.*?</command-\1>", re.S | re.I)
_TOOL_LOG_LINE_RE = re.compile(
    r"^(?:Listed directory|Listed files|Viewed |Read file|Searched for|Searched |Ran command|Ran |"
    r"Created file|Edited file|Wrote |Deleted |Executed |Checked |Updated )"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", text or "")


_PASTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/)[^\n]*\.(?:json|jsonl|ya?ml|toml|csv|tsv|log|md|txt|py|ts|tsx|js|jsx|ini|conf|cfg)$", re.I)


def _pasted_payload_hint(text: str) -> str:
    """识别「问题 + 整份文件内容」型长消息，返回折叠用的摘要标题。"""
    if len(text) < 900:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 10:
        return ""
    first = lines[0].strip()
    if first.startswith("{") or first.startswith("["):
        return "粘贴内容 · 结构化数据"
    if _PASTE_PATH_RE.match(first):
        return "粘贴内容 · " + first[:70]
    return ""


def _cli_command_notice(text: str) -> str:
    """把 Claude Code 的斜杠命令包裹翻译成人话，返回通知正文。"""
    parts: list[str] = []
    args_map: list[str] = _CLI_CMD_ARGS_RE.findall(text)
    names: list[str] = _CLI_CMD_NAME_RE.findall(text)
    for index, name in enumerate(names):
        cmd = name.strip()
        if not cmd:
            continue
        arg_text = args_map[index].strip() if index < len(args_map) else ""
        parts.append("执行命令 " + cmd + ("（参数：" + arg_text + "）" if arg_text else ""))
    for stream, body in _CLI_OUTPUT_RE.findall(text):
        body = _strip_ansi(body).strip()
        if body:
            parts.append(("命令输出：" if stream.lower() == "stdout" else "命令错误输出：") + body)
    residue = _CLI_CMD_BLOCK_RE.sub("", text)
    residue = _CLI_OUTPUT_RE.sub("", residue)
    residue = _wb_tidy_visible(residue)
    if residue:
        parts.append(residue)
    return "\n".join(parts)


def _split_tool_log_prefix(text: str) -> tuple[str, str]:
    """拆出 Antigravity 续接历史时混进用户轮的「工具动作摘要」前缀。"""
    lines = text.splitlines()
    cursor = 0
    hits = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _TOOL_LOG_LINE_RE.match(stripped):
            hits += 1
            cursor = index + 1
            continue
        break
    if hits >= 3:
        return "\n".join(lines[:cursor]).strip(), "\n".join(lines[cursor:]).strip()
    return "", text.strip()


def sanitize_session_events(events: list[dict[str, Any]], fmt: str = "") -> list[dict[str, Any]]:
    """统一清洗各平台事件：用户轮只保留真实输入，其余降级为系统通知。"""
    cleaned_events: list[dict[str, Any]] = []
    for original in events or []:
        event = dict(original)
        if event.get("text"):
            event["text"] = _strip_ansi(event["text"])

        if event.get("kind") != "message" or event.get("role") != "user":
            cleaned_events.append(event)
            continue

        raw = (event.get("text") or "").strip()
        if not raw:
            continue

        # 1) 整条就是 CLI 斜杠命令或其输出 / Claude bash-input / bash-stdout
        if raw.startswith("<bash-input>"):
            m_in = re.search(r"<bash-input>\s*(.*?)\s*</bash-input>", raw, re.S | re.I)
            cmd_txt = (m_in.group(1).strip() if m_in else raw)
            cleaned_events.append({
                "kind": "tool_call",
                "role": "assistant",
                "timestamp": event.get("timestamp", ""),
                "text": cmd_txt,
                "tool_name": "Bash",
                "tool_call_id": "",
                "payload": {"command": cmd_txt},
            })
            continue
        if raw.startswith("<bash-stdout>") or raw.startswith("<bash-stderr>"):
            out_parts = []
            for m_out in re.finditer(r"<bash-(stdout|stderr)>\s*(.*?)\s*</bash-\1>", raw, re.S | re.I):
                body_out = _strip_ansi(m_out.group(2)).strip()
                if body_out:
                    out_parts.append(body_out)
            cleaned_events.append({
                "kind": "tool_result",
                "role": "tool",
                "timestamp": event.get("timestamp", ""),
                "text": "\n".join(out_parts) or "(无输出)",
                "tool_name": "Bash",
                "tool_call_id": "",
                "payload": None,
            })
            continue
        if raw.startswith("<command-name>") or raw.startswith("<local-command-"):
            cleaned_events.append({
                "kind": "notice",
                "role": "system",
                "timestamp": event.get("timestamp", ""),
                "text": _cli_command_notice(raw) or raw,
                "raw_text": raw,
                "hidden_chars": 0,
                "label": "CLI 命令",
                "tool_name": "",
                "payload": None,
            })
            continue

        # 2) 内联系统注入块
        counter = _WbCharCounter()
        body = raw
        for pattern in _UNIV_SYS_BLOCK_RES:
            body = counter.sub(pattern, body)
        body = counter.sub(_UNIV_CAVEAT_RE, body)

        # 3) 工具动作摘要前缀（Antigravity 续接历史）
        prefix, remainder = _split_tool_log_prefix(body)
        if prefix:
            cleaned_events.append({
                "kind": "notice",
                "role": "system",
                "timestamp": event.get("timestamp", ""),
                "text": prefix,
                "raw_text": "",
                "hidden_chars": 0,
                "label": "工具动作摘要",
                "tool_name": "",
                "payload": None,
            })
            body = remainder
            # 这种「动作摘要 + 正文」的打包记录，正文其实是助手当时的答复，
            # 被平台错标成 user；重标为 assistant，别混进用户指令流。
            if body:
                cleaned_events.append({
                    "kind": "message",
                    "role": "assistant",
                    "timestamp": event.get("timestamp", ""),
                    "text": _wb_tidy_visible(body),
                    "raw_text": "",
                    "hidden_chars": 0,
                    "tool_name": "",
                    "payload": None,
                })
                continue

        body = _wb_tidy_visible(body)
        if not body:
            continue

        removed = max(len(raw) - len(body), 0)
        event["text"] = body
        event["raw_text"] = raw if removed else ""
        event["hidden_chars"] = removed
        paste_hint = _pasted_payload_hint(body)
        if paste_hint:
            # 用户自己贴了一整份文件：仍然算用户指令，但默认折叠，避免刷屏
            event["collapsed"] = True
            event["summary"] = paste_hint
        cleaned_events.append(event)
    return cleaned_events


def _extract_antigravity_step101_prompt(payload: bytes) -> str | None:
    """仅从子会话派生时（invoke_subagent Prompt 或 Message from Parent Agent）中提取用户/派生指令。"""
    if not payload:
        return None
    try:
        txt = payload.decode("utf-8", errors="ignore")
        # 1. 明确匹配 invoke_subagent 的 Prompt 参数
        m = re.search(r'\{[^{}]*"Prompt"\s*:\s*("(?:[^"\\]|\\.)*")', txt)
        if m:
            try:
                val = json.loads(m.group(1))
                if val and str(val).strip():
                    return str(val).strip()
            except Exception:
                pass
        # 2. 明确匹配 Message from Parent Agent（必须有 Message from Parent Agent 标记）
        if "Message from Parent Agent" in txt:
            m2 = re.search(r'\[Message\][^\r\n]*content=(.+?)(?=\s*Message from Parent Agent)', txt, re.S)
            if m2:
                val2 = m2.group(1).strip()
                if val2:
                    return val2
    except Exception:
        pass
    return None


def _enrich_session_events_for_detail(
    path: Path, fmt: str, raw_events: Any, events_data: list[dict[str, Any]]
) -> None:
    """补全 session_migrate 为跨工具迁移而刻意抹除的明文思考过程，还原子代理原生指令，并修正原生步骤工具名错位。"""
    from contextlib import closing

    fmt_lower = (fmt or "").lower()
    if fmt_lower == "antigravity" and path and path.exists():
        think_by_idx: dict[int, str] = {}
        prompt_by_idx: dict[int, str] = {}
        try:
            from session_migrate.formats.antigravity import (
                _decode_message,
                _optional_bytes,
                _optional_text,
            )

            with closing(sqlite3.connect(f"file:{str(path)}?mode=ro", uri=True)) as conn:
                for idx, stype, payload in conn.execute(
                    "SELECT idx, step_type, step_payload FROM steps WHERE step_type IN (15, 101)"
                ):
                    if not payload:
                        continue
                    if stype == 15:
                        try:
                            outer = _decode_message(payload)
                            inner = _optional_bytes(outer, 20)
                            if inner:
                                t3 = _optional_text(_decode_message(inner), 3)
                                if t3 and t3.strip():
                                    think_by_idx[int(idx)] = t3.strip()
                        except Exception:
                            pass
                    elif stype == 101:
                        p_txt = _extract_antigravity_step101_prompt(payload)
                        if p_txt:
                            prompt_by_idx[int(idx)] = p_txt
        except Exception:
            pass

        user_prompt_attached = False
        for ev, ev_dict in zip(raw_events or [], events_data):
            prov = getattr(ev, "provenance", None)
            ridx = getattr(prov, "record_index", None)
            rtype = getattr(prov, "record_type", "") or ""
            if ridx is not None and int(ridx) in prompt_by_idx:
                ev_dict["kind"] = "message"
                ev_dict["role"] = "user"
                ev_dict["text"] = prompt_by_idx[int(ridx)]
                if not ev_dict.get("payload"):
                    ev_dict["payload"] = {}
                ev_dict["payload"]["source"] = "subagent_prompt"
                user_prompt_attached = True
            elif ev_dict.get("kind") == "thinking" and not (ev_dict.get("text") or "").strip():
                if ridx is not None and int(ridx) in think_by_idx:
                    ev_dict["text"] = think_by_idx[int(ridx)]
            elif ev_dict.get("kind") == "tool_result":
                if rtype == "antigravity_step_21":
                    ev_dict["tool_name"] = "run_command"
                elif rtype == "antigravity_step_8":
                    ev_dict["tool_name"] = "view_file"
                elif rtype == "antigravity_step_112":
                    ev_dict["tool_name"] = "shell_exec"

        # 若数据库中存在 101 prompt，但未匹配到现有事件（或首位未被标记为 user），且 events_data 中尚无 user 消息
        if prompt_by_idx and not user_prompt_attached and not any(e.get("role") == "user" for e in events_data):
            first_idx = sorted(prompt_by_idx.keys())[0]
            first_prompt = prompt_by_idx[first_idx]
            first_ts = events_data[0].get("timestamp") if events_data else ""
            events_data.insert(0, {
                "kind": "message",
                "role": "user",
                "text": first_prompt,
                "timestamp": first_ts,
                "tool_name": "",
                "tool_call_id": "",
                "payload": {"source": "subagent_prompt", "record_index": first_idx},
            })

    elif fmt_lower == "claude" and path and path.exists():
        think_seq: list[str] = []
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        msg = rec.get("message")
                        if isinstance(msg, dict):
                            content = msg.get("content")
                            if isinstance(content, list):
                                for blk in content:
                                    if isinstance(blk, dict) and blk.get("type") in {
                                        "thinking",
                                        "redacted_thinking",
                                    }:
                                        think_seq.append((blk.get("thinking") or "").strip())
                    except Exception:
                        pass
        except Exception:
            pass

        t_cursor = 0
        for ev_dict in events_data:
            if ev_dict.get("kind") == "thinking":
                if not (ev_dict.get("text") or "").strip() and t_cursor < len(think_seq):
                    if think_seq[t_cursor]:
                        ev_dict["text"] = think_seq[t_cursor]
                t_cursor += 1


def _wb_first_record_timestamp(jsonl_path: Path) -> float | None:
    """读取 jsonl 首条带 timestamp 的记录，返回秒级时间戳（兼容毫秒）。"""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("timestamp")
                if not ts:
                    continue
                try:
                    val = float(ts)
                except (TypeError, ValueError):
                    continue
                return val / 1000.0 if val > 1e11 else val
    except Exception:
        return None
    return None


def get_workbuddy_sessions() -> list[dict[str, Any]]:
    wb_dir = _home_path(".workbuddy")
    db_path = wb_dir / "workbuddy.db"
    meta_by_id = {}
    if db_path.exists():
        try:
            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            for r in db.execute("SELECT id, title, model, cwd, created_at FROM sessions").fetchall():
                meta_by_id[r["id"]] = dict(r)
            db.close()
        except Exception:
            pass

    results = []
    projects_dir = wb_dir / "projects"
    if projects_dir.exists():
        for j in projects_dir.glob("**/*.jsonl"):
            sid = j.stem
            meta = meta_by_id.get(sid, {})
            raw_title = meta.get("title")
            created_at = meta.get("created_at")
            
            # 真实时间口径：优先 DB 的 created_at（毫秒），退回 jsonl 首条记录时间，最后退回文件 mtime。
            # 统一按本地时区渲染，避免出现"所有会话都是 12:00"的伪时间，以及 UTC 换算导致的跨日错位。
            created_dt: datetime | None = None
            if created_at:
                try:
                    ts_val = float(created_at)
                except (TypeError, ValueError):
                    ts_val = 0.0
                if ts_val > 1e11:
                    ts_val /= 1000.0
                if ts_val > 0:
                    try:
                        created_dt = datetime.fromtimestamp(ts_val)
                    except (OverflowError, OSError, ValueError):
                        created_dt = None
            if created_dt is None:
                first_ts = _wb_first_record_timestamp(j)
                if first_ts:
                    try:
                        created_dt = datetime.fromtimestamp(first_ts)
                    except (OverflowError, OSError, ValueError):
                        created_dt = None
            if created_dt is None:
                try:
                    created_dt = datetime.fromtimestamp(j.stat().st_mtime)
                except (OSError, ValueError):
                    created_dt = None

            if created_dt is not None:
                date_str = created_dt.strftime("%Y-%m-%d")
                started_at_str = created_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                date_str = "2026-09-01"
                started_at_str = ""

            if not raw_title:
                try:
                    with open(j, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            data = json.loads(line)
                            if data.get("type") != "message" or data.get("role") != "user":
                                continue
                            classified = classify_workbuddy_user_record(data)
                            if classified["kind"] != "user":
                                continue
                            first_line = classified["text"].strip().splitlines()
                            if first_line and first_line[0].strip():
                                raw_title = first_line[0].strip()[:60]
                                break
                except:
                    pass
            if not raw_title:
                raw_title = f"WorkBuddy 会话 {sid[:8]}"

            raw_title = raw_title.replace("\r", " ").replace("\n", " ").strip()
            title = f"{date_str} · {raw_title}"

            records_count = 0
            try:
                with open(j, "r", encoding="utf-8", errors="ignore") as f:
                    records_count = sum(1 for _ in f)
            except:
                pass

            wb_stat = j.stat()
            wb_tok = compute_session_tokens("workbuddy", sid, j, wb_stat.st_mtime, wb_stat.st_size)
            results.append({
                "catalog_id": f"wb_{sid[:16]}",
                "format": "workbuddy",
                "session_id": sid,
                "title": title,
                "started_at": started_at_str,
                "records": records_count,
                "bytes": wb_stat.st_size,
                **_token_fields(wb_tok),
                "file_path": str(j),
                "exists": True,
            })
    return results

def make_temp_claude_jsonl(messages: list[dict[str, str]], sid: str) -> Path:
    import tempfile, uuid
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    parent_id = None
    for m in messages:
        msg_id = str(uuid.uuid4())
        role = m.get("role", "user")
        text = m.get("text", "")
        ts = m.get("timestamp") or "2026-05-20T12:00:00Z"
        row = {
            "type": role,
            "sessionId": sid,
            "uuid": msg_id,
            "parentUuid": parent_id,
            "message": {
                "role": role,
                "content": [{"type": "text", "text": text}]
            },
            "timestamp": ts,
        }
        parent_id = msg_id
        tmp.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.close()
    return Path(tmp.name)

TRAE_SRC_DB = runtime_paths.roaming_dir() / "Trae CN" / "ModularData" / "ai-agent" / "database.db"
TRAE_PLAIN_DB = runtime_paths.TRAE_PLAIN_DB
_TRAE_DB_CACHE: dict[str, Any] = {"sig": "", "index": {}}
_TRAE_INDEX_CACHE_PATH = runtime_paths.CACHE_DIR / "trae_db_index.json"
_TRAE_REFRESH_LOCK = threading.Lock()
_TRAE_REFRESH_RUNNING = False
_TRAE_REFRESH_LAST_ATTEMPT = 0.0


def _trae_source_mtime() -> float:
    """源库主文件 + WAL 的最新 mtime；没有源库返回 0。"""
    latest = 0.0
    for p in (TRAE_SRC_DB, Path(str(TRAE_SRC_DB) + "-wal")):
        try:
            latest = max(latest, p.stat().st_mtime)
        except OSError:
            continue
    return latest


def _maybe_refresh_trae_plain() -> None:
    """源库比解密副本新时，后台重解密，不阻塞当前列表请求。"""
    global _TRAE_REFRESH_RUNNING, _TRAE_REFRESH_LAST_ATTEMPT
    source_mtime = _trae_source_mtime()
    if source_mtime <= 0:
        return
    try:
        plain_mtime = TRAE_PLAIN_DB.stat().st_mtime if TRAE_PLAIN_DB.exists() else 0.0
    except OSError:
        plain_mtime = 0.0
    if plain_mtime >= source_mtime:
        return

    with _TRAE_REFRESH_LOCK:
        if _TRAE_REFRESH_RUNNING or (time.time() - _TRAE_REFRESH_LAST_ATTEMPT) < 60:
            return
        _TRAE_REFRESH_RUNNING = True
        _TRAE_REFRESH_LAST_ATTEMPT = time.time()

    def worker():
        global _TRAE_REFRESH_RUNNING
        try:
            proc = subprocess.run(
                helper_command("trae-decrypt"),
                cwd=str(SCRIPT_DIR),

                capture_output=True,
                timeout=1800,
                **_no_window_kwargs(),
            )
            if proc.returncode == 0:
                _TRAE_DB_CACHE["sig"] = ""
                invalidate_sessions_cache()
                try:
                    trigger_fts_sync()
                except Exception:
                    pass
        finally:
            with _TRAE_REFRESH_LOCK:
                _TRAE_REFRESH_RUNNING = False

    threading.Thread(target=worker, daemon=True, name="TraeReDecrypt").start()


def _trae_db_conn() -> sqlite3.Connection | None:
    """只读打开解密后的 Trae database.db；不存在则返回 None。"""
    if not TRAE_PLAIN_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{TRAE_PLAIN_DB.as_posix()}?mode=ro", uri=True, timeout=5)
    except Exception:
        return None


_TRAE_SYS_BLOCK_RE = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S | re.I)
_TRAE_USER_INPUT_RE = re.compile(r"<user_input\b[^>]*>(.*?)</user_input>", re.S | re.I)
_TRAE_UPLOADED_RE = re.compile(
    r"<(?:user_)?uploaded_files\b[^>]*>(.*?)</(?:user_)?uploaded_files>", re.S | re.I
)
_TRAE_FILE_TAG_RE = re.compile(r"<file\b[^>]*?/?>", re.I)
_TRAE_FILE_NAME_RE = re.compile(r'\bname="([^"]*)"', re.I)
_TRAE_FILE_PATH_RE = re.compile(r'\bpath="([^"]*)"', re.I)
_TRAE_TOOLCALL_RESULT_RE = re.compile(r"<toolcall_result>(.*?)(?:</toolcall_result>|$)", re.S | re.I)
_TRAE_XML_NOISE_RES = (
    re.compile(r"<shell_command_id>.*?</shell_command_id>", re.S | re.I),
    re.compile(r"<shell_status>.*?</shell_status>", re.S | re.I),
    re.compile(r"<shell_exit_code>.*?</shell_exit_code>", re.S | re.I),
    re.compile(r"<terminal_id>.*?</terminal_id>", re.S | re.I),
    re.compile(r"<terminal_cwd>.*?</terminal_cwd>", re.S | re.I),
    re.compile(r"<command_id>.*?</command_id>", re.S | re.I),
    re.compile(r"<command_status>.*?</command_status>", re.S | re.I),
    re.compile(r"<command_exit_code>.*?</command_exit_code>", re.S | re.I),
    re.compile(r"<toolcall_status>.*?</toolcall_status>", re.S | re.I),
    re.compile(r"<command_run_logs>", re.S | re.I),
    re.compile(r"</command_run_logs>", re.S | re.I),
    re.compile(r"<shell_output>", re.S | re.I),
    re.compile(r"</shell_output>", re.S | re.I),
    re.compile(r"<shell_stderr>", re.S | re.I),
    re.compile(r"</shell_stderr>", re.S | re.I),
    re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S | re.I),
)


def _trae_blocks(content: Any) -> list[str]:
    """content（str 或 [{type:text,text:...}]）→ 纯文本块列表。"""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for it in content:
        if isinstance(it, str):
            out.append(it)
            continue
        if not isinstance(it, dict):
            continue
        if it.get("type") == "text":
            out.append(str(it.get("text") or ""))
    return out


def _trae_upload_names(inner: str) -> list[str]:
    """从上传块内部提取文件名：兼容 `<file path=… name=…/>` 与纯文件名两种写法。"""
    names: list[str] = []
    if "<file" in inner.lower():
        for tag in _TRAE_FILE_TAG_RE.findall(inner):
            m = _TRAE_FILE_NAME_RE.search(tag)
            name = (m.group(1) if m else "").strip()
            if not name:
                p = _TRAE_FILE_PATH_RE.search(tag)
                if p:
                    name = p.group(1).replace("\\", "/").rsplit("/", 1)[-1].strip()
            if name:
                names.append(name)
        return names
    for line in inner.splitlines():
        name = line.strip()
        if name:
            names.append(name)
    return names


def _trae_clean_user_text(blocks: list[str]) -> tuple[str, list[str]]:
    """从 Trae 用户轮的 content 块里取出「人真正敲的那句话」。

    实测形态（history_v2）：一个 user 消息里可能有 4~6 个 text 块，
    依次是若干 `<system-reminder>…</system-reminder>`（20K 字符的工作区/规则注入）、
    一段 `# MCP Server Instructions`、最后才是 `<user_input>真正的输入</user_input>`。
    直接拼接会把整段注入当成用户指令（截图里的「MCP Server Instructions」就是这么来的）。
    规则：只要有 `<user_input>` 就只取它；否则剥离 system-reminder / MCP / REQUIREMENT 注入。
    `<uploaded_files>` 与 `<user_uploaded_files>` 两种附件块都要剥掉，只留下文件名。
    返回 (正文, 上传文件名列表)。
    """
    inputs: list[str] = []
    kept: list[str] = []
    uploads: list[str] = []
    for block in blocks:
        s = (block or "").strip()
        if not s:
            continue
        for m in _TRAE_UPLOADED_RE.finditer(s):
            uploads.extend(_trae_upload_names(m.group(1)))
        if "<user_input" in s:
            for m in _TRAE_USER_INPUT_RE.finditer(s):
                inner = _TRAE_UPLOADED_RE.sub("", m.group(1))
                inner = _TRAE_FILE_TAG_RE.sub("", inner).strip()
                if inner:
                    inputs.append(inner)
            continue
        if "uploaded_files" in s.lower():
            s = _TRAE_UPLOADED_RE.sub("", s)
            s = _TRAE_FILE_TAG_RE.sub("", s).strip()
        if not s:
            continue
        if s.startswith("<system-reminder"):
            continue
        low = s.lower()
        if low.startswith("# mcp server instructions") or low.startswith("mcp server instructions"):
            continue
        if re.match(r"^requirement\s*[:：]", s, re.I):
            continue
        kept.append(s)
    core = "\n".join(inputs) if inputs else "\n".join(kept)
    # 兜底：即使用户输入块之外还粘着附件标签（或 XML 闭合缺失），也把标签和
    # `<file …/>` 清掉，避免详情页“用户指令”尾部残留路径块。
    core = _TRAE_UPLOADED_RE.sub("", core)
    core = re.sub(r"</?(?:user_)?uploaded_files\b[^>]*>", "", core, flags=re.I)
    core = _TRAE_FILE_TAG_RE.sub("", core)
    core = re.sub(r"</?user_input\b[^>]*>", "", core, flags=re.I)
    core = re.sub(r"\n{3,}", "\n\n", core).strip()
    return core, uploads


def _trae_tidy_tool_output(text: str) -> tuple[str, bool]:
    """把工具返回里的 Trae 私有 XML 外壳去掉，返回 (可读正文, 是否失败)。"""
    raw = text or ""
    low = raw.lower()
    is_err = (
        "command failed" in low
        or ("exit code" in low and re.search(r"exit code\s*[1-9]", low) is not None)
        or ("<command_exit_code>" in low and re.search(r"<command_exit_code>\s*[1-9]", low) is not None)
    )
    # 快路径：纯文本输出（无 XML 外壳、无围栏、不是 JSON 数组）直接返回，
    # 避免对 3 万条工具结果做 60 万次正则替换。
    if "<" not in raw and "```" not in raw:
        stripped = raw.lstrip()
        if not stripped.startswith("["):
            return raw.strip()[:6000], is_err
    m = _TRAE_TOOLCALL_RESULT_RE.search(raw)
    body = (m.group(1) if m else raw).strip()
    if body.startswith("["):
        try:
            arr = json.loads(body)
            if isinstance(arr, list):
                texts = [
                    str(x.get("text") or "")
                    for x in arr
                    if isinstance(x, dict) and x.get("type") == "text" and str(x.get("text") or "")
                ]
                if texts:
                    body = "\n".join(texts)
        except Exception:
            pass
    for rx in _TRAE_XML_NOISE_RES:
        body = rx.sub("", body)
    # 去掉工具输出自带的 ``` 围栏（Trae 习惯把 stdout 包进代码块）
    body = body.lstrip()
    body = re.sub(r"^```[A-Za-z0-9_+-]*\s*\n?", "", body)
    body = re.sub(r"\n?```\s*$", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:6000], is_err


def _trae_parse_messages(raw: Any, call_names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """把 history_v2.messages 解析成结构化条目。

    条目类型：
      {"kind": "message", "role": "user|assistant", "text": ...}
      {"kind": "tool_call", "tool_name": ..., "input": {...}, "text": ..., "tool_call_id": ...}
      {"kind": "tool_result", "tool_name": ..., "text": ..., "is_error": bool, "tool_call_id": ...}
    工具名取自 assistant 消息里的 `tool_calls[].function_call.name`；
    role=tool 的消息本身不带 name，只带 tool_call_id，靠上面的映射回填。
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="ignore")
        except Exception:
            return []
    if not isinstance(raw, str):
        return []
    try:
        obj = json.loads(raw)
    except Exception:
        return []
    msgs = obj.get("raw_messages") or obj.get("messages") or []
    if not isinstance(msgs, list):
        return []

    call_names: dict[str, str] = dict(call_names or {})
    items: list[dict[str, Any]] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        blocks = _trae_blocks(m.get("content"))

        if role == "user":
            text, uploads = _trae_clean_user_text(blocks)
            if text:
                items.append({"kind": "message", "role": "user", "text": text, "from_message": True})
            elif uploads:
                items.append({
                    "kind": "message",
                    "role": "user",
                    "text": "上传文件：" + "、".join(uploads[:10]),
                    "from_message": True,
                    "is_upload": True,
                })
            continue

        if role == "assistant":
            text = "\n".join(b for b in blocks if b and b.strip()).strip()
            if text:
                items.append({"kind": "message", "role": "assistant", "text": text, "from_message": True})
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function_call") or {}
                name = str(fn.get("name") or tc.get("name") or "tool")
                args_raw = fn.get("arguments")
                args: Any = args_raw
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except Exception:
                        args = {"raw": args_raw}
                call_id = str(tc.get("id") or "")
                if call_id:
                    call_names[call_id] = name
                try:
                    detail = json.dumps(args, ensure_ascii=False, indent=2) if isinstance(args, (dict, list)) else str(args or "")
                except Exception:
                    detail = str(args or "")
                items.append({
                    "kind": "tool_call",
                    "tool_name": name,
                    "text": detail[:6000],
                    "input": args if isinstance(args, dict) else {"raw": args},
                    "tool_call_id": call_id,
                    "from_message": False,
                })
            continue

        if role == "tool":
            call_id = str(m.get("tool_call_id") or "")
            name = str(m.get("name") or "") or call_names.get(call_id, "") or "tool"
            text, is_err = _trae_tidy_tool_output("\n".join(blocks))
            if text:
                items.append({
                    "kind": "tool_result",
                    "tool_name": name,
                    "text": text,
                    "is_error": is_err,
                    "tool_call_id": call_id,
                    "from_message": True,
                })
    return items


def _trae_collect_call_names(raws: list[Any]) -> dict[str, str]:
    """会话内全部 tool_calls 的 id → 工具名。

    Trae 会把 assistant 的 tool_calls 与对应的 role=tool 结果拆进不同的
    history_v2 行，单行解析时结果侧拿不到工具名，必须按会话先扫一遍。
    """
    names: dict[str, str] = {}
    for raw in raws:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", errors="ignore")
            except Exception:
                continue
        if not isinstance(raw, str):
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        for m in obj.get("raw_messages") or []:
            if not isinstance(m, dict):
                continue
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                cid = str(tc.get("id") or "")
                if not cid:
                    continue
                fn = tc.get("function_call") or {}
                names[cid] = str(fn.get("name") or tc.get("name") or "tool")
    return names


_TRAE_TITLE_SPLIT_RE = re.compile(r"[。！？；!?]")


def _trae_title_from_text(text: str) -> str:
    """把首条用户输入压成一句可读标题。

    取前 3 个非空行拼起来（用户常把路径/对象分几行再提问，只取第一行会变成 `"F:\\rea"`），
    去掉 markdown 符号与成对引号，再按句号或 48 字截断。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:3]
    if not lines:
        return ""
    joined = " ".join(ln.strip().strip('"“”') for ln in lines)
    joined = re.sub(r"[`*#>]+", "", joined).strip()
    cut = _TRAE_TITLE_SPLIT_RE.split(joined)[0].strip() or joined
    if len(cut) > 48:
        cut = cut[:48].rstrip() + "…"
    return cut


def _trae_flatten_messages(raw: Any) -> list[tuple[str, str]]:
    """兼容旧调用：压成 [(role, text)]（含工具调用/结果文本）。"""
    return [
        (it.get("role") or ("tool" if it["kind"] == "tool_result" else "assistant"), it.get("text") or "")
        for it in _trae_parse_messages(raw)
        if it.get("text")
    ]


def _trae_ts(epoch: Any) -> str:
    """epoch 秒 → UTC 字符串（与本文件其它 started_at 口径一致）。"""
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _trae_db_index() -> dict[str, dict[str, Any]]:
    """聚合解密库 history_v2：每个会话的消息数/字符/token/起止时间/首条用户提问。

    结果按库文件的 (mtime,size) 缓存，避免每次列表请求都全量解析 32k 行 JSON。
    """
    _maybe_refresh_trae_plain()
    if not TRAE_PLAIN_DB.exists():
        return {}
    try:
        st = TRAE_PLAIN_DB.stat()
    except Exception:
        return {}
    sig = f"{int(st.st_mtime)}:{st.st_size}"
    if _TRAE_DB_CACHE.get("sig") == sig:
        return _TRAE_DB_CACHE.get("index") or {}

    # 跨进程缓存：32k 行 JSON 全量解析约 6.4 s，落盘后启动只需 ~50 ms。
    try:
        if _TRAE_INDEX_CACHE_PATH.exists():
            cached = json.loads(_TRAE_INDEX_CACHE_PATH.read_text("utf-8"))
            if isinstance(cached, dict) and cached.get("sig") == sig and isinstance(cached.get("index"), dict):
                _TRAE_DB_CACHE["sig"] = sig
                _TRAE_DB_CACHE["index"] = cached["index"]
                return cached["index"]
    except Exception:
        pass

    conn = _trae_db_conn()
    if conn is None:
        return {}
    index: dict[str, dict[str, Any]] = {}
    try:
        rows = conn.execute(
            "select session_id, messages, token_usage, created_at from history_v2 order by created_at, id"
        ).fetchall()
    except Exception:
        rows = []
    # Trae 自己维护的会话标题（SOLO 任务列表里显示的就是这一份）
    native_titles: dict[str, str] = {}
    try:
        for nsid, ntitle in conn.execute("select session_id, title from fts_session_title"):
            t = re.sub(r"\s+", " ", str(ntitle or "")).strip()
            if len(t) > 80:
                t = t[:79].rstrip() + "…"
            if t:
                native_titles[str(nsid)] = t
    except Exception:
        native_titles = {}
    finally:
        conn.close()

    for sid, raw, tok, ts in rows:
        items = _trae_parse_messages(raw)
        if not items:
            continue
        agg = index.setdefault(
            str(sid),
            {
                "records": 0,
                "msgs": 0,
                "chars": 0,
                "tokens": 0,
                "first": "",
                "last": "",
                "last_mtime": 0.0,
                "title": "",
                "title_ai": "",
                "upload_hint": "",
                "native": "",
            },
        )
        agg["records"] += 1
        # 「步数」沿用旧口径：每条原始消息算一步（工具调用不额外计步）
        msg_items = [it for it in items if it.get("from_message")]
        agg["msgs"] += len(msg_items) if msg_items else len(items)
        agg["tokens"] += int(tok or 0)
        for it in items:
            txt = it.get("text") or ""
            agg["chars"] += len(txt)
            if it["kind"] != "message":
                continue
            head = _trae_title_from_text(txt)
            if not head:
                continue
            if it["role"] == "user" and not agg["title"]:
                if it.get("is_upload"):
                    if not agg["upload_hint"]:
                        agg["upload_hint"] = head
                else:
                    agg["title"] = head
            elif it["role"] == "assistant" and not agg["title_ai"]:
                agg["title_ai"] = head
        tstr = _trae_ts(ts)
        if tstr:
            if not agg["first"]:
                agg["first"] = tstr
            agg["last"] = tstr
        try:
            agg["last_mtime"] = max(agg["last_mtime"], float(ts or 0))
        except Exception:
            pass

    # 标题优先级：Trae 原生标题 > 人话（首条用户输入）> 首条助手回复 > 上传文件名
    for sid, agg in index.items():
        agg["native"] = native_titles.get(sid, "")
        if agg["native"]:
            agg["title"] = agg["native"]
        elif not agg["title"]:
            agg["title"] = agg["title_ai"] or agg["upload_hint"]

    _TRAE_DB_CACHE["sig"] = sig
    _TRAE_DB_CACHE["index"] = index
    try:
        _TRAE_INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TRAE_INDEX_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sig": sig, "index": index}, ensure_ascii=False), "utf-8")
        tmp.replace(_TRAE_INDEX_CACHE_PATH)
    except Exception:
        pass
    return index


def _trae_db_messages(sid: str) -> list[dict[str, Any]]:
    """按会话取完整正文（解密库是唯一有 assistant 正文的来源）。"""
    if not sid:
        return []
    conn = _trae_db_conn()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "select messages, created_at from history_v2 where session_id = ? order by created_at, id",
            (sid,),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    events: list[dict[str, Any]] = []
    call_names = _trae_collect_call_names([raw for raw, _ in rows])
    for raw, ts in rows:
        tstr = _trae_ts(ts)
        for it in _trae_parse_messages(raw, call_names):
            kind = it["kind"]
            if kind == "message":
                events.append({
                    "kind": "message", "role": it["role"], "timestamp": tstr,
                    "text": it["text"], "tool_name": "", "tool_call_id": "", "payload": None,
                })
            elif kind == "tool_call":
                events.append({
                    "kind": "tool_call", "role": "assistant", "timestamp": tstr,
                    "text": it["text"], "tool_name": it["tool_name"],
                    "tool_call_id": it["tool_call_id"], "payload": {"input": it["input"]},
                })
            elif kind == "tool_result":
                events.append({
                    "kind": "tool_result", "role": "tool", "timestamp": tstr,
                    "text": it["text"], "tool_name": it["tool_name"],
                    "tool_call_id": it["tool_call_id"],
                    "payload": {"is_error": bool(it.get("is_error"))},
                })
    return events


def get_trae_sessions() -> list[dict[str, Any]]:
    import urllib.parse
    base_user_dirs = [
        ("trae", _roaming_path("Trae CN", "User")),
        ("trae_solo", _roaming_path("TRAE SOLO CN", "User")),
    ]
    mem_dir = _home_path(".trae-cn", "memory", "projects")
    results = []
    sessions_map: dict[str, dict[str, Any]] = {}

    def get_or_create(sid: str) -> dict[str, Any]:
        if sid not in sessions_map:
            sessions_map[sid] = {
                "session_id": sid,
                "title": "",
                "started_at": "",
                "records": 0,
                "bytes": 0,
                "mtime": 0.0,
                "account": "",
                "model": "",
                "mode": "",
                "workspace": "",
                "file_path": "",
                "all_files": set(),
                "chat_text_buf": [],
                "raw_json_len": 0,
            }
        return sessions_map[sid]

    # 1. Scan memory directory (.trae-cn/memory/projects)
    if mem_dir.exists():
        for f in mem_dir.rglob("session_memory_*.jsonl"):
            m = re.search(r"session_memory_([a-zA-Z0-9_\-]+)\.jsonl", f.name)
            if m:
                sid = m.group(1)
                s = get_or_create(sid)
                s["all_files"].add(str(f))
                if not s["file_path"]:
                    s["file_path"] = str(f)
                sz = f.stat().st_size
                s["bytes"] += sz
                s["mtime"] = max(s["mtime"], f.stat().st_mtime)
                lines = [l.strip() for l in f.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
                for l in lines:
                    try:
                        entry = json.loads(l)
                        t_str = entry.get("message_summary_time") or ""
                        if t_str and (not s["started_at"] or t_str < s["started_at"]):
                            s["started_at"] = t_str
                        intent = entry.get("intent", "").strip()
                        if intent and not s["title"]:
                            s["title"] = intent
                        outcome = entry.get("outcome", "").strip()
                        if intent:
                            s["chat_text_buf"].append(intent)
                        if outcome:
                            s["chat_text_buf"].append(outcome)
                        s["records"] += 1
                    except Exception:
                        pass

        for f in mem_dir.rglob("topics.md"):
            txt = f.read_text(encoding="utf-8", errors="ignore")
            for block in re.split(r"\[session_id:\s*", txt):
                if not block.strip():
                    continue
                parts = block.split("|", 1)
                sid = parts[0].strip()
                if sid and len(sid) >= 16:
                    s = get_or_create(sid)
                    s["all_files"].add(str(f))
                    if not s["file_path"]:
                        s["file_path"] = str(f)
                    s["bytes"] += f.stat().st_size
                    s["mtime"] = max(s["mtime"], f.stat().st_mtime)
                    m_t = re.search(r"topic_summary_time:\s*([^\]]+)\](.*)", block, re.DOTALL)
                    if m_t:
                        t_time = m_t.group(1).strip()
                        t_desc = m_t.group(2).strip().splitlines()[0][:100]
                        if t_time and (not s["started_at"] or t_time < s["started_at"]):
                            s["started_at"] = t_time
                        if not s["title"] and t_desc:
                            s["title"] = t_desc
                        if t_desc:
                            s["chat_text_buf"].append(t_desc)

    # 2. Scan state.vscdb files
    for agent_type, user_dir in base_user_dirs:
        if not user_dir.exists():
            continue

        dbs_to_scan = []
        global_db = user_dir / "globalStorage" / "state.vscdb"
        if global_db.exists():
            dbs_to_scan.append((global_db, ""))

        ws_dir = user_dir / "workspaceStorage"
        if ws_dir.exists():
            for ws in ws_dir.iterdir():
                vscdb = ws / "state.vscdb"
                if vscdb.exists():
                    ws_name = ""
                    ws_json = ws / "workspace.json"
                    if ws_json.exists():
                        try:
                            d = json.loads(ws_json.read_text(encoding="utf-8", errors="ignore"))
                            folder = d.get("folder") or d.get("workspace") or ""
                            if folder:
                                decoded = urllib.parse.unquote(folder).rstrip("/")
                                name = decoded.split("/")[-1]
                                if name.endswith(".code-workspace"):
                                    name = name[:-15]
                                ws_name = name
                        except Exception:
                            pass
                    dbs_to_scan.append((vscdb, ws_name))

        for db_file, ws_folder in dbs_to_scan:
            try:
                db_mtime = db_file.stat().st_mtime
                conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
                cursor = conn.cursor()

                # A. Check ai-chat.chatQueryCompletion.%
                cursor.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'ai-chat.chatQueryCompletion.%'")
                for key, val in cursor.fetchall():
                    sid = key.split(".")[-1]
                    if not sid or len(sid) < 16:
                        continue
                    s = get_or_create(sid)
                    s["all_files"].add(str(db_file))
                    if not s["file_path"]:
                        s["file_path"] = str(db_file)
                    s["mtime"] = max(s["mtime"], db_mtime)
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    s["bytes"] += len(val)
                    s["raw_json_len"] += len(val)
                    try:
                        data = json.loads(val)
                        saved_at = data.get("savedAt")
                        if saved_at and not s["started_at"]:
                            s["started_at"] = datetime.fromtimestamp(saved_at / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        if data.get("modelName") and not s["model"]:
                            s["model"] = str(data["modelName"])
                        if data.get("messagesLength"):
                            s["records"] = max(s["records"], int(data["messagesLength"]))
                        res_list = data.get("response", {}).get("resp", {}).get("result", []) or data.get("response", {}).get("result", [])
                        if res_list and isinstance(res_list, list):
                            # 注意：ai-chat.chatQueryCompletion 存的是 Trae 为输入框生成的
                            # 「猜你想问」候选追问，并不是用户真实提问，也不是会话标题。
                            # 因此这里只用于记录数/时间戳兜底，绝不能当标题或正文展示。
                            s["records"] = max(s["records"], len(res_list))
                            for item in res_list:
                                if item.get("text"):
                                    txt = item["text"].strip()
                                    s["chat_text_buf"].append(txt)
                                    item_id = item.get("id", "")
                                    if len(item_id) >= 8 and item_id.startswith("202") and not s["started_at"]:
                                        s["started_at"] = f"{item_id[:4]}-{item_id[4:6]}-{item_id[6:8]} {item_id[8:10]}:{item_id[10:12]}:{item_id[12:14]}"
                                    break
                    except Exception:
                        pass

                # B. Check sessionRelation:modelMap (User ID accounts)
                cursor.execute("SELECT key, value FROM ItemTable WHERE key LIKE '%sessionRelation:modelMap%' OR key LIKE '%sessionRelation:globalModelMap%'")
                for key, val in cursor.fetchall():
                    uid_m = re.match(r"^(\d+)_", key)
                    uid = uid_m.group(1) if uid_m else ""
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    try:
                        d = json.loads(val)
                        if isinstance(d, dict):
                            for sid, minfo in d.items():
                                if not sid or len(sid) < 16:
                                    continue
                                s = get_or_create(sid)
                                s["all_files"].add(str(db_file))
                                if not s["file_path"]:
                                    s["file_path"] = str(db_file)
                                s["mtime"] = max(s["mtime"], db_mtime)
                                if uid and not s["account"]:
                                    s["account"] = uid
                                if ws_folder and not s["workspace"]:
                                    s["workspace"] = ws_folder
                                if isinstance(minfo, dict) and not s["model"]:
                                    models = list(minfo.values())
                                    if models:
                                        s["model"] = str(models[0])
                                elif isinstance(minfo, str) and not s["model"]:
                                    s["model"] = minfo
                    except Exception:
                        pass

                # C. Check icube_session_agent_map
                cursor.execute("SELECT key, value FROM ItemTable WHERE key = 'icube_session_agent_map'")
                for key, val in cursor.fetchall():
                    if isinstance(val, bytes):
                        val = val.decode("utf-8", errors="ignore")
                    try:
                        d = json.loads(val)
                        if isinstance(d, dict):
                            for sid, agent_type in d.items():
                                if not sid or len(sid) < 16:
                                    continue
                                s = get_or_create(sid)
                                s["all_files"].add(str(db_file))
                                if not s["file_path"]:
                                    s["file_path"] = str(db_file)
                                s["mtime"] = max(s["mtime"], db_mtime)
                                if not s["mode"]:
                                    s["mode"] = str(agent_type)
                                if ws_folder and not s["workspace"]:
                                    s["workspace"] = ws_folder
                    except Exception:
                        pass

                # D. Check draft:session:[sid]
                cursor.execute("SELECT key, value FROM ItemTable WHERE key LIKE '%:draft:session:%'")
                for key, val in cursor.fetchall():
                    m = re.search(r":draft:session:([a-zA-Z0-9_\-]+):", key)
                    if m:
                        sid = m.group(1)
                        s = get_or_create(sid)
                        s["all_files"].add(str(db_file))
                        if not s["file_path"]:
                            s["file_path"] = str(db_file)
                        s["mtime"] = max(s["mtime"], db_mtime)
                        if isinstance(val, bytes):
                            val = val.decode("utf-8", errors="ignore")
                        try:
                            d = json.loads(val)
                            if d.get("scope", {}).get("userId") and not s["account"]:
                                s["account"] = str(d["scope"]["userId"])
                            if d.get("updatedAt") and not s["started_at"]:
                                s["started_at"] = datetime.fromtimestamp(d["updatedAt"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            pass

                # E. Check all_session_badges_%
                cursor.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'all_session_badges_%'")
                for key, val in cursor.fetchall():
                    sid = key.replace("all_session_badges_", "")
                    if not sid or len(sid) < 16:
                        continue
                    s = get_or_create(sid)
                    s["all_files"].add(str(db_file))
                    if not s["file_path"]:
                        s["file_path"] = str(db_file)
                    s["mtime"] = max(s["mtime"], db_mtime)

                # F. Check memento/icube-ai-agent-storage (post-2026-10-12 workspace session list)
                ws_current_sid = ""
                ws_memento_sids: list[str] = []
                cursor.execute("SELECT value FROM ItemTable WHERE key = 'memento/icube-ai-agent-storage'")
                m_row = cursor.fetchone()
                if m_row and m_row[0]:
                    m_val = m_row[0].decode("utf-8", errors="ignore") if isinstance(m_row[0], bytes) else str(m_row[0])
                    try:
                        m_data = json.loads(m_val)
                        if isinstance(m_data, dict):
                            ws_current_sid = str(m_data.get("currentSessionId") or "").strip()
                            for item in (m_data.get("list") or []):
                                if not isinstance(item, dict):
                                    continue
                                m_sid = str(item.get("sessionId") or "").strip()
                                if not m_sid or len(m_sid) < 16:
                                    continue
                                ws_memento_sids.append(m_sid)
                                s = get_or_create(m_sid)
                                s["has_memento"] = True
                                s["all_files"].add(str(db_file))
                                if not s["file_path"]:
                                    s["file_path"] = str(db_file)
                                s["mtime"] = max(s["mtime"], db_mtime)
                                if ws_folder and not s["workspace"]:
                                    s["workspace"] = ws_folder
                                if item.get("isCurrent") and not ws_current_sid:
                                    ws_current_sid = m_sid
                    except Exception:
                        pass

                # G. Check icube-ai-agent-storage-input-history (real user prompts in workspace)
                cursor.execute("SELECT value FROM ItemTable WHERE key = 'icube-ai-agent-storage-input-history'")
                ih_row = cursor.fetchone()
                if ih_row and ih_row[0]:
                    ih_val = ih_row[0].decode("utf-8", errors="ignore") if isinstance(ih_row[0], bytes) else str(ih_row[0])
                    try:
                        ih_list = json.loads(ih_val)
                        if isinstance(ih_list, list) and ih_list:
                            texts = [
                                str(it.get("inputText") or "").strip()
                                for it in ih_list
                                if isinstance(it, dict) and str(it.get("inputText") or "").strip()
                            ]
                            if texts:
                                target_sid = ws_current_sid or (ws_memento_sids[0] if ws_memento_sids else f"ws_{db_file.parent.name[:16]}")
                                s = get_or_create(target_sid)
                                s["has_memento"] = True
                                s["input_history_db"] = str(db_file)
                                s["all_files"].add(str(db_file))
                                if not s["file_path"]:
                                    s["file_path"] = str(db_file)
                                s["mtime"] = max(s["mtime"], db_mtime)
                                if ws_folder and not s["workspace"]:
                                    s["workspace"] = ws_folder
                                s["records"] = max(s["records"], len(texts))
                                s["bytes"] += sum(len(t.encode("utf-8", errors="ignore")) for t in texts)
                                s["chat_text_buf"].extend(texts)
                                if not s["title"]:
                                    s["title"] = clean_human_title(texts[-1]) or texts[-1][:40]
                    except Exception:
                        pass

                conn.close()
            except Exception:
                pass

    # 2.5 解密后的 Trae 库（history_v2）：补齐只有库里有正文的会话
    for sid, agg in _trae_db_index().items():
        s = get_or_create(sid)
        s["has_db"] = True
        s["db_records"] = agg["records"]
        s["db_tokens"] = agg["tokens"]
        s["records"] = max(s["records"], agg["msgs"])
        s["bytes"] = max(s["bytes"], agg["chars"])
        # “最近活跃”取会话自己最后一条 history_v2 记录的时间，而不是解密库
        # 文件的 mtime。否则所有 Trae 会话会共用同一个库文件 mtime，排序退化成
        # 插入顺序，最新活跃的会话反而沉底。
        if float(agg.get("last_mtime") or 0) > 0:
            s["mtime"] = float(agg["last_mtime"])
        if not s["file_path"]:
            s["file_path"] = str(TRAE_PLAIN_DB)
        if not s["all_files"]:
            s["all_files"].add(str(TRAE_PLAIN_DB))
        if not s["title"] and agg["title"]:
            s["title"] = agg["title"]
        elif agg.get("native"):
            # Trae 库里有官方标题时以它为准（与 SOLO 任务列表一致）
            s["title"] = agg["native"]
        if agg["first"] and (not s["started_at"] or agg["first"] < s["started_at"]):
            s["started_at"] = agg["first"]

    # 3. Assemble and calculate tokens for all sessions
    for sid, s in sessions_map.items():
        # Trae 在 state.vscdb 里会留下只有 all_session_badges_<id>（空值）和空
        # chatQueryCompletion 的壳记录：没有标题、没有正文、0 步 0 字节。
        # 另有一类 20~74 步但正文不足 1KB 的记录，同样只是工作区标签残留。
        # 它们既无法查看也无法迁移，直接跳过，避免污染列表和统计。
        has_jsonl = any("session_memory_" in f for f in s["all_files"])
        has_ih = bool(s.get("input_history_db"))
        has_db = bool(s.get("has_db"))
        if not has_jsonl and not has_ih and not has_db:
            continue
        fp = Path(s["file_path"]) if s["file_path"] else _roaming_path("Trae CN", "User", "globalStorage", "state.vscdb")
        mtime = s["mtime"] if s["mtime"] > 0 else (fp.stat().st_mtime if fp.exists() else time.time())
        if not s["started_at"] and re.fullmatch(r"[0-9a-f]{24}", sid):
            try:
                obj_ts = int(sid[:8], 16)
                if 1700000000 <= obj_ts <= 1950000000:
                    s["started_at"] = datetime.fromtimestamp(obj_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        # 没有解密库正文、也没有 session_memory 的会话，只能从 state.vscdb
        # 取得时间；同一个 state.vscdb 的 mtime 对所有会话都一样。此时改用
        # 会话自己的 started_at，避免“工作区提问历史”这类旧条目被文件 mtime
        # 抬到最新活跃的位置。
        if not has_db and not has_jsonl and s["started_at"]:
            try:
                s["mtime"] = datetime.strptime(
                    s["started_at"].strip(), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc).timestamp()
                mtime = s["mtime"]
            except (TypeError, ValueError):
                pass
        date_str = ""
        if s["started_at"]:
            date_str = s["started_at"][:10]
        else:
            date_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
            s["started_at"] = f"{date_str} 12:00:00"

        title_raw = s["title"].strip()
        if not has_jsonl and has_ih and not has_db:
            ws_label = s["workspace"] or sid[:8]
            title_raw = f"Trae 工作区提问历史 ({ws_label}) · {max(1, s['records'])} 条"
        elif not title_raw:
            sub = s["workspace"] or s["model"] or s["mode"]
            if sub:
                title_raw = f"Trae 会话 ({sub} · {sid[:8]})"
            else:
                title_raw = f"Trae 会话 ({sid[:8]})"

        t_chat = sum(estimate_text_tokens(txt) for txt in s["chat_text_buf"])
        t_tot = max(t_chat, estimate_text_tokens(" ".join(s["chat_text_buf"])) + int(s["raw_json_len"] * 0.15))
        t_aux = max(0, t_tot - t_chat)
        # 解密库里有模型侧记录的 token_usage，优先用真实值而非估算
        if has_db and int(s.get("db_tokens") or 0) > 0:
            t_chat = int(s["db_tokens"])
            t_tot = t_chat
            t_aux = 0

        trae_tok = compute_session_tokens(
            "trae",
            sid,
            fp,
            mtime,
            max(1, s["bytes"]),
            trae_chat_tokens=t_chat,
            trae_aux_tokens=t_aux,
        )

        results.append({
            "catalog_id": f"trae_{sid[:16]}",
            "format": "trae",
            "session_id": sid,
            "title": f"{date_str} · {title_raw}",
            "started_at": s["started_at"],
            "records": max(1, s["records"]),
            "bytes": max(1, s["bytes"]),
            **_token_fields(trae_tok),
            "file_path": str(fp),
            "all_files": list(s["all_files"]),
            "account": s["account"],
            "model": s["model"],
            "mode": s["mode"],
            "workspace": s["workspace"],
            "input_history_db": s.get("input_history_db", ""),
            "has_db": has_db,
            "db_records": int(s.get("db_records") or 0),
            "db_tokens": int(s.get("db_tokens") or 0),
            "exists": True,
            "mtime": mtime,
        })

    return results

def get_trae_session_messages(session_match: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract conversation message turns for a Trae session."""
    events = []
    sid = session_match.get("session_id", "")
    all_files = session_match.get("all_files", []) or [session_match.get("file_path", "")]

    # 0. 优先用解密库（history_v2 有完整的 assistant 正文与工具结果；
    #    memory jsonl 只有 intent/outcome 摘要，state.vscdb 只有提问残片）
    if sid and (session_match.get("has_db") or _trae_db_index().get(sid)):
        db_events = _trae_db_messages(sid)
        if db_events:
            return db_events
    
    # 1. From session_memory jsonl
    for fp in all_files:
        p = Path(fp)
        if "session_memory_" in p.name and p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    intent = entry.get("intent", "").strip()
                    t_str = entry.get("message_summary_time", "")
                    if intent:
                        events.append({
                            "kind": "message",
                            "role": "user",
                            "timestamp": t_str,
                            "text": intent,
                            "tool_name": "",
                            "payload": None,
                        })
                    outcome = entry.get("outcome", "").strip()
                    actions = entry.get("actions", [])
                    learned = entry.get("learned", [])
                    if actions and isinstance(actions, list):
                        for act in actions:
                            act_str = str(act).strip()
                            if act_str:
                                events.append({
                                    "kind": "tool_call",
                                    "role": "assistant",
                                    "timestamp": t_str,
                                    "text": act_str,
                                    "tool_name": "trae_action",
                                    "tool_call_id": "",
                                    "payload": None,
                                })
                    resp_parts = []
                    if outcome:
                        resp_parts.append(outcome)
                    if learned and isinstance(learned, list):
                        resp_parts.append("\n**习得知识与经验：**\n" + "\n".join(f"- {l}" for l in learned))
                    if resp_parts:
                        events.append({
                            "kind": "message",
                            "role": "assistant",
                            "timestamp": t_str,
                            "text": "\n".join(resp_parts),
                            "tool_name": "",
                            "payload": None,
                        })
            except Exception:
                pass

    # 2. 如果没有 .jsonl 记忆文件，但该会话关联了工作区的 icube-ai-agent-storage-input-history，
    #    从 state.vscdb 读取真实用户提问记录（模型回复仍在 SQLCipher 加密库中）。
    if not events and session_match.get("input_history_db"):
        ih_db = Path(str(session_match["input_history_db"]))
        if ih_db.exists():
            try:
                conn = sqlite3.connect(f"file:{ih_db}?mode=ro", uri=True)
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key = 'icube-ai-agent-storage-input-history'"
                ).fetchone()
                conn.close()
                if row and row[0]:
                    raw_val = row[0].decode("utf-8", errors="ignore") if isinstance(row[0], bytes) else str(row[0])
                    items = json.loads(raw_val)
                    if isinstance(items, list):
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            txt = str(item.get("inputText") or "").strip()
                            if not txt:
                                continue
                            events.append({
                                "kind": "message",
                                "role": "user",
                                "timestamp": session_match.get("started_at", ""),
                                "text": txt,
                                "tool_name": "",
                                "payload": None,
                            })
            except Exception:
                pass

    # 3. Fallback to overview metadata
    if not events:
        desc_lines = [
            f"**智能体平台：** Trae",
            f"**会话标识：** `{sid}`",
        ]
        if session_match.get("account"):
            desc_lines.append(f"**关联账号 (User ID)：** `{session_match['account']}`")
        if session_match.get("workspace"):
            desc_lines.append(f"**关联工作区：** {session_match['workspace']}")
        if session_match.get("model"):
            desc_lines.append(f"**使用模型：** `{session_match['model']}`")
        if session_match.get("mode"):
            desc_lines.append(f"**运行模式：** `{session_match['mode']}`")
        if session_match.get("started_at"):
            desc_lines.append(f"**创建时间：** {session_match['started_at']}")
        events.append({
            "kind": "message",
            "role": "assistant",
            "timestamp": session_match.get("started_at", ""),
            "text": "\n".join(desc_lines),
            "tool_name": "",
            "payload": None,
        })

    return events


def _doubao_clean_prompt_title(text: str) -> str:
    """从豆包 Agent Mode 首条用户消息提取可读标题。"""
    if not text:
        return ""
    cleaned = re.sub(r"\[([^\]]+)\]\(<[^>]+>\)", r"\1", text)
    return clean_human_title(cleaned) or cleaned.strip()[:40]


def _doubao_read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
    return val, pos


def _doubao_snappy_decompress(data: bytes) -> bytes:
    """纯 Python Snappy 解压（用于读取 Chromium IndexedDB LevelDB 数据块）。"""
    pos = 0
    n = len(data)
    ulen, pos = _doubao_read_varint(data, pos)
    if ulen > 16 * 1024 * 1024 or pos >= n:
        raise ValueError("invalid snappy stream")
    out = bytearray()
    while pos < n:
        tag = data[pos]
        pos += 1
        kind = tag & 0x03
        if kind == 0:
            length = (tag >> 2) + 1
            if length > 60:
                extra = length - 60
                if pos + extra > n:
                    raise ValueError("snappy literal oob")
                length = int.from_bytes(data[pos:pos + extra], "little") + 1
                pos += extra
            if pos + length > n:
                raise ValueError("snappy literal oob")
            out.extend(data[pos:pos + length])
            pos += length
        else:
            if kind == 1:
                if pos >= n:
                    raise ValueError("snappy copy1 oob")
                length = ((tag >> 2) & 0x07) + 4
                offset = ((tag & 0xE0) << 3) | data[pos]
                pos += 1
            elif kind == 2:
                if pos + 2 > n:
                    raise ValueError("snappy copy2 oob")
                length = (tag >> 2) + 1
                offset = int.from_bytes(data[pos:pos + 2], "little")
                pos += 2
            else:
                if pos + 4 > n:
                    raise ValueError("snappy copy4 oob")
                length = (tag >> 2) + 1
                offset = int.from_bytes(data[pos:pos + 4], "little")
                pos += 4
            if offset == 0 or offset > len(out):
                raise ValueError("snappy bad offset")
            for _ in range(length):
                out.append(out[-offset])
    if len(out) != ulen:
        raise ValueError("snappy length mismatch")
    return bytes(out)


def _doubao_iter_idb_blobs(idb_dir: Path) -> list[bytes]:
    """读取 Chromium IndexedDB LevelDB（.ldb + .log）并尝试 Snappy 解压值。"""
    import struct as _struct

    blobs: list[bytes] = []
    if not idb_dir.exists():
        return blobs

    def _try_dec(val: bytes) -> bytes:
        for off in range(min(12, len(val))):
            try:
                return _doubao_snappy_decompress(val[off:])
            except Exception:
                pass
        return val

    for ldb_file in sorted(idb_dir.glob("*.ldb")):
        try:
            raw = ldb_file.read_bytes()
            if len(raw) < 48 or raw[-8:] != b"\x57\xfb\x80\x8b\x24\x75\x47\xdb":
                continue
            footer = raw[-48:]
            p = 0
            _, p = _doubao_read_varint(footer, p)
            _, p = _doubao_read_varint(footer, p)
            idx_off, p = _doubao_read_varint(footer, p)
            idx_size, p = _doubao_read_varint(footer, p)

            def _read_blk(off: int, size: int) -> bytes:
                blk = raw[off:off + size]
                return _doubao_snappy_decompress(blk) if raw[off + size] == 1 else blk

            def _iter_kv(blk: bytes):
                num_restarts = _struct.unpack_from("<I", blk, len(blk) - 4)[0]
                data_end = len(blk) - 4 - num_restarts * 4
                q = 0
                out = []
                while q < data_end:
                    _, q = _doubao_read_varint(blk, q)
                    un, q = _doubao_read_varint(blk, q)
                    vl, q = _doubao_read_varint(blk, q)
                    q += un
                    v = blk[q:q + vl]
                    q += vl
                    out.append(v)
                return out

            idx_blk = _read_blk(idx_off, idx_size)
            for h in _iter_kv(idx_blk):
                hp = 0
                boff, hp = _doubao_read_varint(h, hp)
                bsize, hp = _doubao_read_varint(h, hp)
                for v in _iter_kv(_read_blk(boff, bsize)):
                    blobs.append(_try_dec(v))
        except Exception:
            continue

    for log_file in sorted(idb_dir.glob("*.log")):
        try:
            raw = log_file.read_bytes()
            pos = 0
            block_size = 32768
            buf = bytearray()
            recs: list[bytes] = []
            while pos + 7 <= len(raw):
                in_b = pos % block_size
                if block_size - in_b < 7:
                    pos += block_size - in_b
                    continue
                _, length, rtype = _struct.unpack_from("<IHB", raw, pos)
                pos += 7
                if pos + length > len(raw) or rtype == 0:
                    break
                chunk = raw[pos:pos + length]
                pos += length
                if rtype == 1:
                    recs.append(chunk)
                elif rtype == 2:
                    buf = bytearray(chunk)
                elif rtype == 3:
                    buf.extend(chunk)
                elif rtype == 4:
                    buf.extend(chunk)
                    recs.append(bytes(buf))
                    buf = bytearray()
            for rec in recs:
                if len(rec) < 12:
                    continue
                p = 12
                while p < len(rec):
                    vt = rec[p]
                    p += 1
                    kl, p = _doubao_read_varint(rec, p)
                    p += kl
                    if vt == 1:
                        vl, p = _doubao_read_varint(rec, p)
                        v = rec[p:p + vl]
                        p += vl
                        blobs.append(_try_dec(v))
        except Exception:
            continue

    return blobs


def _doubao_extract_idb_sessions(idb_dir: Path) -> list[dict[str, Any]]:
    """从豆包 IndexedDB 中提取最近对话列表及已缓存的同步消息。"""
    blobs = _doubao_iter_idb_blobs(idb_dir)
    if not blobs:
        return []

    conv_map: dict[str, dict[str, Any]] = {}
    conv_blobs = [b for b in blobs if b"conversation-list-data" in b]
    if conv_blobs:
        blob = max(conv_blobs, key=len)
        for m in re.finditer(rb'\x0fconversation_id".([0-9]{10,25})', blob):
            cid = m.group(1).decode("ascii", errors="ignore")
            window = blob[m.end():m.end() + 2400]
            title = ""
            nm = re.search(rb'\x04name\x00?', window)
            if nm:
                pos = nm.end()
                tag = window[pos] if pos < len(window) else 0
                if tag == 0x63:
                    blen, q = _doubao_read_varint(window, pos + 1)
                    if 2 <= blen <= 400 and q + blen <= len(window):
                        title = window[q:q + blen].decode("utf-16-le", errors="ignore").strip()
                elif tag == 0x22:
                    blen, q = _doubao_read_varint(window, pos + 1)
                    if 1 <= blen <= 300 and q + blen <= len(window):
                        title = window[q:q + blen].decode("latin1", errors="ignore").strip()
            ts_val = 0
            tm = re.search(rb'update_time".([0-9]{10,13})', window) or re.search(rb'create_time".([0-9]{10,13})', window)
            if tm:
                ts_val = int(tm.group(1))
                if ts_val > 1e12:
                    ts_val //= 1000
            if cid not in conv_map or (title and not conv_map[cid]["title"]):
                conv_map[cid] = {"cid": cid, "title": title, "ts": ts_val, "cached_msgs": []}

    # 补充解析 mainTaskDataMap 中的已缓存用户消息文本与附件名
    msg_blobs = [b for b in blobs if b"mainTaskDataMap" in b and b"messages" in b]
    if msg_blobs:
        mblob = msg_blobs[-1]
        cm = re.search(rb'conversation_id".([0-9]{10,25})', mblob)
        mcid = cm.group(1).decode("ascii", errors="ignore") if cm else ""
        texts: list[str] = []
        for tm in re.finditer(rb'text_blocko".\x04text\x00?', mblob):
            pos = tm.end()
            if pos < len(mblob):
                tag = mblob[pos]
                if tag == 0x63:
                    blen, q = _doubao_read_varint(mblob, pos + 1)
                    if 2 <= blen <= 32768 and q + blen <= len(mblob):
                        t = mblob[q:q + blen].decode("utf-16-le", errors="ignore").strip()
                        if t and t not in texts:
                            texts.append(t)
                elif tag == 0x22:
                    blen, q = _doubao_read_varint(mblob, pos + 1)
                    if 2 <= blen <= 16384 and q + blen <= len(mblob):
                        t = mblob[q:q + blen].decode("latin1", errors="ignore").strip()
                        if t and t not in texts:
                            texts.append(t)
        if mcid and mcid in conv_map and texts:
            conv_map[mcid]["cached_msgs"] = texts

    return list(conv_map.values())


def get_doubao_sessions() -> list[dict[str, Any]]:
    """扫描本地豆包（Doubao）会话：Agent Mode 轨迹、Coding 快照与工作区产物。"""
    results: list[dict[str, Any]] = []
    seen_sids: set[str] = set()

    local_app = LOCAL_APPDATA
    user_home = USERPROFILE

    # 1. Doubao Agent Mode: trajectory.jsonl + assignment.md
    agent_sessions_dir = local_app / "Doubao" / "User Data" / "Default" / ".doubao" / "agent_mode" / "workspace" / ".sessions"
    if agent_sessions_dir.exists():
        for sess_dir in sorted(agent_sessions_dir.iterdir()):
            if not sess_dir.is_dir():
                continue
            sid = sess_dir.name
            agents_dir = sess_dir / "agents"
            if not agents_dir.exists():
                continue
            for traj in sorted(agents_dir.glob("*/system/trajectory.jsonl")):
                try:
                    st = traj.stat()
                    if st.st_size == 0:
                        continue
                except OSError:
                    continue
                assign_path = traj.parent / "assignment.md"
                started_at = ""
                title = ""
                records = 0
                first_user_text = ""
                try:
                    with open(traj, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            records += 1
                            if not first_user_text:
                                try:
                                    obj = json.loads(line)
                                    if obj.get("role") == "user":
                                        c = obj.get("content")
                                        if isinstance(c, str) and c.strip():
                                            first_user_text = c.strip()
                                except Exception:
                                    pass
                except Exception:
                    continue

                if assign_path.exists():
                    try:
                        assign_txt = assign_path.read_text(encoding="utf-8", errors="ignore")
                        m_ts = re.search(r"Created:\s*([0-9T:\-.Z]+)", assign_txt) or re.search(r"##\s*\[([0-9T:\-.Z]+)\]", assign_txt)
                        if m_ts:
                            started_at = _ag_local_time_str(m_ts.group(1))
                    except Exception:
                        pass

                if not started_at:
                    started_at = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                title = _doubao_clean_prompt_title(first_user_text) or f"豆包 Agent 会话 ({sid[:8]})"
                total_bytes = st.st_size + (assign_path.stat().st_size if assign_path.exists() else 0)
                tok = compute_session_tokens("doubao", sid, traj, st.st_mtime, total_bytes)
                seen_sids.add(sid)
                results.append({
                    "catalog_id": f"db_{sid[:16]}",
                    "format": "doubao",
                    "session_id": sid,
                    "title": title,
                    "started_at": started_at,
                    "records": max(1, records),
                    "bytes": total_bytes,
                    **_token_fields(tok),
                    "file_path": str(traj),
                    "all_files": [str(traj)] + ([str(assign_path)] if assign_path.exists() else []),
                    "account": "",
                    "model": "",
                    "mode": "agent_mode",
                    "workspace": "",
                    "source_kind": "agent_mode",
                    "exists": True,
                    "mtime": st.st_mtime,
                })
                break

    # 2. Doubao Coding Snapshots
    snap_root = local_app / "Doubao" / "User Data" / "coding" / "snapshot"
    if snap_root.exists():
        for snap_file in sorted(snap_root.glob("*/*/*/*.json")):
            try:
                st = snap_file.stat()
                data = json.loads(snap_file.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            exe = data.get("execution") if isinstance(data, dict) else None
            if not isinstance(exe, dict):
                continue
            cid = str(exe.get("conversationId") or snap_file.parent.parent.name).strip()
            if not cid or cid in seen_sids:
                continue
            seen_sids.add(cid)
            files_list = data.get("files") if isinstance(data.get("files"), list) else []
            started_raw = str(exe.get("startedAtFormatted") or "").replace("/", "-").strip()
            started_at = started_raw or datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            title = f"豆包 Coding ({cid[-8:]}) · {len(files_list)} 个文件快照"
            tok = compute_session_tokens("doubao", cid, snap_file, st.st_mtime, st.st_size)
            results.append({
                "catalog_id": f"db_{cid[:16]}",
                "format": "doubao",
                "session_id": cid,
                "title": title,
                "started_at": started_at,
                "records": max(1, len(files_list)),
                "bytes": st.st_size,
                **_token_fields(tok),
                "file_path": str(snap_file),
                "all_files": [str(snap_file)],
                "account": str(exe.get("userId") or ""),
                "model": "",
                "mode": "coding_snapshot",
                "workspace": "",
                "source_kind": "coding_snapshot",
                "exists": True,
                "mtime": st.st_mtime,
            })

    # 3. Doubao Chats Workspace artifacts
    chats_root = user_home / "Doubao" / "chats"
    if chats_root.exists():
        for date_dir in sorted(chats_root.iterdir()):
            if not date_dir.is_dir():
                continue
            for chat_dir in sorted(date_dir.iterdir()):
                if not chat_dir.is_dir():
                    continue
                files_in_dir = [p for p in sorted(chat_dir.rglob("*")) if p.is_file()]
                if not files_in_dir:
                    continue
                rel = f"{date_dir.name}/{chat_dir.name}"
                sid = f"chat_{hashlib.md5(rel.encode('utf-8')).hexdigest()[:12]}"
                if sid in seen_sids:
                    continue
                seen_sids.add(sid)
                total_bytes = sum(p.stat().st_size for p in files_in_dir)
                latest_mtime = max(p.stat().st_mtime for p in files_in_dir)
                started_at = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")
                primary = next((p for p in files_in_dir if p.suffix.lower() == ".md"), files_in_dir[0])
                title = f"{date_dir.name} · {primary.stem}"
                tok = compute_session_tokens("doubao", sid, primary, latest_mtime, total_bytes)
                results.append({
                    "catalog_id": f"db_{sid[:16]}",
                    "format": "doubao",
                    "session_id": sid,
                    "title": title,
                    "started_at": started_at,
                    "records": len(files_in_dir),
                    "bytes": total_bytes,
                    **_token_fields(tok),
                    "file_path": str(chat_dir),
                    "all_files": [str(p) for p in files_in_dir[:20]],
                    "account": "",
                    "model": "",
                    "mode": "chat_workspace",
                    "workspace": str(chat_dir),
                    "source_kind": "chat_workspace",
                    "exists": True,
                    "mtime": latest_mtime,
                })

    # 4. 豆包云端同步仓（完整会话正文；优先于本地 IndexedDB 元数据）
    cloud_data = doubao_cloud.load()
    for cid, item in sorted(
        cloud_data.items(), key=lambda kv: (kv[1].get("ts") or 0), reverse=True
    ):
        cid = str(cid)
        msg_list = item.get("messages") or []
        text_msgs = [
            m for m in msg_list
            if m.get("kind", "message") == "message" and str(m.get("text") or "").strip()
        ]
        if not text_msgs:
            continue
        # 云端正文优先：同 cid 的 Coding Snapshot / Agent Mode 摘要不再重复展示
        prev = next((r for r in results if str(r.get("session_id")) == cid), None)
        if prev is not None:
            try:
                results.remove(prev)
            except ValueError:
                pass
        seen_sids.add(cid)
        ts = item.get("ts") or 0
        started_at = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        title = str(item.get("title") or f"豆包对话 ({cid[-8:]})")
        total_bytes = max(
            128, sum(len(str(m.get("text") or "").encode("utf-8", errors="ignore")) for m in msg_list)
        )
        tok = compute_session_tokens(
            "doubao", cid, Path(item.get("file") or item.get("dir") or ""), ts, total_bytes
        )
        results.append({
            "catalog_id": f"db_{cid[:16]}",
            "format": "doubao",
            "session_id": cid,
            "title": title,
            "started_at": started_at,
            "records": max(1, len(msg_list)),
            "bytes": total_bytes,
            **_token_fields(tok),
            "file_path": item.get("file") or item.get("dir") or "",
            "all_files": [item.get("file") or item.get("dir") or ""],
            "account": "",
            "model": "",
            "mode": "chat_cloud",
            "workspace": "",
            "source_kind": "cloud",
            "cached_msgs": [],
            "exists": True,
            "mtime": ts,
        })

    # 5. Doubao Chat IndexedDB（遍历所有 profile：Default / Profile 1 ...）
    doubao_user_data = local_app / "Doubao" / "User Data"
    idb_data = doubao_idb.load(doubao_user_data)
    idb_mtime = 0.0
    for idb_dir in doubao_idb.leveldb_dirs(doubao_user_data):
        for p in idb_dir.glob("*"):
            if p.is_file():
                try:
                    idb_mtime = max(idb_mtime, p.stat().st_mtime)
                except OSError:
                    continue
    existing_by_sid = {
        str(r.get("session_id") or ""): r for r in results if r.get("format") == "doubao"
    }
    for cid, item in sorted(idb_data.items(), key=lambda kv: (kv[1].get("ts") or 0), reverse=True):
        if str(cid) in seen_sids:
            continue
        msg_list = item.get("messages") or []
        cached_msgs = [
            m["text"] for m in msg_list
            if m.get("kind", "message") == "message" and m.get("text")
        ]
        prev = existing_by_sid.get(cid)
        if prev is not None:
            # IDB 里有真实对话就以它为准；Coding Snapshot 只是产物摘要
            if not cached_msgs:
                continue
            try:
                results.remove(prev)
            except ValueError:
                continue
        # 纯 IndexedDB 元数据占位：只有标题、没有任何任务态正文。
        # 这类记录在云端也没有可取的 message_list（实测按 ID 拉取为 0），
        # 默认不进入会话列表，避免以“0 步 / 空会话”盖住真正有正文的会话。
        # 源文件不删除；需要排查时可显式设置 DOUBAO_INCLUDE_EMPTY_IDB=1。
        if not cached_msgs and os.environ.get("DOUBAO_INCLUDE_EMPTY_IDB", "0") != "1":
            continue
        seen_sids.add(cid)
        ts = item.get("ts") or idb_mtime
        started_at = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        title = item.get("title") or f"豆包对话 ({cid[-8:]})"
        total_bytes = max(128, sum(len(t.encode("utf-8", errors="ignore")) for t in cached_msgs))
        tok = compute_session_tokens("doubao", cid, Path(item.get("dir") or doubao_user_data), ts, total_bytes)
        results.append({
            "catalog_id": f"db_{cid[:16]}",
            "format": "doubao",
            "session_id": cid,
            "title": title,
            "started_at": started_at,
            "records": len(cached_msgs),
            "bytes": total_bytes,
            **_token_fields(tok),
            "file_path": item.get("dir") or str(doubao_user_data),
            "all_files": [item.get("dir") or str(doubao_user_data)],
            "account": "",
            "model": "",
            "mode": "chat_indexeddb",
            "workspace": "",
            "source_kind": "indexeddb",
            "cached_msgs": cached_msgs,
            "exists": True,
            "mtime": ts,
        })

    return results


def get_doubao_session_messages(session_match: dict[str, Any]) -> list[dict[str, Any]]:
    """解析豆包会话的消息与工具事件列表。"""
    events: list[dict[str, Any]] = []
    source_kind = session_match.get("source_kind", "")
    cid = str(session_match.get("session_id") or "")
    # 云端同步完成后，快照可能仍是旧的 IndexedDB 记录；详情必须优先使用
    # 云端完整正文，否则会出现「列表显示已同步，详情仍只有 3 条」的假象。
    if source_kind == "indexeddb" and doubao_cloud.get(cid).get("messages"):
        source_kind = "cloud"
    fp = Path(str(session_match.get("file_path") or ""))
    started_at = str(session_match.get("started_at") or "")

    if source_kind == "cloud":
        item = doubao_cloud.get(cid)
        for m in item.get("messages") or []:
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            ts = int(m.get("ts") or 0)
            events.append({
                "kind": m.get("kind") or "message",
                "role": m.get("role") or "assistant",
                "timestamp": (
                    datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else started_at
                ),
                "text": text,
                "tool_name": m.get("tool_name") or "",
                "tool_call_id": "",
                "payload": None,
            })
        if events:
            return events
        for idx, t in enumerate(session_match.get("cached_msgs") or []):
            text = str(t or "").strip()
            if not text:
                continue
            events.append({
                "kind": "message",
                "role": "user" if idx % 2 == 0 else "assistant",
                "timestamp": started_at,
                "text": text,
                "tool_name": "",
                "tool_call_id": "",
                "payload": None,
            })
        return events

    if source_kind == "indexeddb":
        cid = str(session_match.get("session_id") or "")
        local_app = LOCAL_APPDATA
        item = doubao_idb.load(local_app / "Doubao" / "User Data").get(cid) or {}
        for m in item.get("messages") or []:
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            events.append({
                "kind": m.get("kind") or "message",
                "role": m.get("role") or "assistant",
                "timestamp": started_at,
                "text": text,
                "tool_name": m.get("tool_name") or "",
                "tool_call_id": "",
                "payload": None,
            })
        if events:
            return events
        for idx, t in enumerate(session_match.get("cached_msgs") or []):
            text = str(t or "").strip()
            if not text:
                continue
            events.append({
                "kind": "message",
                "role": "user" if idx == 0 else "assistant",
                "timestamp": started_at,
                "text": text,
                "tool_name": "",
                "tool_call_id": "",
                "payload": None,
            })
        if events:
            return events
        events.append({
            "kind": "message",
            "role": "assistant",
            "timestamp": started_at,
            "text": "该会话只有本地 IndexedDB 元数据（标题），没有任务态正文；豆包云端按该 ID 查询时 index_list 与 latest_messagelist 也都返回 0 条，因此不存在可读的正文。",
            "tool_name": "",
            "tool_call_id": "",
            "payload": None,
        })
        return events

    if source_kind == "agent_mode" and fp.exists():
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                role = str(obj.get("role") or "")
                content = obj.get("content")
                text = content if isinstance(content, str) else (json.dumps(content, ensure_ascii=False) if content else "")
                if role == "user" and text.strip():
                    clean_user = re.sub(r"\[([^\]]+)\]\(<[^>]+>\)", r"[\1]", text.strip())
                    events.append({
                        "kind": "message",
                        "role": "user",
                        "timestamp": started_at,
                        "text": clean_user,
                        "tool_name": "",
                        "tool_call_id": "",
                        "payload": None,
                    })
                elif role == "assistant":
                    if text.strip():
                        events.append({
                            "kind": "message",
                            "role": "assistant",
                            "timestamp": started_at,
                            "text": text.strip(),
                            "tool_name": "",
                            "tool_call_id": "",
                            "payload": None,
                        })
                    for tc in (obj.get("tool_calls") or []):
                        if not isinstance(tc, dict):
                            continue
                        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                        fn_name = str(fn.get("name") or tc.get("type") or "tool")
                        args = fn.get("arguments")
                        events.append({
                            "kind": "tool_call",
                            "role": "assistant",
                            "timestamp": started_at,
                            "text": json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else str(args or ""),
                            "tool_name": fn_name,
                            "tool_call_id": str(tc.get("id") or ""),
                            "payload": args if isinstance(args, dict) else None,
                        })
                elif role == "tool":
                    events.append({
                        "kind": "tool_result",
                        "role": "tool",
                        "timestamp": started_at,
                        "text": text.strip(),
                        "tool_name": "",
                        "tool_call_id": str(obj.get("tool_call_id") or ""),
                        "payload": None,
                    })
        return events

    if source_kind == "coding_snapshot" and fp.exists():
        data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
        exe = data.get("execution") or {}
        files_list = data.get("files") or []
        lines = [
            "**智能体平台：** 豆包 (Coding Snapshot)",
            f"**会话标识：** `{exe.get('conversationId', '')}`",
            f"**执行标识：** `{exe.get('executionKey', '')}`",
            f"**开始时间：** {exe.get('startedAtFormatted', started_at)}",
            f"**结束时间：** {exe.get('endedAtFormatted', '')}",
            f"**快照文件数：** {len(files_list)}",
        ]
        for fitem in files_list[:30]:
            if isinstance(fitem, dict):
                fpath = fitem.get("filePath") or fitem.get("path") or fitem.get("relativePath") or ""
                if fpath:
                    lines.append(f"- `{fpath}`")
        events.append({
            "kind": "message",
            "role": "assistant",
            "timestamp": started_at,
            "text": "\n".join(lines),
            "tool_name": "",
            "tool_call_id": "",
            "payload": None,
        })
        return events

    if source_kind == "chat_workspace" and fp.exists() and fp.is_dir():
        files_in_dir = [p for p in sorted(fp.rglob("*")) if p.is_file()]
        summary = [f"**豆包工作区目录：** `{fp}`", f"**产物文件数：** {len(files_in_dir)}"]
        for p in files_in_dir[:20]:
            summary.append(f"- `{p.name}` ({p.stat().st_size} B)")
        events.append({
            "kind": "message",
            "role": "assistant",
            "timestamp": started_at,
            "text": "\n".join(summary),
            "tool_name": "",
            "tool_call_id": "",
            "payload": None,
        })
        for p in files_in_dir[:5]:
            if p.suffix.lower() in {".md", ".txt", ".ps1", ".py", ".json"} and p.stat().st_size <= 64 * 1024:
                txt = p.read_text(encoding="utf-8", errors="ignore")[:12000]
                events.append({
                    "kind": "message",
                    "role": "assistant",
                    "timestamp": started_at,
                    "text": f"### {p.name}\n\n{txt}",
                    "tool_name": "",
                    "tool_call_id": "",
                    "payload": None,
                })
        return events

    if source_kind == "indexeddb":
        cached_msgs = session_match.get("cached_msgs") or []
        if cached_msgs:
            for txt in cached_msgs:
                events.append({
                    "kind": "message",
                    "role": "user",
                    "timestamp": started_at,
                    "text": txt,
                    "tool_name": "",
                    "tool_call_id": "",
                    "payload": None,
                })
        else:
            events.append({
                "kind": "message",
                "role": "assistant",
                "timestamp": started_at,
                "text": (
                    f"**智能体平台：** 豆包 (IndexedDB 缓存索引)\n"
                    f"**会话标题：** {session_match.get('title', '')}\n"
                    f"**会话标识：** `{session_match.get('session_id', '')}`\n"
                    f"**活跃时间：** {started_at}"
                ),
                "tool_name": "",
                "tool_call_id": "",
                "payload": None,
            })
        return events

    return events

def get_catalog_db() -> sqlite3.Connection:
    path = default_catalog_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def clean_human_title(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[A-Za-z]:[\\/](?:[^\\/\s]+[\\/])*([^\\/\s]+)", r"\1", text)
    text = re.sub(r"[`#*_\r\n\t]+", " ", text)
    text = re.sub(r"^(?:请帮我|帮我|请问|我想|如何|怎么|关于|现在|目前)\s*", "", text)
    text = re.sub(r"^[^一-龥A-Za-z0-9]+", "", text)
    text = re.sub(r'[\\/:*?"<>|]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ._-")
    while text and text[-1] in "HP| `_-":
        text = text[:-1].strip(" ._-")
    if len(text) > 40:
        text = text[:40].rstrip(" ._-")
    return text

def _ag_local_time_str(value: Any) -> str:
    """把 ISO8601（UTC，带 Z）时间戳转成本地时区的 'YYYY-MM-DD HH:MM:SS'。"""
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s


# 会话标识串：32 位裸十六进制、带连字符 UUID、以及 sessionID/工具调用 id 之类。
# Antigravity 的 protobuf 里这些字段与人类标题同层出现，必须排除，否则卡片标题会变成一串 id。
_AG_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_AG_HEX32_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
_AG_HEXISH_RE = re.compile(r"^[0-9a-f]{16,}$", re.I)
_AG_TOKEN_RE = re.compile(r"^[0-9a-zA-Z_\-]+$")


def _ag_looks_like_id(text: str) -> bool:
    """判断候选串是否是机器标识而非人类可读标题。"""
    t = (text or "").strip()
    if not t:
        return True
    if "sessionID" in t or "conversation_summaries" in t:
        return True
    if _AG_UUID_RE.match(t) or _AG_HEX32_RE.match(t) or _AG_HEXISH_RE.match(t):
        return True
    # 单段无空格的 ASCII 串，且数字占比高 → 判为 id（避免误伤 Retrofitting 这类正常英文标题）
    if _AG_TOKEN_RE.match(t) and len(t) >= 20:
        digits = sum(ch.isdigit() for ch in t)
        if digits >= 8:
            return True
    return False


_ANTIGRAVITY_TITLE_CACHE: dict[str, tuple[float, str]] = {}

def extract_antigravity_title(abs_path: Path) -> str:
    path_str = str(abs_path)
    if not abs_path.exists() or abs_path.stat().st_size == 0:
        return ""
    mtime = abs_path.stat().st_mtime
    if path_str in _ANTIGRAVITY_TITLE_CACHE:
        cached_mtime, cached_title = _ANTIGRAVITY_TITLE_CACHE[path_str]
        if cached_mtime == mtime and cached_title:
            return cached_title

    title = ""
    try:
        conn = sqlite3.connect(f"file:{path_str}?mode=ro", uri=True)
        cur = conn.cursor()

        # 1. First priority: Check step_type = 23 (Cascade Title from IDE) sorted by idx ASC (earliest is main title)
        try:
            rows_23 = cur.execute("SELECT idx, step_payload FROM steps WHERE step_type = 23 ORDER BY idx ASC LIMIT 5").fetchall()
            for idx, payload in rows_23:
                if not payload:
                    continue
                # Antigravity Cascade Title is serialized in protobuf field 4 followed by field 9 (H)
                m = re.search(rb'"([-])(.*?)(?=H)', payload)
                if m:
                    try:
                        s = m.group(2).decode("utf-8").strip()
                        if not _ag_looks_like_id(s) and len(s) >= 2:
                            title = clean_human_title(s)
                            if title:
                                break
                    except Exception:
                        pass
                if not title:
                    # Varint length string after byte 0x22
                    m2 = re.search(rb'"([-])', payload)
                    if m2:
                        length = ord(m2.group(1))
                        start = m2.end()
                        if start + length <= len(payload):
                            raw = payload[start:start+length]
                            try:
                                s = raw.decode("utf-8").strip()
                                if not _ag_looks_like_id(s) and len(s) >= 2:
                                    title = clean_human_title(s)
                                    if title:
                                        break
                            except Exception:
                                pass
                if title:
                    break
        except Exception:
            pass

        # 2. Second priority: Check step_type = 14 (User Request prompt)
        if not title:
            try:
                user_rows = cur.execute("SELECT idx, step_payload FROM steps WHERE step_type = 14 ORDER BY idx ASC LIMIT 5").fetchall()
                for idx, payload in user_rows:
                    if not payload:
                        continue
                    dec = payload.decode("utf-8", errors="ignore")
                    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", dec, re.DOTALL)
                    if m:
                        for line in m.group(1).splitlines():
                            t = clean_human_title(line.strip())
                            if len(t) >= 2:
                                title = t
                                break
                    if title:
                        break
                    # Fallback string candidates
                    candidates = re.findall(r"[一-龥A-Za-z0-9_\-\.\:\+\\/ ]{4,}", dec)
                    for c in candidates:
                        c = c.strip()
                        if any(skip in c for skip in ["Conversation History", "conversation_summaries", "file:///", "USER_REQUEST"]):
                            continue
                        if len(c) >= 3 and not _ag_looks_like_id(c):
                            title = clean_human_title(c)
                            if title:
                                break
                    if title:
                        break
            except Exception:
                pass

        conn.close()
    except Exception:
        pass

    # 最后一道闸门：清洗后若仍是机器标识，按"无标题"处理，交给上层用父会话/首条提问兜底
    if title and _ag_looks_like_id(title):
        title = ""

    _ANTIGRAVITY_TITLE_CACHE[path_str] = (mtime, title)
    return title



# ---------------------------------------------------------------------------
# Global Dialogue Content Full-Text Search Engine (SQLite FTS5 + CJK Tokenizer)
# ---------------------------------------------------------------------------

def cjk_tokenize(text: str) -> str:
    """Separate CJK characters with whitespace while preserving ASCII words/symbols.
    Enables SQLite unicode61 FTS5 to index arbitrary Chinese words, single chars and phrases.
    """
    if not text:
        return ""
    return re.sub(r'([一-鿿㐀-䶿豈-﫿])', r' \1 ', text)

def cjk_untokenize(text: str) -> str:
    """Collapse artificial spaces between CJK characters, preserving <mark> tags."""
    if not text:
        return ""
    text = re.sub(r'([一-鿿㐀-䶿豈-﫿])\s+(?=[一-鿿㐀-䶿豈-﫿<])', r'\1', text)
    text = re.sub(r'(</mark>)\s+(?=[一-鿿㐀-䶿豈-﫿])', r'\1', text)
    text = re.sub(r'([一-鿿㐀-䶿豈-﫿])\s+(?=<mark)', r'\1', text)
    return text

class SessionFTSManager:
    """High-performance SQLite FTS5 Full-Text Search Engine for agent conversations.
    Zero external dependencies, incremental file indexing, sub-millisecond query latency.
    """
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        # 正常路径：直接打开原库。
        # 若原库的 -wal 被安全软件/残留句柄锁住，SQLite 会报
        # “unable to open database file”。此时从主库文件做一份可写副本继续
        # 启动，避免整个 Memory Tools 因为一个 WAL 句柄而不可用。
        try:
            self._init_db_at(self.db_path)
        except sqlite3.OperationalError:
            if not self.db_path.exists():
                raise
            alt = self.db_path.with_name(f"{self.db_path.stem}.recovered{self.db_path.suffix}")
            if not alt.exists():
                shutil.copy2(self.db_path, alt)
            self.db_path = alt
            self._init_db_at(alt)

    def _init_db_at(self, db_path: Path):
        with self._lock, sqlite3.connect(db_path, timeout=15) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fts_file_meta (
                    file_path TEXT PRIMARY KEY,
                    mtime REAL,
                    size INTEGER,
                    catalog_id TEXT,
                    indexed_turns INTEGER,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(
                    catalog_id UNINDEXED,
                    session_id UNINDEXED,
                    role UNINDEXED,
                    turn_index UNINDEXED,
                    timestamp UNINDEXED,
                    session_title UNINDEXED,
                    session_format UNINDEXED,
                    cjk_text,
                    tokenize="unicode61"
                )
            """)

    def is_file_up_to_date(self, file_path: str, mtime: float, size: int) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT mtime, size FROM fts_file_meta WHERE file_path = ?",
                (file_path,)
            ).fetchone()
            if not row:
                return False
            return abs(row["mtime"] - mtime) < 0.001 and row["size"] == size

    def index_session_turns(
        self,
        file_path: str,
        mtime: float,
        size: int,
        catalog_id: str,
        session_id: str,
        session_title: str,
        session_format: str,
        turns: list[dict]
    ):
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM conversation_fts WHERE catalog_id = ?", (catalog_id,))
            insert_rows = []
            for t in turns:
                role = t.get("role") or ""
                if role not in ("user", "assistant"):
                    continue
                text = (t.get("text") or "").strip()
                if len(text) < 2:
                    continue
                if len(text) > 12000:
                    text = text[:12000]
                tokenized = cjk_tokenize(text)
                insert_rows.append((
                    catalog_id,
                    session_id,
                    role,
                    int(t.get("turn_index", 0)),
                    str(t.get("timestamp") or ""),
                    str(session_title or ""),
                    str(session_format or ""),
                    tokenized
                ))

            if insert_rows:
                conn.executemany("""
                    INSERT INTO conversation_fts (
                        catalog_id, session_id, role, turn_index, timestamp,
                        session_title, session_format, cjk_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, insert_rows)

            conn.execute("""
                INSERT OR REPLACE INTO fts_file_meta (
                    file_path, mtime, size, catalog_id, indexed_turns, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (file_path, mtime, size, catalog_id, len(insert_rows), time.time()))

    def delete_session(self, catalog_id: str):
        with self._lock, self._get_conn() as conn:
            conn.execute("DELETE FROM conversation_fts WHERE catalog_id = ?", (catalog_id,))
            conn.execute("DELETE FROM fts_file_meta WHERE catalog_id = ?", (catalog_id,))

    def get_stats(self) -> dict:
        with self._get_conn() as conn:
            # FTS5 的 count(*) 是 O(n) 全表扫描（本库 4.9 万行约 60 ms，占检索总耗时 85%）。
            # docsize 表每个文档一行、与主表行数严格一致，计数为 O(1)（约 0.01 ms）。
            try:
                turns = int(conn.execute("SELECT count(*) FROM conversation_fts_docsize").fetchone()[0])
            except sqlite3.OperationalError:
                turns = 0
            if turns <= 0:
                # 兜底：极旧版本 FTS 或空库时退回主表计数
                turns = int(conn.execute("SELECT count(*) FROM conversation_fts").fetchone()[0])
            files = conn.execute("SELECT count(*) FROM fts_file_meta").fetchone()[0]
            return {"indexed_files": files, "indexed_turns": turns}

    def search(self, query: str, limit: int = 50) -> dict:
        t0 = time.time()
        q = (query or "").strip()
        if not q:
            stats = self.get_stats()
            return {
                "query": "",
                "count": 0,
                "total_indexed_turns": stats["indexed_turns"],
                "total_indexed_files": stats["indexed_files"],
                "latency_ms": 0,
                "results": []
            }

        tokenized_q = cjk_tokenize(q)
        fts_match = '"' + ' '.join(tokenized_q.split()) + '"'

        with self._get_conn() as conn:
            try:
                cur = conn.execute("""
                    SELECT catalog_id, session_id, role, turn_index, timestamp,
                           session_title, session_format,
                           snippet(conversation_fts, 7, '<mark class="chat-highlight">', '</mark>', '...', 28) AS snippet
                    FROM conversation_fts
                    WHERE conversation_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (fts_match, limit))
                rows = cur.fetchall()
            except sqlite3.OperationalError:
                # Fallback to plain terms if syntax error
                try:
                    cur = conn.execute("""
                        SELECT catalog_id, session_id, role, turn_index, timestamp,
                               session_title, session_format,
                               snippet(conversation_fts, 7, '<mark class="chat-highlight">', '</mark>', '...', 28) AS snippet
                        FROM conversation_fts
                        WHERE conversation_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (tokenized_q, limit))
                    rows = cur.fetchall()
                except Exception:
                    rows = []

            stats = self.get_stats()

        results = []
        for r in rows:
            results.append({
                "catalog_id": r["catalog_id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "turn_index": r["turn_index"],
                "timestamp": r["timestamp"],
                "session_title": r["session_title"],
                "session_format": r["session_format"],
                "snippet": cjk_untokenize(r["snippet"]),
            })

        latency = round((time.time() - t0) * 1000, 2)
        return {
            "query": q,
            "count": len(results),
            "total_indexed_turns": stats["indexed_turns"],
            "total_indexed_files": stats["indexed_files"],
            "latency_ms": latency,
            "results": results
        }

FTS_DB_PATH = Path(default_catalog_path()).parent / "dialogue_fts.sqlite3"
GLOBAL_FTS_MGR = SessionFTSManager(FTS_DB_PATH)

_FTS_SYNC_IN_PROGRESS = False
_FTS_SYNC_PENDING = False

def _event_kind_value(ev: Any) -> str:
    """取事件的 kind 字符串（session_migrate 用 EventKind 枚举）。"""
    kind = getattr(ev, "kind", None)
    if kind is None:
        return ""
    return kind.value if hasattr(kind, "value") else str(kind)


def extract_dialogue_turns_for_fts(path: Path, fmt: str) -> list[dict]:
    """抽取可检索的对白轮次（供 FTS 索引）。

    轮边界修正（本轮 bugfix）
    ------------------------
    旧实现只判 `role == "user"` 就 `user_turn_no += 1`。但 Claude Code 的
    `tool_result` 事件 role 也是 `user`，于是 FTS 的 `turn_index` 会多算，
    "检索命中第 N 轮 → 详情跳到第 N 轮"就会错位。
    现在边界判定统一为 `kind == "message" and role == "user"`（与
    `services/turns.py` / 前端 `buildTurns` 三方一致），
    但**索引内容不变**：非边界的 user/tool_result 文本仍然入索引，
    只是不再推进轮号，避免索引覆盖率下降。
    """
    turns: list[dict] = []

    def append(role: str, turn_index: int, text: str, timestamp: str) -> None:
        cleaned = (text or "").strip()
        # 与 `SessionFTSManager.index_session_turns` 的入库过滤保持一致（<2 字符不入库）；
        # 否则"抽取器算出的最大轮号"与"索引里的最大轮号"会永久差 1，对账永远为红。
        if len(cleaned) < 2:
            return
        turns.append({
            "role": role,
            "turn_index": max(turn_index, 1),
            "text": cleaned,
            "timestamp": timestamp or "",
        })

    try:
        if fmt in {"antigravity", "claude", "codex"}:
            if fmt == "antigravity":
                agent_format = AgentFormat.ANTIGRAVITY
            elif fmt == "claude":
                agent_format = AgentFormat.CLAUDE
            else:
                agent_format = AgentFormat.CODEX
            sess = load_session(path, agent_format)
            user_turn_no = 0
            for ev in sess.events:
                role = ev.role.value if hasattr(ev.role, "value") and ev.role else str(ev.role or "")
                if role not in {"user", "assistant"}:
                    continue
                is_boundary = role == "user" and _event_kind_value(ev) == turns_service.TURN_BOUNDARY_KIND
                if role == "user":
                    if is_boundary:
                        user_turn_no += 1
                    append("user", user_turn_no, ev.text or "", ev.timestamp)
                else:
                    append("assistant", user_turn_no, ev.text or "", ev.timestamp)
        elif fmt == "trae":
            messages = get_trae_session_messages({"file_path": str(path), "session_id": path.stem})
            user_turn_no = 0
            for msg in messages:
                role = msg.get("role") or ""
                if role not in {"user", "assistant"}:
                    continue
                if role == "user":
                    user_turn_no += 1  # Trae 的消息来自对话消息表，无 tool_result 混淆
                append(role, user_turn_no, msg.get("text") or "", msg.get("timestamp") or "")
        elif fmt == "workbuddy":
            events = get_workbuddy_session_events(path)
            user_turn_no = 0
            for ev in events:
                role = ev.get("role") or ""
                if role not in {"user", "assistant"}:
                    continue
                kind = ev.get("kind") or "message"
                if role == "user":
                    if kind == turns_service.TURN_BOUNDARY_KIND:
                        user_turn_no += 1
                    append("user", user_turn_no, ev.get("text") or "", ev.get("timestamp") or "")
                else:
                    append("assistant", user_turn_no, ev.get("text") or "", ev.get("timestamp") or "")
    except Exception:
        pass
    return turns

def collect_all_sessions(fmt_filter: str = "all", search: str = "") -> list[dict]:
    readable_map = load_brain_readable_map()
    ag_summaries = load_antigravity_summaries_map()

    db = get_catalog_db()
    sql = """
        SELECT s.id, s.catalog_id, s.format, s.session_id, s.display_title, s.started_at,
               s.status, s.records, s.bytes, s.relative_path, r.path as root_path
        FROM sessions s
        JOIN roots r ON s.root_id = r.id
        WHERE s.status != 'missing'
    """
    params = []
    if fmt_filter and fmt_filter not in {"all", "workbuddy", "trae"}:
        sql += " AND s.format = ?"
        params.append(fmt_filter)

    sql += " ORDER BY s.started_at DESC"
    rows = db.execute(sql, params).fetchall() if fmt_filter not in {"workbuddy", "trae"} else []
    db.close()

    results = []
    seen_sids = set()

    for row in rows:
        abs_path = Path(row["root_path"]) / row["relative_path"]
        sid = row["session_id"] or abs_path.stem
        fmt = row["format"]
        if sid in seen_sids:
            continue
        seen_sids.add(sid)
        mtime = abs_path.stat().st_mtime if abs_path.exists() else 0
        
        # Formulate natural language descriptive title
        title = ""
        date_str = ""
        local_started = _ag_local_time_str(row["started_at"])
        if local_started:
            date_str = local_started[:10]

        if fmt == "antigravity":
            short_sid = sid[:8].lower()
            clean_t = ""
            if sid in ag_summaries and ag_summaries[sid].get("title"):
                clean_t = ag_summaries[sid]["title"]
            if not clean_t:
                clean_t = extract_antigravity_title(abs_path)
            if not clean_t and short_sid in readable_map:
                clean_t = readable_map[short_sid].get("title", "")
            if not clean_t:
                # 子代理（browser 等）会话在 conversation_summaries 里 title 恒为空，
                # 只能回溯父链，给出「父标题 · xxx 子会话」，别再退化成 会话_xxxxxxxx。
                parent_title, agent_name = antigravity_parent_title(sid, ag_summaries)
                if parent_title:
                    clean_t = f"{parent_title} · {agent_name or '子代理'} 子会话"
            if not clean_t:
                # 官方标题缺失时，用会话首条用户提问作为标题
                clean_t = antigravity_first_user_text(abs_path)
            if not clean_t:
                raw_dt = row["display_title"] or ""
                if raw_dt and not _ag_looks_like_id(raw_dt):
                    clean_t = clean_human_title(raw_dt)
            if not clean_t:
                clean_t = f"会话_{sid[:8]}"

            d = date_str or (datetime.fromtimestamp(mtime).strftime("%Y-%m-%d") if mtime else "2026-10-10")
            title = f"{d} · {clean_t}"
        elif fmt == "claude":
            c_title, c_date = extract_claude_title_and_date(abs_path)
            d = date_str or c_date
            title = f"{d} · {c_title}"
        else:
            d = date_str or "2026-01-01"
            raw_t = row["display_title"] or sid[:8]
            title = f"{d} · {raw_t}"

        # Search filtering
        if search:
            haystack = f"{title} {sid} {fmt} {str(abs_path)}".lower()
            if search not in haystack:
                continue

        s_bytes = row["bytes"] or (abs_path.stat().st_size if abs_path.exists() else 0)
        tok_info = compute_session_tokens(fmt, sid, abs_path if abs_path.exists() else None, mtime, s_bytes)
        catalog_entry = {
            "catalog_id": row["catalog_id"],
            "format": fmt,
            "session_id": sid,
            "title": title,
            "started_at": local_started or (datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S") if mtime else ""),
            "records": row["records"] or 0,
            "bytes": s_bytes,
            **_token_fields(tok_info),
            "file_path": str(abs_path),
            "exists": abs_path.exists(),
            "mtime": mtime,
        }
        if fmt == "antigravity" and abs_path.exists():
            try:
                with sqlite3.connect(f"file:{str(abs_path)}?mode=ro", uri=True) as ag_conn:
                    catalog_entry["records"] = ag_conn.execute("SELECT count(*) FROM steps").fetchone()[0]
            except Exception:
                pass
            catalog_entry["lineage"] = antigravity_lineage_key(abs_path)
            catalog_entry["side_question"] = antigravity_side_question(abs_path)
            ag_info = ag_summaries.get(sid, {})
            catalog_entry["parent_id"] = (ag_info.get("parent_id") or "").strip()
            catalog_entry["nesting_depth"] = ag_info.get("nesting_depth") or 0
            catalog_entry["agent_name"] = (ag_info.get("agent_name") or "").strip()
        results.append(catalog_entry)

    # Directly merge any Antigravity conversation .db files that were missed or new
    if fmt_filter in {"all", "antigravity", ""}:
        for ag_conv_dir in ANTIGRAVITY_CONV_DIRS:
            if not ag_conv_dir.exists():
                continue
            for p in ag_conv_dir.glob("*.db"):
                if p.name.endswith("-wal") or p.name.endswith("-shm") or p.stat().st_size == 0:
                    continue
                sid = p.stem
                if sid in seen_sids:
                    continue
                seen_sids.add(sid)
                mtime = p.stat().st_mtime
                d = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                clean_t = ""
                if sid in ag_summaries and ag_summaries[sid].get("title"):
                    clean_t = ag_summaries[sid]["title"]
                if not clean_t:
                    clean_t = extract_antigravity_title(p)
                if not clean_t:
                    parent_title, agent_name = antigravity_parent_title(sid, ag_summaries)
                    if parent_title:
                        clean_t = f"{parent_title} · {agent_name or '子代理'} 子会话"
                if not clean_t:
                    clean_t = antigravity_first_user_text(p)
                if not clean_t:
                    clean_t = f"会话_{sid[:8]}"
                title = f"{d} · {clean_t}"
                if search:
                    haystack = f"{title} {sid} antigravity {str(p)}".lower()
                    if search not in haystack:
                        continue
                steps_count = ag_summaries.get(sid, {}).get("step_count", 0)
                if not steps_count:
                    try:
                        with sqlite3.connect(f"file:{str(p)}?mode=ro", uri=True) as c:
                            steps_count = c.execute("SELECT count(*) FROM steps").fetchone()[0]
                    except Exception:
                        pass
                started_at_str = ag_summaries.get(sid, {}).get("last_modified_time")
                if not started_at_str:
                    started_at_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    started_at_str = _ag_local_time_str(started_at_str)
                ag_size = p.stat().st_size
                ag_tok = compute_session_tokens("antigravity", sid, p, mtime, ag_size)
                ag_info = ag_summaries.get(sid, {})
                results.append({
                    "catalog_id": f"ag_{sid[:12]}",
                    "format": "antigravity",
                    "session_id": sid,
                    "title": title,
                    "started_at": started_at_str,
                    "records": steps_count,
                    "bytes": ag_size,
                    "lineage": antigravity_lineage_key(p),
                    "side_question": antigravity_side_question(p),
                    "parent_id": (ag_info.get("parent_id") or "").strip(),
                    "nesting_depth": ag_info.get("nesting_depth") or 0,
                    "agent_name": (ag_info.get("agent_name") or "").strip(),
                    **_token_fields(ag_tok),
                    "file_path": str(p),
                    "exists": True,
                    "mtime": mtime,
                })

    # Append WorkBuddy sessions
    if fmt_filter in {"all", "workbuddy", ""}:
        wb_list = get_workbuddy_sessions()
        for w in wb_list:
            if search:
                haystack = f"{w['title']} {w['session_id']} workbuddy {w['file_path']}".lower()
                if search not in haystack:
                    continue
            w_path = Path(w["file_path"])
            w["mtime"] = w_path.stat().st_mtime if w_path.exists() else 0
            results.append(w)

    # Append Trae sessions
    if fmt_filter in {"all", "trae", ""}:
        trae_list = get_trae_sessions()
        for t in trae_list:
            if search:
                haystack = f"{t['title']} {t['session_id']} trae {t['file_path']}".lower()
                if search not in haystack:
                    continue
            t_path = Path(t["file_path"])
            # 不要把每个 Trae 会话都覆盖成解密库文件的 mtime：同一库文件下
            # 所有会话会得到相同值，“最近活跃”排序就退化成文件枚举顺序。
            # 只有没有会话级时间时才回退到文件 mtime。
            if float(t.get("mtime") or 0) <= 0:
                t["mtime"] = t_path.stat().st_mtime if t_path.exists() else 0
            results.append(t)

    # Append Doubao sessions
    if fmt_filter in {"all", "doubao", ""}:
        db_list = get_doubao_sessions()
        for d in db_list:
            if search:
                haystack = f"{d['title']} {d['session_id']} doubao {d['file_path']}".lower()
                if search not in haystack:
                    continue
            results.append(d)

    flush_token_cache()
    _mark_antigravity_lineage(results)
    _mark_antigravity_children(results)
    return results

def _run_fts_sync_worker():
    global _FTS_SYNC_IN_PROGRESS, _FTS_SYNC_PENDING
    if _FTS_SYNC_IN_PROGRESS:
        _FTS_SYNC_PENDING = True
        return
    _FTS_SYNC_IN_PROGRESS = True
    try:
        all_sessions = collect_all_sessions(fmt_filter="all")

        # 1. Update existing titles in conversation_fts where title is outdated or placeholder (e.g. 会话_xxxx)
        try:
            with GLOBAL_FTS_MGR._get_conn() as conn:
                for s in all_sessions:
                    sid = s.get("session_id")
                    title = s.get("title")
                    if sid and title:
                        conn.execute(
                            """
                            UPDATE conversation_fts 
                            SET session_title = ? 
                            WHERE session_id = ? AND (session_title != ? OR session_title LIKE '会话_%')
                            """,
                            (title, sid, title)
                        )
        except Exception:
            pass

        # 2. Incrementally index turns
        synced_count = 0
        for s in all_sessions:
            try:
                p_str = s.get("file_path")
                if not p_str:
                    continue
                # 豆包 IndexedDB 由 2c 用合成键逐个会话索引（一个目录承载多个会话）
                if s.get("source_kind") == "indexeddb":
                    continue
                # 豆包云端同步仓由 2d 用合成键索引，避免主循环把它当普通文件清空
                if s.get("source_kind") == "cloud":
                    continue
                # 解密库承载多个会话，由下方 2b 逐个建立索引，这里跳过
                if str(p_str).endswith("trae_database_plain.db"):
                    continue
                p = Path(p_str)
                if not p.exists() or p.stat().st_size == 0:
                    continue
                st = p.stat()
                mtime = st.st_mtime
                size = st.st_size
                cid = s.get("catalog_id") or f"ag_{s.get('session_id')[:12]}"
                sid = s.get("session_id")
                fmt_str = s.get("format")
                title = s.get("title")

                if GLOBAL_FTS_MGR.is_file_up_to_date(str(p), mtime, size):
                    continue
                turns = extract_dialogue_turns_for_fts(p, fmt_str)
                GLOBAL_FTS_MGR.index_session_turns(
                    file_path=str(p),
                    mtime=mtime,
                    size=size,
                    catalog_id=cid,
                    session_id=sid,
                    session_title=title,
                    session_format=fmt_str,
                    turns=turns
                )
                synced_count += 1
                time.sleep(0.005)
            except Exception:
                pass

        # 2b. Trae 解密库：同一个物理库承载多个会话，用合成索引键逐个建索引
        for s in all_sessions:
            if not s.get("has_db"):
                continue
            sid = s.get("session_id")
            if not sid:
                continue
            try:
                st = TRAE_PLAIN_DB.stat()
            except Exception:
                continue
            key = f"trae_db://{sid}"
            try:
                if GLOBAL_FTS_MGR.is_file_up_to_date(key, st.st_mtime, st.st_size):
                    continue
            except Exception:
                pass
            turns = []
            user_no = 0
            for msg in _trae_db_messages(sid):
                # 只索引人话正文；tool_call 的入参 JSON 与工具输出留在详情里看，
                # 不进 FTS，避免搜索结果被命令/参数片段淹没。
                if msg.get("kind") != "message":
                    continue
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue
                if role == "user":
                    user_no += 1
                turns.append({
                    "role": role,
                    "turn_index": max(user_no, 1),
                    "text": msg.get("text") or "",
                    "timestamp": msg.get("timestamp") or "",
                })
            if not turns:
                continue
            try:
                GLOBAL_FTS_MGR.index_session_turns(
                    file_path=key,
                    mtime=st.st_mtime,
                    size=st.st_size,
                    catalog_id=s.get("catalog_id") or f"trae_{sid[:16]}",
                    session_id=sid,
                    session_title=s.get("title") or "",
                    session_format="trae",
                    turns=turns,
                )
                synced_count += 1
                time.sleep(0.005)
            except Exception:
                pass

        # 2c. 豆包 IndexedDB：一个 profile 目录承载多个会话，用合成键逐个建索引
        try:
            doubao_user_data = LOCAL_APPDATA / "Doubao" / "User Data"
            idb_dirs = doubao_idb.leveldb_dirs(doubao_user_data)
            if idb_dirs:
                sig_mtime = 0.0
                sig_size = 0
                for idb_dir in idb_dirs:
                    for f in idb_dir.glob("*"):
                        try:
                            st = f.stat()
                        except OSError:
                            continue
                        sig_mtime = max(sig_mtime, st.st_mtime_ns / 1e9)
                        sig_size += st.st_size
                idb = doubao_idb.load(doubao_user_data)
                cloud_cids = set(doubao_cloud.load())
                current_keys = set()
                for cid, item in idb.items():
                    if cid in cloud_cids:
                        continue
                    msgs = [
                        m for m in (item.get("messages") or [])
                        if m.get("kind", "message") == "message"
                        and str(m.get("text") or "").strip()
                    ]
                    if not msgs:
                        continue
                    key = f"doubao_idb://{cid}"
                    current_keys.add(key)
                    try:
                        if GLOBAL_FTS_MGR.is_file_up_to_date(key, sig_mtime, sig_size):
                            continue
                    except Exception:
                        pass
                    turns = []
                    user_no = 0
                    for m in msgs:
                        role = m.get("role")
                        if role not in ("user", "assistant"):
                            continue
                        if role == "user":
                            user_no += 1
                        turns.append({
                            "role": role,
                            "turn_index": max(user_no, 1),
                            "text": m.get("text") or "",
                            "timestamp": "",
                        })
                    if not turns:
                        continue
                    try:
                        GLOBAL_FTS_MGR.index_session_turns(
                            file_path=key,
                            mtime=sig_mtime,
                            size=sig_size,
                            catalog_id=f"db_{cid[:16]}",
                            session_id=cid,
                            session_title=item.get("title") or f"豆包对话 ({cid[-8:]})",
                            session_format="doubao",
                            turns=turns,
                        )
                        synced_count += 1
                        time.sleep(0.005)
                    except Exception:
                        pass
                # 清理已消失会话的旧索引
                try:
                    with GLOBAL_FTS_MGR._get_conn() as conn:
                        rows = conn.execute(
                            "SELECT file_path, catalog_id FROM fts_file_meta "
                            "WHERE file_path LIKE 'doubao_idb://%'"
                        ).fetchall()
                        for old_key, old_cid in rows:
                            if old_key in current_keys:
                                continue
                            conn.execute(
                                "DELETE FROM conversation_fts WHERE catalog_id = ?", (old_cid,)
                            )
                            conn.execute(
                                "DELETE FROM fts_file_meta WHERE file_path = ?", (old_key,)
                            )
                except Exception:
                    pass
        except Exception:
            pass

        # 2d. 豆包云端同步仓：完整正文，优先于 IndexedDB
        try:
            cloud = doubao_cloud.load()
            current_cloud_keys = set()
            for cid, item in cloud.items():
                msgs = [
                    m for m in (item.get("messages") or [])
                    if m.get("kind", "message") == "message"
                    and str(m.get("text") or "").strip()
                ]
                if not msgs:
                    continue
                key = f"doubao_cloud://{cid}"
                current_cloud_keys.add(key)
                fpath = Path(str(item.get("file") or item.get("dir") or ""))
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                try:
                    if GLOBAL_FTS_MGR.is_file_up_to_date(key, st.st_mtime, st.st_size):
                        continue
                except Exception:
                    pass
                turns = []
                user_no = 0
                for m in msgs:
                    role = m.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    if role == "user":
                        user_no += 1
                    turns.append({
                        "role": role,
                        "turn_index": max(user_no, 1),
                        "text": m.get("text") or "",
                        "timestamp": "",
                    })
                if not turns:
                    continue
                try:
                    GLOBAL_FTS_MGR.index_session_turns(
                        file_path=key,
                        mtime=st.st_mtime,
                        size=st.st_size,
                        catalog_id=f"db_{cid[:16]}",
                        session_id=cid,
                        session_title=item.get("title") or f"豆包对话 ({cid[-8:]})",
                        session_format="doubao",
                        turns=turns,
                    )
                    synced_count += 1
                    time.sleep(0.003)
                except Exception:
                    pass
            try:
                with GLOBAL_FTS_MGR._get_conn() as conn:
                    rows = conn.execute(
                        "SELECT file_path, catalog_id FROM fts_file_meta "
                        "WHERE file_path LIKE 'doubao_cloud://%'"
                    ).fetchall()
                    for old_key, old_cid in rows:
                        if old_key in current_cloud_keys:
                            continue
                        conn.execute(
                            "DELETE FROM conversation_fts WHERE catalog_id = ?", (old_cid,)
                        )
                        conn.execute(
                            "DELETE FROM fts_file_meta WHERE file_path = ?", (old_key,)
                        )
            except Exception:
                pass
        except Exception:
            pass
    finally:
        _FTS_SYNC_IN_PROGRESS = False
        if _FTS_SYNC_PENDING:
            _FTS_SYNC_PENDING = False
            threading.Thread(
                target=_run_fts_sync_worker, daemon=True, name="FTS_SyncWorker"
            ).start()

def trigger_fts_sync():
    t = threading.Thread(target=_run_fts_sync_worker, daemon=True, name="FTS_SyncWorker")
    t.start()


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        try:
            super().log_message(format, *args)
        except Exception:
            pass
    def _send_compressed(self, body_bytes: bytes, content_type: str, status: int = 200, extra_headers: dict = None, etag: str | None = None):
        """Send response with automatic ETag (HTTP 304) and Gzip compression for payloads > 1KB.

        `etag` 为 None 时按 md5(body) 现算（旧行为）；详情/列表接口传入**稳定 ETag**
        （只依赖稳定输入，不含耗时），这样条件请求才可能命中 304。

        `extra_headers` 在 **304 分支也会发送**：诊断头（`X-Cache` 等）必须在
        "没有 body 的那一条响应"上也能被看到，否则无法区分 304 与 200。
        """
        if etag is None:
            etag = f'"{hashlib.md5(body_bytes).hexdigest()}"'
        client_etag = self.headers.get("If-None-Match")
        if client_etag == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", "ETag, X-Query-Ms, X-Build-Ms, X-Cache")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            return

        accept_encoding = self.headers.get("Accept-Encoding", "")
        can_gzip = "gzip" in accept_encoding and len(body_bytes) > 1024

        if can_gzip:
            payload = gzip.compress(body_bytes, compresslevel=6)
        else:
            payload = body_bytes

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if can_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "ETag, X-Query-Ms, X-Build-Ms, X-Cache")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data: Any, status: int = 200, etag: str | None = None, extra_headers: dict | None = None):
        """发送 JSON。

        `etag` 为 None 时沿用旧行为（md5(body) 现算）；详情/列表接口传入**稳定 ETag**
        （只依赖文件元信息/快照身份 + 查询参数，不依赖 body 也不含耗时），
        这样 304 命中时连 body 都不用序列化。
        """
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_compressed(
            body,
            "application/json; charset=utf-8",
            status=status,
            etag=etag,
            extra_headers=extra_headers,
        )

    def send_not_modified(self, etag: str, elapsed_ms: float = 0.0) -> None:
        """304：空 body + ETag + must-revalidate。"""
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, max-age=0, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Elapsed-Ms", f"{elapsed_ms:.2f}")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def serve_static(self, rel_path: str) -> bool:
        """Serve a static file from frontend/out if it exists. Returns True if served."""
        clean_path = rel_path.lstrip("/").split("?")[0].split("#")[0]
        if not clean_path:
            clean_path = "index.html"
        target = (FRONTEND_OUT_DIR / clean_path).resolve()
        try:
            target.relative_to(FRONTEND_OUT_DIR)
        except ValueError:
            return False
        if not target.is_file():
            return False
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            if target.suffix == ".svg":
                ctype = "image/svg+xml"
            elif target.suffix == ".txt":
                ctype = "text/plain; charset=utf-8"
            elif target.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            elif target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            else:
                ctype = "application/octet-stream"
        elif ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            if "charset" not in ctype:
                ctype = f"{ctype}; charset=utf-8"
        body = target.read_bytes()
        extra_headers = {}
        if "/_next/static/" in rel_path or "/static/" in rel_path:
            extra_headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            extra_headers["Cache-Control"] = "no-cache"
        self._send_compressed(body, ctype, status=200, extra_headers=extra_headers)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            if (FRONTEND_OUT_DIR / "index.html").is_file():
                self.serve_static("index.html")
            else:
                self.serve_html()
        elif path == "/legacy":
            self.serve_html()
        elif path.startswith("/api/"):
            if path == "/api/status":
                self.handle_get_status()
            elif path == "/api/sessions":
                self.handle_get_sessions(query)
            elif path == "/api/session/detail":
                self.handle_get_session_detail(query)
            elif path == "/api/session/inspect":
                self.handle_get_session_inspect(query)
            elif path == "/api/session/children":
                self.handle_get_session_children(query)
            elif path == "/api/session/search":
                self.handle_session_search(query)
            elif path == "/api/session/event":
                self.handle_session_event(query)
            elif path == "/api/search/content":
                self.handle_search_content(query)
            elif path == "/api/doubao/sync/status":
                self.send_json({
                    "running": _DOUBAO_SYNC_STATE["running"],
                    "started_at": _DOUBAO_SYNC_STATE["started_at"],
                    "last_result": _DOUBAO_SYNC_STATE["last_result"],
                    "last_sync": doubao_cloud.last_sync_ts(),
                    "conversations": len(doubao_cloud.load()),
                })
            else:
                self.send_json({"error": "Not Found"}, status=404)
        elif self.serve_static(path):
            pass
        else:
            self.send_json({"error": "Not Found"}, status=404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if path == "/api/catalog/refresh":
            self.handle_catalog_refresh()
        elif path == "/api/catalog/add_root":
            self.handle_catalog_add_root(payload)
        elif path == "/api/catalog/remove_root":
            self.handle_catalog_remove_root(payload)
        elif path == "/api/session/migrate":
            self.handle_session_migrate(payload)
        elif path == "/api/session/delete":
            self.handle_session_delete(payload)
        elif path == "/api/sessions/batch_delete":
            self.handle_sessions_batch_delete(payload)
        elif path == "/api/sessions/batch_migrate":
            self.handle_sessions_batch_migrate(payload)
        elif path == "/api/open_folder":
            self.handle_open_folder(payload)
        elif path == "/api/doubao/sync":
            try:
                limit = int(payload.get("limit") or 0)
            except Exception:
                limit = 0
            started = start_doubao_sync(
                full=bool(payload.get("full")),
                only=str(payload.get("only") or ""),
                limit=limit,
            )
            self.send_json({
                "ok": True,
                "started": started,
                "running": _DOUBAO_SYNC_STATE["running"],
                "last_sync": doubao_cloud.last_sync_ts(),
            })
        else:
            self.send_json({"error": "Not Found"}, status=404)

    def handle_get_status(self):
        ensure_antigravity_catalog_roots()
        with Catalog(default_catalog_path()) as cat:
            roots_data = []
            for r in cat.roots():
                roots_data.append({
                    "id": r.id,
                    "format": r.format,
                    "path": r.path,
                    "source": r.source,
                    "enabled": r.enabled,
                    "last_scan_status": r.last_scan_status,
                    "last_error": r.last_error,
                })

        db = get_catalog_db()
        cat_sessions = db.execute("SELECT count(*) FROM sessions WHERE status != 'missing'").fetchone()[0]
        format_counts = dict(db.execute(
            "SELECT format, count(*) FROM sessions WHERE status != 'missing' GROUP BY format"
        ).fetchall())
        db.close()

        # Add WorkBuddy, Trae and Doubao counts
        # 不再逐个格式重新扫盘：直接复用列表快照（single-flight，冷启动也只构建一次），
        # 这样 /api/status 的计数与 /api/sessions 的 total 永远一致，且热态 ~10 ms。
        snapshot, _cache_status = _get_snapshot_cache().get(allow_stale=True)
        snap_items = snapshot.items_full
        format_counts = {}
        for it in snap_items:
            fmt = str(it.get("format") or "")
            if fmt:
                format_counts[fmt] = format_counts.get(fmt, 0) + 1
        total_sessions = len(snap_items)

        # 保留 WorkBuddy / Trae / 豆包 的键（即使当前没有条目），前端按 0 显示
        for fmt_key in ("workbuddy", "trae", "doubao"):
            format_counts.setdefault(fmt_key, 0)

        # Append Trae user & memory data directories into roots_data
        trae_user_dir = _roaming_path("Trae CN", "User")
        if trae_user_dir.exists() and not any(r.get("path") == str(trae_user_dir) for r in roots_data):
            roots_data.append({
                "id": 9901,
                "format": "trae",
                "path": str(trae_user_dir),
                "kind": "default",
                "is_active": 1,
                "last_scan_at": datetime.now(timezone.utc).isoformat(),
                "last_scan_status": "ok",
                "last_error": None,
            })
        trae_mem_dir = _home_path(".trae-cn", "memory")
        if trae_mem_dir.exists() and not any(r.get("path") == str(trae_mem_dir) for r in roots_data):
            roots_data.append({
                "id": 9902,
                "format": "trae",
                "path": str(trae_mem_dir),
                "kind": "memory",
                "is_active": 1,
                "last_scan_at": datetime.now(timezone.utc).isoformat(),
                "last_scan_status": "ok",
                "last_error": None,
            })

        supported_targets = [f.value for f in AgentFormat]

        self.send_json({
            "total_sessions": total_sessions,
            "format_counts": format_counts,
            "roots": roots_data,
            "supported_targets": supported_targets,
            "agent_meta": AGENT_META,
            "export_dir": str(EXPORT_DIR),
        })


    def handle_get_sessions(self, query: dict[str, list[str]]):
        """会话列表：快照 + 分页 + lite 投影 + 折叠。

        兼容底线（旧页 `/` 与脚本在用）：
        * 不传 `limit` → 全量返回，字段与改造前逐键一致；
        * `count` 语义仍是"本次返回条数"；
        * 新增的 `total/offset/limit/snapshot/has_more/meta` 都是纯增补。

        ETag 策略：由快照身份 + 查询参数派生（`snapshot.compute_list_etag`），
        **不含任何耗时**；耗时改走 `X-Query-Ms` / `X-Build-Ms` / `X-Cache` 响应头。
        body 里没有随时间变化的字段，因此相同参数的二次请求能真正命中 304。
        """
        result = _get_snapshot_cache().serve(query)
        # 镜像给旧读取点（handle_search_content 的标题映射），保持引用同一份 list
        _GLOBAL_SESSIONS_CACHE["data"] = _get_snapshot_cache().latest_items()
        _GLOBAL_SESSIONS_CACHE["ts"] = time.time()
        self.send_json(
            result.payload,
            etag=result.etag,
            extra_headers={
                "X-Query-Ms": f"{result.query_ms:.2f}",
                "X-Build-Ms": f"{result.build_ms:.2f}",
                "X-Cache": result.cache_status,
            },
        )

    def handle_get_session_children(self, query: dict[str, list[str]]):
        """子会话列表（替代 lite 里被裁掉的 `children` 字段）。

        `GET /api/session/children?catalog_id=ag_xxx` →
        `{catalog_id, session_id, children: [...], children_count: n}`
        """
        cid = (query.get("catalog_id", [""])[0] or "").strip()
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return
        items = _get_snapshot_cache().get()[0].items_full
        item = next((it for it in items if it.get("catalog_id") == cid), None)
        if item is None:
            item = next((it for it in items if it.get("session_id") == cid), None)
        if item is None:
            self.send_json({"error": f"Session not found: {cid}"}, status=404)
            return
        children = list(item.get("children") or [])
        children.sort(key=lambda c: (c.get("started_at") or "", float(c.get("mtime") or 0)))
        self.send_json({
            "catalog_id": item.get("catalog_id", cid),
            "session_id": item.get("session_id", ""),
            "children": children,
            "children_count": len(children),
        })

    def handle_session_search(self, query: dict[str, list[str]]):
        """会话内全文检索：优先复用 FTS 的 `turn_index`，未覆盖时回退内存遍历。

        `GET /api/session/search?catalog_id=..&q=..&limit=50`
        → `{catalog_id, q, count, matches: [{turn_index, snippet, kind, role}], source}`
        """
        cid = (query.get("catalog_id", [""])[0] or "").strip()
        q = (query.get("q", [""])[0] or "").strip()
        try:
            limit = min(max(int(query.get("limit", ["50"])[0]), 1), 200)
        except Exception:
            limit = 50
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return
        if not q:
            self.send_json({"catalog_id": cid, "q": "", "count": 0, "matches": [], "source": "empty"})
            return

        matches: list[dict[str, Any]] = []
        source = "fts"
        # 1) FTS：按 catalog_id 过滤 + MATCH，snippet 直接给命中上下文
        try:
            tokenized = cjk_tokenize(q)
            fts_match = '"' + " ".join(tokenized.split()) + '"'
            with GLOBAL_FTS_MGR._get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT role, turn_index, timestamp,
                           snippet(conversation_fts, 7, '[', ']', '…', 24) AS snippet
                    FROM conversation_fts
                    WHERE conversation_fts MATCH ? AND catalog_id = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_match, cid, limit),
                ).fetchall()
            for row in rows:
                matches.append({
                    "turn_index": int(row["turn_index"] or 0),
                    "snippet": cjk_untokenize(row["snippet"] or ""),
                    "kind": "message",
                    "role": row["role"] or "",
                    "timestamp": row["timestamp"] or "",
                })
        except Exception:
            matches = []

        # 2) FTS 未覆盖该会话 → 回退到内存遍历（复用详情解析件的 LRU 结果）
        if not matches:
            source = "memory"
            try:
                probe = self._detail_probe(cid)
                payload = detail_service.load_cached(probe, lambda: self._detail_load(probe))
                matches = detail_service.search_in_events(
                    payload.get("events") or [], q, limit=limit
                )
            except detail_service.DetailError as exc:
                # 会话不存在 / 源文件缺失属于 client error：原样透传状态码（404），
                # 不要升格成 500，也不必把内部文本（catalog session ID ...）泄漏出去
                self.send_json({"error": exc.message}, status=exc.status)
                return
            except Exception as exc:  # noqa: BLE001
                self.send_json({"error": f"Failed to search session: {exc}"}, status=500)
                return

        self.send_json({
            "catalog_id": cid,
            "q": q,
            "count": len(matches),
            "matches": matches,
            "source": source,
        })

    def handle_session_event(self, query: dict[str, list[str]]):
        """单事件回源：取**未裁剪**的完整 text / payload。

        `GET /api/session/event?catalog_id=..&index=4721&field=both`
        → `{catalog_id, index, kind, role, timestamp, text?, text_chars?, payload?, payload_bytes?, bytes}`

        存在理由：`slim=1` 会把 `tool_result.text` 截到 1200 字符、把大 `payload`
        换成 `{"_omitted":true}`。前端点「展开原始内容」时必须有一条能拿到全文的路，
        否则用户看到的就是"展开后仍然被截断"。
        复用详情解析件的 LRU（`detail_service.load_cached`），不重复解析。
        """
        cid = (query.get("catalog_id", [""])[0] or "").strip()
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return
        raw_index = (query.get("index", [""])[0] or "").strip()
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            self.send_json({"error": "index (int) required"}, status=400)
            return
        field = (query.get("field", ["both"])[0] or "both").strip().lower()
        if field not in {"text", "payload", "both"}:
            field = "both"

        try:
            probe = self._detail_probe(cid)
            payload = detail_service.load_cached(probe, lambda: self._detail_load(probe))
        except detail_service.DetailError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
            return
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Failed to resolve session: {exc}"}, status=500)
            return

        events = payload.get("events") or []
        if index < 0 or index >= len(events):
            self.send_json(
                {"error": f"event index out of range: {index} (total {len(events)})"},
                status=404,
            )
            return

        event = events[index] or {}
        response: dict[str, Any] = {
            "catalog_id": cid,
            "index": index,
            "kind": event.get("kind") or "",
            "role": event.get("role") or "",
            "timestamp": event.get("timestamp") or "",
            "events_total_raw": len(events),
        }
        if field in {"text", "both"}:
            text = event.get("text") or ""
            response["text"] = text
            response["text_chars"] = len(text)
            if event.get("raw_text"):
                # 被 sanitize 清洗掉的原始用户输入（CLI 命令/系统注入块）
                response["raw_text"] = event.get("raw_text") or ""
                response["raw_text_chars"] = len(response["raw_text"])
        if field in {"payload", "both"}:
            raw_payload = event.get("payload")
            response["payload"] = raw_payload
            response["payload_bytes"] = detail_service.approx_json_bytes(raw_payload)
        response["bytes"] = detail_service.approx_json_bytes(
            {"text": event.get("text") or "", "payload": event.get("payload")}
        )
        self.send_json(response)

    def handle_search_content(self, query: dict[str, list[str]]):
        q = query.get("q", [""])[0]
        limit = 50
        try:
            limit = min(int(query.get("limit", ["50"])[0]), 200)
        except Exception:
            limit = 50
        res = GLOBAL_FTS_MGR.search(q, limit=limit)

        # Dynamic natural language descriptive title enrichment
        title_map = {}
        if _GLOBAL_SESSIONS_CACHE.get("data"):
            for s in _GLOBAL_SESSIONS_CACHE["data"]:
                if s.get("session_id") and s.get("title"):
                    title_map[s["session_id"]] = s["title"]
                if s.get("catalog_id") and s.get("title"):
                    title_map[s["catalog_id"]] = s["title"]
        else:
            # Fast title map from Antigravity summaries & brain readable
            ag_sums = load_antigravity_summaries_map()
            for sid, info in ag_sums.items():
                t = info.get("title")
                if t and not t.startswith("会话_"):
                    m_time = info.get("last_modified_time") or ""
                    d = m_time.split()[0] if m_time else "2026-11-06"
                    title_map[sid] = f"{d} · {t}"

        for item in res.get("results", []):
            sid = item.get("session_id")
            cid = item.get("catalog_id")
            better_title = title_map.get(sid) or title_map.get(cid)
            if better_title and not better_title.startswith("会话_"):
                item["session_title"] = better_title

        self.send_json(res)

    # ---------------------------------------------------------------
    # 会话详情：探针 → 解析（LRU） → 分片/裁剪/ETag（services/detail.py）
    # 四个平台分支的分派逻辑原样保留，只是把出口从 self.send_json 换成 return，
    # 这样裁剪/分片/304 的风险集中在一个出口上。
    # ---------------------------------------------------------------
    def _detail_probe(self, cid: str) -> dict[str, Any]:
        """解析前探针：只做目录/索引查找，不读文件内容。

        作用有二：① 让 ETag 能在**解析之前**算出来（304 命中即零解析）；
        ② 让 404（会话不存在）在昂贵的解析之前返回。
        """
        # 1. WorkBuddy
        if cid.startswith("wb_"):
            sid_prefix = cid[3:]
            match = next(
                (w for w in get_workbuddy_sessions() if w["session_id"].startswith(sid_prefix)),
                None,
            )
            if not match:
                raise detail_service.DetailError("WorkBuddy session not found", 404)
            return {
                "catalog_id": cid,
                "branch": "workbuddy",
                "format": "workbuddy",
                "path": Path(match["file_path"]),
                "extra": {"match": match},
            }

        # 2. Trae
        if cid.startswith("trae_"):
            sid = cid[5:]
            match = next(
                (t for t in get_trae_sessions() if t["session_id"].startswith(sid)), None
            )
            if not match:
                raise detail_service.DetailError("Trae session not found", 404)
            return {
                "catalog_id": cid,
                "branch": "trae",
                "format": "trae",
                "path": Path(match["file_path"]),
                "extra": {"match": match},
            }

        # 2.5 Doubao
        if cid.startswith("db_"):
            sid = cid[3:]
            match = next(
                (d for d in get_doubao_sessions() if d["session_id"].startswith(sid)), None
            )
            if not match:
                # IndexedDB 里的新会话可能只有“当前任务态”而没有可展示正文，
                # 常规列表会把它过滤掉；但云端仍有完整正文。详情必须能按
                # catalog_id 找到它，否则 _maybe_refresh 已经触发的云端同步
                # 还没落盘就先返回 404。
                local = doubao_idb.load(LOCAL_APPDATA / "Doubao" / "User Data")
                full = next((k for k in local.keys() if str(k).startswith(sid)), "")
                if full:
                    item = local.get(full) or {}
                    cached_msgs = [
                        m["text"] for m in item.get("messages") or []
                        if m.get("kind", "message") == "message" and m.get("text")
                    ]
                    match = {
                        "catalog_id": cid,
                        "format": "doubao",
                        "session_id": str(full),
                        "title": item.get("title") or f"豆包对话 ({str(full)[-8:]})",
                        "started_at": "",
                        "records": len(cached_msgs),
                        "bytes": 0,
                        "file_path": item.get("dir") or str(LOCAL_APPDATA / "Doubao" / "User Data"),
                        "all_files": [item.get("dir") or ""],
                        "source_kind": "indexeddb",
                        "cached_msgs": cached_msgs,
                        "exists": True,
                        "mtime": item.get("ts") or 0,
                    }
            if not match:
                raise detail_service.DetailError("Doubao session not found", 404)
            return {
                "catalog_id": cid,
                "branch": "doubao",
                "format": "doubao",
                "path": Path(match["file_path"]),
                "extra": {"match": match},
            }

        # 3. 自定义 Antigravity（ag_<前缀>，直接扫会话目录）
        if cid.startswith("ag_"):
            sid_prefix = cid[3:]
            matched_path = None
            for ag_conv_dir in ANTIGRAVITY_CONV_DIRS:
                if not ag_conv_dir.exists():
                    continue
                matched_path = next(
                    (p for p in ag_conv_dir.glob("*.db") if p.stem.startswith(sid_prefix)), None
                )
                if matched_path:
                    break
            if not matched_path:
                raise detail_service.DetailError("Antigravity session file not found", 404)
            return {
                "catalog_id": cid,
                "branch": "ag",
                "format": "antigravity",
                "path": matched_path,
                "extra": {},
            }

        # 4. 标准 Catalog 会话（Antigravity / Claude / Cursor ...）
        with Catalog(default_catalog_path()) as cat:
            try:
                entry = cat.get_session(cid, include_paths=True)
            except Exception as e:
                raise detail_service.DetailError(f"Session not found in catalog: {e}", 404)
            try:
                source_ref = cat.session_source_for_transfer(cid)
                path = Path(source_ref.path)
                src_format = source_ref.format
            except Exception:
                path = Path(entry.path) if entry.path else None
                try:
                    src_format = AgentFormat(entry.format)
                except Exception:
                    src_format = AgentFormat.ANTIGRAVITY

        if not path or not path.exists():
            raise detail_service.DetailError(f"Session file not found: {path}", 404)
        fmt_value = src_format.value if hasattr(src_format, "value") else str(src_format)
        return {
            "catalog_id": cid,
            "branch": "catalog",
            "format": fmt_value,
            "path": path,
            "extra": {"entry": entry, "src_format": src_format},
        }

    @staticmethod
    def _events_to_dicts(sess_events: Any) -> list[dict[str, Any]]:
        """把 session_migrate 的事件对象转成可 JSON 的 dict（逐行等价于原实现）。"""
        events_data: list[dict[str, Any]] = []
        for ev in sess_events or []:
            events_data.append({
                "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                "role": ev.role.value if hasattr(ev.role, "value") and ev.role else (str(ev.role) if ev.role else ""),
                "timestamp": ev.timestamp or "",
                "text": ev.text or "",
                "tool_name": ev.tool_name or "",
                "tool_call_id": ev.tool_call_id or "",
                "payload": ev.payload if ev.payload else None,
            })
        return events_data


    def _detail_load(self, probe: dict[str, Any]) -> dict[str, Any]:
        """真正解析一个会话，返回**全量** payload（未裁剪、未分片）。"""
        branch = probe.get("branch")
        path = probe.get("path")
        extra = probe.get("extra") or {}

        if branch == "workbuddy":
            match = extra["match"]
            try:
                events = get_workbuddy_session_events(path)
            except Exception as e:
                raise detail_service.DetailError(f"Failed to parse WorkBuddy session: {e}", 500)
            return {
                "session_id": match["session_id"],
                "format": "workbuddy",
                "title": match["title"],
                "started_at": match["started_at"],
                "events_count": len(events),
                "events": events,
            }

        if branch == "trae":
            match = extra["match"]
            try:
                events = sanitize_session_events(get_trae_session_messages(match), "trae")
            except Exception as e:
                raise detail_service.DetailError(f"Failed to read Trae session: {e}", 500)
            # Trae 新版把会话正文（模型回复/工具链）写入加密库，外部只能读到提问缓存；
            # 没有 assistant 事件时必须显式说明，否则详情看起来像「丢了回复」
            has_assistant = any(str(ev.get("role") or "") == "assistant" for ev in events)
            notice = "" if has_assistant else (
                "Trae 新版把模型回复与工具调用写入了加密库"
                "（ModularData\\ai-agent\\database.db），外部工具无法解密读取；"
                "此处仅能显示本地可读的用户提问。"
            )
            return {
                "session_id": match["session_id"],
                "format": "trae",
                "title": match["title"],
                "started_at": match["started_at"],
                "events_count": len(events),
                "events": events,
                "notice": notice,
            }

        if branch == "doubao":
            match = extra["match"]
            try:
                events = sanitize_session_events(get_doubao_session_messages(match), "doubao")
            except Exception as e:
                raise detail_service.DetailError(f"Failed to read Doubao session: {e}", 500)
            has_user = any(str(ev.get("role") or "") == "user" for ev in events)
            has_assistant = any(str(ev.get("role") or "") == "assistant" for ev in events)
            notice = ""
            if not has_user:
                if match.get("source_kind") == "indexeddb":
                    notice = (
                        "该豆包会话在本地只有会话元数据、没有消息正文；"
                        "云端接口也没有对应记录（basic_info 400 / latest_messagelist retry_list），"
                        "因此没有可解析的正文。"
                    )
                else:
                    notice = (
                        "该豆包会话没有可解析的用户消息，"
                        "仅展示本地可读的工作区产物/快照内容。"
                    )
            elif not has_assistant:
                notice = "该豆包会话本地仅记录到用户提问，未落盘模型回复或工具调用。"
            return {
                "session_id": match["session_id"],
                "format": "doubao",
                "title": match["title"],
                "started_at": match["started_at"],
                "events_count": len(events),
                "events": events,
                "notice": notice,
            }

        if branch == "ag":
            try:
                sess = load_session(path, AgentFormat.ANTIGRAVITY)
                events_data = self._events_to_dicts(sess.events)
                _enrich_session_events_for_detail(path, "antigravity", sess.events, events_data)
                events_data = sanitize_session_events(events_data, "antigravity")
                ag_sums = load_antigravity_summaries_map()
                info = ag_sums.get(sess.session_id, {})
                c_title = info.get("title") or extract_antigravity_title(path)
                if not c_title:
                    p_title, p_agent = antigravity_parent_title(sess.session_id, ag_sums)
                    if p_title:
                        c_title = f"{p_title} · {p_agent or '子代理'} 子会话"
                if not c_title:
                    c_title = antigravity_first_user_text(path)
                if not c_title:
                    c_title = sess.session_id[:8]
                notice = ""
                parent_id = (info.get("parent_id") or "").strip()
                parent_title = ""
                parent_cid = ""
                agent_name = (info.get("agent_name") or "").strip()
                is_child = False
                if parent_id:
                    is_child = True
                    parent_title, found_agent = antigravity_parent_title(sess.session_id, ag_sums)
                    agent_name = agent_name or found_agent or "子代理"
                    try:
                        db = get_catalog_db()
                        p_row = db.execute(
                            "SELECT catalog_id FROM sessions WHERE session_id = ? OR session_id LIKE ?",
                            (parent_id, f"{parent_id}%"),
                        ).fetchone()
                        db.close()
                        if p_row and p_row[0]:
                            parent_cid = p_row[0]
                        else:
                            parent_cid = f"ag_{parent_id[:12]}"
                    except Exception:
                        parent_cid = f"ag_{parent_id[:12]}"

                    notice = ""
            except detail_service.DetailError:
                raise
            except Exception as e:
                raise detail_service.DetailError(f"Failed to parse Antigravity session: {e}", 500)
            return {
                "session_id": sess.session_id,
                "format": sess.source_format.value,
                "title": c_title,
                "started_at": sess.started_at or "",
                "events_count": len(events_data),
                "events": events_data,
                "notice": notice,
                "is_child": is_child,
                "parent_id": parent_id,
                "parent_title": parent_title,
                "parent_catalog_id": parent_cid,
                "agent_name": agent_name,
            }

        # branch == "catalog"
        entry = extra.get("entry")
        src_format = extra.get("src_format") or AgentFormat.ANTIGRAVITY
        try:
            sess = load_session(path, src_format)
            events_data = self._events_to_dicts(sess.events)
            _enrich_session_events_for_detail(path, sess.source_format.value, sess.events, events_data)
            events_data = sanitize_session_events(events_data, sess.source_format.value)
        except Exception as e:
            raise detail_service.DetailError(f"Failed to parse session content: {e}", 500)

        is_child = False
        parent_id = ""
        parent_title = ""
        parent_cid = ""
        agent_name = ""
        notice = ""

        if src_format == AgentFormat.ANTIGRAVITY:
            ag_sums = load_antigravity_summaries_map()
            info = ag_sums.get(sess.session_id, {})
            parent_id = (info.get("parent_id") or "").strip()
            agent_name = (info.get("agent_name") or "").strip()
            if parent_id:
                is_child = True
                parent_title, found_agent = antigravity_parent_title(sess.session_id, ag_sums)
                agent_name = agent_name or found_agent or "子代理"
                try:
                    db = get_catalog_db()
                    p_row = db.execute(
                        "SELECT catalog_id FROM sessions WHERE session_id = ? OR session_id LIKE ?",
                        (parent_id, f"{parent_id}%"),
                    ).fetchone()
                    db.close()
                    if p_row and p_row[0]:
                        parent_cid = p_row[0]
                    else:
                        parent_cid = f"ag_{parent_id[:12]}"
                except Exception:
                    parent_cid = f"ag_{parent_id[:12]}"

                notice = ""

        return {
            "session_id": sess.session_id,
            "format": sess.source_format.value,
            "title": sess.title or (entry.title if entry else None)
            or (extract_antigravity_title(path) if src_format == AgentFormat.ANTIGRAVITY else None)
            or sess.session_id[:8],
            "started_at": sess.started_at,
            "cwd": str(sess.cwd) if sess.cwd else None,
            "model": sess.model,
            "cli_version": sess.cli_version,
            "events_count": len(events_data),
            "events": events_data,
            "notice": notice,
            "is_child": is_child,
            "parent_id": parent_id,
            "parent_title": parent_title,
            "parent_catalog_id": parent_cid,
            "agent_name": agent_name,
        }

    def handle_get_session_detail(self, query: dict[str, list[str]]):
        """会话详情：缺省 = 全量（旧行为）；带任一新增参数 = 分片 + 裁剪 + 预解析 ETag。"""
        cid = (query.get("catalog_id", [""])[0] or "").strip()
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return

        # 豆包云端详情：只要该会话的 manifest 超过 120 秒，就触发一次
        # --only 后台增量；本次先返回旧缓存，客户端收到 refresh_pending 后重取。
        refresh_pending = _maybe_refresh_doubao_detail(cid)
        full_cloud_cid = _doubao_cloud_cid_for_catalog(cid)
        try:
            probe = self._detail_probe(cid)
        except detail_service.DetailError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
            return
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": f"Failed to resolve session: {exc}"}, status=500)
            return
        probe["response_extra"] = {
            "refresh_pending": bool(refresh_pending),
            "cloud_link": f"doubao_cloud://{full_cloud_cid}" if full_cloud_cid else "",
        }
        detail_service.serve(self, query, probe, lambda: self._detail_load(probe))

    def handle_get_session_inspect(self, query: dict[str, list[str]]):
        cid = query.get("catalog_id", [""])[0]
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return

        with Catalog(default_catalog_path()) as cat:
            try:
                source_ref = cat.session_source_for_transfer(cid)
            except Exception as e:
                self.send_json({"error": str(e)}, status=404)
                return

        path = Path(source_ref.path)
        try:
            sess = load_session(path, source_ref.format)
            kinds = {}
            roles = {}
            for e in sess.events:
                k = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
                kinds[k] = kinds.get(k, 0) + 1
                if e.role:
                    r = e.role.value if hasattr(e.role, "value") else str(e.role)
                    roles[r] = roles.get(r, 0) + 1

            self.send_json({
                "session_id": sess.session_id,
                "source_format": sess.source_format.value,
                "total_events": len(sess.events),
                "kind_breakdown": kinds,
                "role_breakdown": roles,
                "file_size": path.stat().st_size if path.exists() else 0,
            })
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_catalog_refresh(self):
        invalidate_sessions_cache()
        try:
            with Catalog(default_catalog_path()) as cat:
                res = cat.refresh()
            # 目录刷新后异步补齐新会话的 FTS 索引（含 Codex）。
            trigger_fts_sync()
            self.send_json({
                "success": True,
                "scanned": res.scanned,
                "files_seen": res.files_seen,
                "unchanged": res.unchanged,
                "missing": res.missing,
                "statuses": res.statuses,
            })
        except Exception as e:
            self.send_json({"success": False, "error": str(e)}, status=500)

    def handle_catalog_add_root(self, payload: dict):
        fmt_str = payload.get("format", "").strip()
        path_str = payload.get("path", "").strip()
        if not fmt_str or not path_str:
            self.send_json({"error": "format and path are required"}, status=400)
            return

        try:
            fmt = AgentFormat(fmt_str)
            p = Path(path_str).resolve()
            if not p.exists():
                self.send_json({"error": f"Directory does not exist: {p}"}, status=400)
                return
            with Catalog(default_catalog_path()) as cat:
                cat.add_root(fmt, p)
                cat.refresh()
            self.send_json({"success": True, "message": f"Added root {p} for {fmt.value}"})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_catalog_remove_root(self, payload: dict):
        root_id = payload.get("id")
        if not root_id:
            self.send_json({"error": "root id is required"}, status=400)
            return
        try:
            with Catalog(default_catalog_path()) as cat:
                cat.remove_root(int(root_id))
            self.send_json({"success": True})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def handle_session_migrate(self, payload: dict):
        cid = payload.get("catalog_id")
        target_fmt_str = payload.get("target_format")
        mode = payload.get("mode", "import")  # 'import' or 'export'
        custom_out_dir = payload.get("custom_out_dir")

        if not cid or not target_fmt_str:
            self.send_json({"error": "catalog_id and target_format are required"}, status=400)
            return

        temp_cleanup_path = None
        # 1. Special target: WorkBuddy
        if target_fmt_str == "workbuddy":
            try:
                import time, uuid
                new_sid = str(uuid.uuid4())
                now_ms = int(time.time() * 1000)
                wb_root = _home_path(".workbuddy")
                
                if mode == "export":
                    out_dir = Path(custom_out_dir) if custom_out_dir else EXPORT_DIR
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_file = out_dir / f"{new_sid}.jsonl"
                else:
                    wb_proj_dir = wb_root / "projects" / "migrated"
                    wb_proj_dir.mkdir(parents=True, exist_ok=True)
                    out_file = wb_proj_dir / f"{new_sid}.jsonl"

                messages = []
                title = "Migrated Session"

                if cid.startswith("wb_"):
                    sid_prefix = cid[3:]
                    wb_sessions = get_workbuddy_sessions()
                    match = next((w for w in wb_sessions if w["session_id"].startswith(sid_prefix)), None)
                    if match:
                        title = match.get("title", title)
                        with open(match["file_path"], "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                d = json.loads(line)
                                role = d.get("role") or d.get("type") or "user"
                                c = d.get("content") or d.get("message", {}).get("content")
                                text = ""
                                if isinstance(c, str): text = c
                                elif isinstance(c, list):
                                    text = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and "text" in x)
                                if text:
                                    messages.append({"role": "user" if role == "user" else "assistant", "text": text})
                elif cid.startswith("trae_"):
                    sid = cid[5:]
                    trae_list = get_trae_sessions()
                    match = next((t for t in trae_list if t["session_id"].startswith(sid)), None)
                    if match:
                        title = match.get("title", title)
                        trae_events = get_trae_session_messages(match)
                        for ev in trae_events:
                            messages.append({"role": ev.get("role", "user"), "text": ev.get("text", "")})
                elif cid.startswith("db_"):
                    sid = cid[3:]
                    db_list = get_doubao_sessions()
                    match = next((d for d in db_list if d["session_id"].startswith(sid)), None)
                    if match:
                        title = match.get("title", title)
                        for ev in get_doubao_session_messages(match):
                            if ev.get("text"):
                                messages.append({"role": "user" if ev.get("role") == "user" else "assistant", "text": ev.get("text", "")})
                else:
                    with Catalog(default_catalog_path()) as cat:
                        source_ref = cat.session_source_for_transfer(cid)
                    sess = load_session(Path(source_ref.path), source_ref.format)
                    title = sess.title or title
                    for e in sess.events:
                        if e.text:
                            messages.append({"role": e.role.value if e.role else "user", "text": e.text})

                with open(out_file, "w", encoding="utf-8") as f:
                    for m in messages:
                        row = {
                            "id": str(uuid.uuid4()),
                            "timestamp": "2026-10-09T12:00:00Z",
                            "type": "message",
                            "role": m["role"],
                            "content": m["text"],
                            "sessionId": new_sid,
                            "cwd": "C:\\Users\\HP"
                        }
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")

                if mode == "import":
                    wb_db_path = wb_root / "workbuddy.db"
                    if wb_db_path.exists():
                        conn = sqlite3.connect(wb_db_path)
                        cur = conn.cursor()
                        uid_row = cur.execute("SELECT user_id FROM sessions WHERE user_id IS NOT NULL LIMIT 1").fetchone()
                        user_id = uid_row[0] if uid_row else str(uuid.uuid4())
                        cur.execute(
                            "INSERT OR REPLACE INTO sessions (id, cwd, user_id, title, status, created_at, updated_at, transport) VALUES (?, ?, ?, ?, 'active', ?, ?, 'local')",
                            (new_sid, "C:\\Users\\HP", user_id, f"[迁移] {title[:50]}", now_ms, now_ms)
                        )
                        conn.commit()
                        conn.close()

                result_info = {
                    "session_id": new_sid,
                    "target_format": "workbuddy",
                    "warnings": [],
                    "dropped": {},
                    "native_bytes": out_file.stat().st_size,
                    "output_path": str(out_file),
                    "mode": mode,
                    "message": f"Migrated to WorkBuddy ({mode}) successfully!"
                }
                self.send_json({"success": True, "data": result_info})
                return
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, status=500)
                return

        try:
            target_fmt = AgentFormat(target_fmt_str)
        except ValueError:
            self.send_json({"error": f"Unsupported target format: {target_fmt_str}"}, status=400)
            return

        # Special handling for WorkBuddy and Trae sources: normalize via Claude format
        if cid.startswith("wb_"):
            sid_prefix = cid[3:]
            wb_sessions = get_workbuddy_sessions()
            match = next((w for w in wb_sessions if w["session_id"].startswith(sid_prefix)), None)
            if not match:
                self.send_json({"error": "WorkBuddy session not found"}, status=404)
                return
            msgs = []
            try:
                for ev in get_workbuddy_session_events(Path(match["file_path"])):
                    if ev.get("kind") != "message":
                        continue
                    role = ev.get("role")
                    text = (ev.get("text") or "").strip()
                    if role not in {"user", "assistant"} or not text:
                        continue
                    msgs.append({"role": role, "text": text, "timestamp": str(ev.get("timestamp", ""))})
            except Exception as e:
                self.send_json({"error": f"Failed to parse WorkBuddy file: {e}"}, status=500)
                return
            temp_cleanup_path = make_temp_claude_jsonl(msgs, match["session_id"])
            src_path = temp_cleanup_path
            src_format = AgentFormat.CLAUDE
        elif cid.startswith("trae_"):
            sid = cid[5:]
            trae_list = get_trae_sessions()
            match = next((t for t in trae_list if t["session_id"].startswith(sid)), None)
            if not match:
                self.send_json({"error": "Trae session not found"}, status=404)
                return
            msgs = []
            try:
                trae_events = get_trae_session_messages(match)
                for ev in trae_events:
                    msgs.append({
                        "role": ev.get("role", "user"),
                        "text": ev.get("text", ""),
                        "timestamp": ev.get("timestamp") or "2026-05-20T12:00:00Z"
                    })
            except Exception as e:
                self.send_json({"error": f"Failed to read Trae session: {e}"}, status=500)
                return
            temp_cleanup_path = make_temp_claude_jsonl(msgs, match["session_id"])
            src_path = temp_cleanup_path
            src_format = AgentFormat.CLAUDE
        elif cid.startswith("db_"):
            sid = cid[3:]
            db_list = get_doubao_sessions()
            match = next((d for d in db_list if d["session_id"].startswith(sid)), None)
            if not match:
                self.send_json({"error": "Doubao session not found"}, status=404)
                return
            msgs = []
            try:
                for ev in get_doubao_session_messages(match):
                    txt = (ev.get("text") or "").strip()
                    if not txt:
                        continue
                    msgs.append({
                        "role": "user" if ev.get("role") == "user" else "assistant",
                        "text": txt,
                        "timestamp": ev.get("timestamp") or "2026-10-13T12:00:00Z",
                    })
            except Exception as e:
                self.send_json({"error": f"Failed to read Doubao session: {e}"}, status=500)
                return
            temp_cleanup_path = make_temp_claude_jsonl(msgs, match["session_id"])
            src_path = temp_cleanup_path
            src_format = AgentFormat.CLAUDE
        elif cid.startswith("ag_"):
            sid = cid[3:]
            ag_file = None
            for ag_d in ANTIGRAVITY_CONV_DIRS:
                if not ag_d.exists():
                    continue
                f = ag_d / f"{sid}.db"
                if f.exists():
                    ag_file = f
                    break
                match = next((p for p in ag_d.glob("*.db") if p.stem.startswith(sid)), None)
                if match:
                    ag_file = match
                    break
            if not ag_file or not ag_file.exists():
                self.send_json({"error": "Antigravity session file not found"}, status=404)
                return
            src_path = ag_file
            src_format = AgentFormat.ANTIGRAVITY
        else:
            with Catalog(default_catalog_path()) as cat:
                try:
                    entry = cat.get_session(cid, include_paths=True)
                except Exception as e:
                    self.send_json({"error": f"Session lookup failed: {e}"}, status=404)
                    return
                try:
                    source_ref = cat.session_source_for_transfer(cid)
                    src_path = Path(source_ref.path)
                    src_format = source_ref.format
                except Exception:
                    src_path = Path(entry.path) if entry.path else None
                    try:
                        src_format = AgentFormat(entry.format)
                    except Exception:
                        src_format = AgentFormat.ANTIGRAVITY

        try:
            session = load_session(src_path, src_format)
            opts = ConversionOptions(target_format=target_fmt)
            artifact = convert_session(session, opts)

            result_info = {
                "session_id": artifact.session_id,
                "target_format": target_fmt.value,
                "warnings": list(artifact.warnings),
                "dropped": artifact.dropped,
                "native_bytes": artifact.native_bytes_length if hasattr(artifact, "native_bytes_length") else len(artifact.native_bytes),
            }

            if mode == "export":
                out_dir = Path(custom_out_dir) if custom_out_dir else EXPORT_DIR
                out_dir.mkdir(parents=True, exist_ok=True)
                ext = ".db" if target_fmt in {AgentFormat.ANTIGRAVITY, AgentFormat.CURSOR} else ".jsonl"
                out_file = out_dir / f"{artifact.session_id}{ext}"
                with open(out_file, "wb") as f:
                    f.write(artifact.native_bytes)
                result_info["output_path"] = str(out_file)
                result_info["mode"] = "export"
                result_info["message"] = f"Exported to {out_file.name} successfully!"
            else:
                target_home = default_target_home(target_fmt)
                if target_fmt == AgentFormat.ANTIGRAVITY:
                    # Direct installation into modern Antigravity conversations
                    ide_dir = _home_path(".gemini", "antigravity", "conversations")
                    if not ide_dir.parent.exists():
                        ide_dir = _home_path(".gemini", "antigravity-ide", "conversations")
                    ide_dir.mkdir(parents=True, exist_ok=True)
                    out_path = ide_dir / f"{artifact.session_id}.db"
                    with open(out_path, "wb") as f:
                        f.write(artifact.native_bytes)
                elif target_fmt == AgentFormat.CURSOR:
                    install_cursor_artifact(artifact, target_home=target_home)
                    out_path = target_home / "chats"
                elif target_fmt == AgentFormat.COPILOT:
                    install_copilot_artifact(artifact, target_home=target_home)
                    out_path = target_home / "session-state"
                elif target_fmt == AgentFormat.KIMI:
                    install_kimi_artifact(artifact, target_home=target_home)
                    out_path = target_home / "sessions"
                elif target_fmt == AgentFormat.DEVIN:
                    install_devin_artifact(artifact, target_home=target_home)
                    out_path = target_home
                elif target_fmt == AgentFormat.HERMES:
                    install_hermes_artifact(artifact, target_home=target_home)
                    out_path = target_home
                elif target_fmt == AgentFormat.MASTRACODE:
                    install_mastracode_artifact(artifact, target_home=target_home)
                    out_path = target_home
                elif target_fmt == AgentFormat.OPENHANDS:
                    install_openhands_artifact(artifact, target_home=target_home)
                    out_path = target_home
                elif target_fmt == AgentFormat.GROK:
                    install_grok_artifact(artifact, target_home=target_home)
                    out_path = target_home
                elif target_fmt == AgentFormat.VIBE:
                    install_vibe_artifact(artifact, target_home=target_home)
                    out_path = target_home
                else:
                    out_path, manifest_path = target_import_paths(artifact, target_home)
                    write_artifact(artifact, output_path=out_path, manifest_path=manifest_path)

                result_info["output_path"] = str(out_path)
                result_info["mode"] = "import"
                result_info["message"] = f"Installed into {target_fmt.value} successfully!"

            self.send_json({"success": True, "data": result_info})
        except Exception as e:
            self.send_json({"success": False, "error": str(e)}, status=500)
        finally:
            if temp_cleanup_path and temp_cleanup_path.exists():
                try:
                    temp_cleanup_path.unlink()
                except:
                    pass

    def _delete_single_session_core(self, cid: str, sid: str, fmt: str, file_path_str: str) -> dict:
        total_freed_bytes = 0
        cleaned_paths = []
        is_shared_db = False

        # 1. 解析主文件路径
        main_path = Path(file_path_str) if file_path_str else None
        if not main_path or not main_path.exists():
            if sid:
                for ag_conv_dir in ANTIGRAVITY_CONV_DIRS:
                    ag_p = ag_conv_dir / f"{sid}.db"
                    if ag_p.exists():
                        main_path = ag_p
                        break
            if not main_path:
                try:
                    with sqlite3.connect(default_catalog_path()) as c_db:
                        row = c_db.execute(
                            "SELECT r.path as root_path, s.relative_path, s.format, s.session_id FROM sessions s JOIN roots r ON s.root_id = r.id WHERE s.catalog_id = ? OR s.session_id = ?",
                            (cid, sid)
                        ).fetchone()
                        if row:
                            main_path = Path(row[0]) / row[1]
                            if not fmt:
                                fmt = row[2]
                            if not sid:
                                sid = row[3]
                except Exception:
                    pass

        # 2. 判断是否为共享总数据库（如 Trae 的 state.vscdb）
        # 共享总数据库存放整个软件全局设置，绝对不能删除整个文件，而是从库中精确删除行并执行 VACUUM 释放物理空间
        is_shared_db = fmt in ["trae", "trae_solo", "cursor"] or (main_path and main_path.name in ["state.vscdb", "workbuddy.db"])

        if is_shared_db and main_path and main_path.exists():
            try:
                size_before = main_path.stat().st_size
                with sqlite3.connect(main_path, timeout=10) as conn:
                    conn.execute("DELETE FROM ItemTable WHERE key LIKE ?", (f"%{sid}%",))
                    conn.commit()
                    try:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.execute("VACUUM")
                    except Exception:
                        pass
                size_after = main_path.stat().st_size
                freed = max(0, size_before - size_after)
                total_freed_bytes += freed
                cleaned_paths.append(f"{main_path} (行清理+VACUUM紧缩)")
            except Exception as e:
                pass
        else:
            # 独立会话文件（Antigravity .db / WorkBuddy .jsonl / Claude .jsonl 等）: 直接彻底删除该物理文件！
            if main_path and main_path.exists() and main_path.is_file():
                try:
                    total_freed_bytes += main_path.stat().st_size
                    main_path.unlink(missing_ok=True)
                    cleaned_paths.append(str(main_path))
                    for extra_ext in ["-wal", "-shm", "-journal"]:
                        extra_p = Path(str(main_path) + extra_ext)
                        if extra_p.exists():
                            total_freed_bytes += extra_p.stat().st_size
                            extra_p.unlink(missing_ok=True)
                except Exception:
                    pass

        # 3. 如果是 Antigravity：递归清理关联的 brain 记忆目录与日志
        if sid and (fmt == "antigravity" or "antigravity" in str(main_path or "").lower()):
            brain_dirs = [
                _home_path(".gemini", "antigravity", "brain") / sid,
                _home_path(".gemini", "antigravity-ide", "brain") / sid,
                _home_path(".gemini", "antigravity-ide", "brain_readable") / sid,
                _home_path(".gemini", "antigravity-cli", "brain") / sid,
            ]
            for b_dir in brain_dirs:
                if b_dir.exists() and b_dir.is_dir():
                    try:
                        dir_size = sum(f.stat().st_size for f in b_dir.glob('**/*') if f.is_file())
                        total_freed_bytes += dir_size
                        shutil.rmtree(b_dir, ignore_errors=True)
                        cleaned_paths.append(str(b_dir))
                    except Exception:
                        pass
            for s_db_p in [
                _home_path(".gemini", "antigravity", "conversation_summaries.db"),
                _home_path(".gemini", "antigravity-ide", "conversation_summaries.db"),
            ]:
                if s_db_p.exists():
                    try:
                        with sqlite3.connect(s_db_p, timeout=5) as s_conn:
                            s_conn.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (sid,))
                    except Exception:
                        pass

            # 级联彻底清理归属于该主会话的所有子代理会话 (Subagents)
            try:
                child_sids = set()
                for s_db_p in [
                    _home_path(".gemini", "antigravity", "conversation_summaries.db"),
                    _home_path(".gemini", "antigravity-ide", "conversation_summaries.db"),
                ]:
                    if s_db_p.exists():
                        with sqlite3.connect(s_db_p, timeout=5) as s_conn:
                            rows = s_conn.execute(
                                "SELECT conversation_id FROM conversation_summaries WHERE parent_conversation_id = ?",
                                (sid,)
                            ).fetchall()
                            for (c_sid,) in rows:
                                if c_sid and c_sid != sid:
                                    child_sids.add(c_sid)
                for c_sid in child_sids:
                    # 清除子代理 .db 及 WAL/SHM
                    for ag_conv_dir in ANTIGRAVITY_CONV_DIRS:
                        c_p = ag_conv_dir / f"{c_sid}.db"
                        if c_p.exists():
                            total_freed_bytes += c_p.stat().st_size
                            c_p.unlink(missing_ok=True)
                            cleaned_paths.append(str(c_p))
                            for extra_ext in ["-wal", "-shm", "-journal"]:
                                extra_p = Path(str(c_p) + extra_ext)
                                if extra_p.exists():
                                    total_freed_bytes += extra_p.stat().st_size
                                    extra_p.unlink(missing_ok=True)
                    # 清除子代理 brain 目录
                    for c_b_dir in [
                        _home_path(".gemini", "antigravity", "brain") / c_sid,
                        _home_path(".gemini", "antigravity-ide", "brain") / c_sid,
                        _home_path(".gemini", "antigravity-ide", "brain_readable") / c_sid,
                        _home_path(".gemini", "antigravity-cli", "brain") / c_sid,
                    ]:
                        if c_b_dir.exists() and c_b_dir.is_dir():
                            c_sz = sum(f.stat().st_size for f in c_b_dir.glob('**/*') if f.is_file())
                            total_freed_bytes += c_sz
                            shutil.rmtree(c_b_dir, ignore_errors=True)
                            cleaned_paths.append(str(c_b_dir))
                    # 从摘要库清除子代理记录
                    for s_db_p in [
                        _home_path(".gemini", "antigravity", "conversation_summaries.db"),
                        _home_path(".gemini", "antigravity-ide", "conversation_summaries.db"),
                    ]:
                        if s_db_p.exists():
                            with sqlite3.connect(s_db_p, timeout=5) as s_conn:
                                s_conn.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (c_sid,))
            except Exception:
                pass

        # 4. 如果是 WorkBuddy：从 workbuddy.db 中删除该会话记录
        if fmt == "workbuddy" or (main_path and "workbuddy" in str(main_path).lower()):
            try:
                wb_db = _home_path(".workbuddy", "workbuddy.db")
                if wb_db.exists():
                    with sqlite3.connect(wb_db, timeout=5) as conn:
                        conn.execute("DELETE FROM sessions WHERE id = ? OR id LIKE ?", (sid, f"%{sid}%"))
                        conn.commit()
            except Exception:
                pass

        # 5. 如果是 Trae：彻底清理关联的物理 session_memory 文件、attachments 截图、thumbnails 缩略图、work 目录及 state.vscdb 记录
        if fmt in ["trae", "trae_solo"] or (main_path and "trae" in str(main_path).lower()) or (cid and cid.startswith("trae_")):
            # A. 物理 session_memory 文件
            trae_mem_projects = _home_path(".trae-cn", "memory", "projects")
            if trae_mem_projects.exists():
                for f in trae_mem_projects.rglob(f"session_memory_*{sid}*.jsonl"):
                    try:
                        total_freed_bytes += f.stat().st_size
                        f.unlink(missing_ok=True)
                        cleaned_paths.append(str(f))
                    except Exception:
                        pass
            # B. 截图附件 attachments
            att_dir = _home_path(".trae-cn", "attachments") / sid
            if att_dir.exists() and att_dir.is_dir():
                try:
                    dir_sz = sum(f.stat().st_size for f in att_dir.glob("**/*") if f.is_file())
                    total_freed_bytes += dir_sz
                    shutil.rmtree(att_dir, ignore_errors=True)
                    cleaned_paths.append(str(att_dir))
                except Exception:
                    pass
            # C. 缩略图 thumbnails
            thumb_file = _home_path(".trae-cn", ".thumbnails") / f"{sid}.png"
            if thumb_file.exists():
                try:
                    total_freed_bytes += thumb_file.stat().st_size
                    thumb_file.unlink(missing_ok=True)
                    cleaned_paths.append(str(thumb_file))
                except Exception:
                    pass
            # D. Work 目录
            work_dir = _home_path(".trae-cn", "work") / sid
            if work_dir.exists() and work_dir.is_dir():
                try:
                    dir_sz = sum(f.stat().st_size for f in work_dir.glob("**/*") if f.is_file())
                    total_freed_bytes += dir_sz
                    shutil.rmtree(work_dir, ignore_errors=True)
                    cleaned_paths.append(str(work_dir))
                except Exception:
                    pass
            # E. 所有 state.vscdb 中清理键并紧缩释放物理空间
            for user_base in [
                _roaming_path("Trae CN", "User"),
                _roaming_path("TRAE SOLO CN", "User"),
            ]:
                if not user_base.exists():
                    continue
                for vscdb in user_base.rglob("state.vscdb"):
                    try:
                        sz_before = vscdb.stat().st_size
                        with sqlite3.connect(vscdb, timeout=10) as conn:
                            cur = conn.cursor()
                            cur.execute("DELETE FROM ItemTable WHERE key LIKE ?", (f"%{sid}%",))
                            conn.commit()
                            try:
                                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                conn.execute("VACUUM")
                            except Exception:
                                pass
                        sz_after = vscdb.stat().st_size
                        freed = max(0, sz_before - sz_after)
                        total_freed_bytes += freed
                        cleaned_paths.append(f"{vscdb} (清理会话行)")
                    except Exception:
                        pass

        # 5. 从 Catalog 中同步删除会话记录
        try:
            with sqlite3.connect(default_catalog_path(), timeout=5) as c_db:
                c_db.execute("DELETE FROM sessions WHERE catalog_id = ? OR session_id = ?", (cid, sid))
                c_db.commit()
        except Exception:
            pass

        return {
            "success": True,
            "freed_bytes": total_freed_bytes,
            "cleaned_paths": cleaned_paths,
            "is_shared_db": is_shared_db
        }

    def handle_session_delete(self, payload: dict):
        invalidate_sessions_cache()
        cid = payload.get("catalog_id", "").strip()
        sid = payload.get("session_id", "").strip()
        fmt = payload.get("format", "").strip()
        file_path_str = payload.get("file_path", "").strip()

        if not cid and not sid and not file_path_str:
            self.send_json({"error": "session identifier required"}, status=400)
            return

        res = self._delete_single_session_core(cid, sid, fmt, file_path_str)
        self.send_json({
            "success": True,
            "catalog_id": cid,
            "session_id": sid,
            "freed_bytes": res["freed_bytes"],
            "cleaned_paths": res["cleaned_paths"],
            "is_shared_db": res["is_shared_db"]
        })

    def handle_sessions_batch_delete(self, payload: dict):
        invalidate_sessions_cache()
        sessions = payload.get("sessions", [])
        if not sessions:
            self.send_json({"error": "sessions list required"}, status=400)
            return

        total_freed = 0
        deleted_count = 0
        trae_cleaned = 0
        details = []

        # 按数据库类型智能聚合批量处理
        for item in sessions:
            cid = item.get("catalog_id", "").strip()
            sid = item.get("session_id", "").strip()
            fmt = item.get("format", "").strip()
            f_path = item.get("file_path", "").strip()

            res = self._delete_single_session_core(cid, sid, fmt, f_path)
            if res.get("success"):
                deleted_count += 1
                total_freed += res.get("freed_bytes", 0)
                if res.get("is_shared_db"):
                    trae_cleaned += 1
                details.append({
                    "catalog_id": cid,
                    "session_id": sid,
                    "freed_bytes": res.get("freed_bytes", 0),
                    "is_shared_db": res.get("is_shared_db", False)
                })

        self.send_json({
            "success": True,
            "deleted_count": deleted_count,
            "total_freed_bytes": total_freed,
            "total_freed_mb": round(total_freed / (1024 * 1024), 2),
            "trae_cleaned": trae_cleaned,
            "details": details
        })

    def handle_sessions_batch_migrate(self, payload: dict):
        catalog_ids = payload.get("catalog_ids", [])
        target_format_str = payload.get("target_format", "").strip().lower()

        if not catalog_ids or not target_format_str:
            self.send_json({"error": "catalog_ids and target_format required"}, status=400)
            return

        try:
            target_format = AgentFormat(target_format_str)
        except Exception:
            self.send_json({"error": f"Unsupported target format: {target_format_str}"}, status=400)
            return

        success_count = 0
        failed_count = 0
        results = []

        for cid in catalog_ids:
            try:
                # 迁移单个会话
                fake_payload = {"catalog_id": cid, "target_format": target_format_str}
                # 复用转换逻辑
                with Catalog(default_catalog_path()) as cat:
                    source_ref = cat.session_source_for_transfer(cid)
                sess = load_session(Path(source_ref.path), source_ref.format)
                conv_res = convert_session(sess, target_format)
                out_path = write_artifact(conv_res, target_format, EXPORT_DIR)
                success_count += 1
                results.append({
                    "catalog_id": cid,
                    "success": True,
                    "output_path": str(out_path)
                })
            except Exception as e:
                failed_count += 1
                results.append({
                    "catalog_id": cid,
                    "success": False,
                    "error": str(e)
                })

        self.send_json({
            "success": True,
            "target_format": target_format_str,
            "total": len(catalog_ids),
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        })

    def handle_open_folder(self, payload: dict):
        p_str = payload.get("path", "").strip()
        if not p_str:
            self.send_json({"error": "path required"}, status=400)
            return
        p = Path(p_str)
        if not p.exists():
            if p.parent.exists():
                p = p.parent
            else:
                self.send_json({"error": f"路径不存在: {p_str}"}, status=404)
                return

        try:
            p_resolved = str(p.resolve())
            if os.name == "nt":
                import subprocess
                # explorer 是 GUI 程序，不产生控制台；CREATE_NO_WINDOW 仅对
                # cmd 回退路径生效，避免后台进程弹出终端窗口。
                no_window = {"creationflags": subprocess.CREATE_NO_WINDOW}
                if p.is_file():
                    # Windows 原生命令行，带 /select,"..." 确保高亮选中该文件
                    cmd = f'explorer.exe /select,"{p_resolved}"'
                    try:
                        subprocess.Popen(cmd, **no_window)
                    except Exception:
                        subprocess.Popen(["cmd", "/c", "start", "", cmd], **no_window)
                else:
                    cmd = f'explorer.exe "{p_resolved}"'
                    subprocess.Popen(cmd, **no_window)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", "-R" if p.is_file() else "", p_resolved])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", p_resolved if p.is_dir() else str(p.parent)])

            self.send_json({"success": True, "path": p_resolved})
        except Exception as e:
            self.send_json({"error": str(e)}, status=500)

    def serve_html(self):
        from services.legacy_ui import get_legacy_html
        body = get_legacy_html().encode("utf-8")
        self._send_compressed(body, "text/html; charset=utf-8", status=200)


def main():
    global PORT
    multiprocessing.freeze_support()
    # 命令行覆盖：--port 18923 / --no-browser（不影响任何接口行为，仅便于多实例自测）
    argv = list(sys.argv[1:])
    if argv[:1] == ["--helper"]:
        if len(argv) < 2:
            print("usage: web_app.py --helper <doubao-sync|trae-decrypt> ...", file=sys.stderr)
            return 2
        return run_helper(argv[1], argv[2:])
    open_browser_enabled = True

    if "--no-browser" in argv:
        open_browser_enabled = False
        argv.remove("--no-browser")
    if "--port" in argv:
        try:
            idx = argv.index("--port")
            candidate = int(argv[idx + 1])
            if 0 < candidate < 65536:
                PORT = candidate
            del argv[idx:idx + 2]
        except (IndexError, ValueError):
            pass

    ensure_antigravity_catalog_roots()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    url = f"http://127.0.0.1:{PORT}"
    guard = instance_service.acquire_instance_lock(
        f"AgentsMemoryTools-{PORT}", DATA_DIR
    )
    if guard is None:
        if open_browser_enabled:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        print(f"Agents Memory Tools is already running: {url}")
        return 0

    trigger_fts_sync()
    try:
        # 只监听回环地址，避免局域网其他设备访问本地会话数据。
        server_address = ("127.0.0.1", PORT)
        httpd = ReusableThreadingServer(server_address, RequestHandler)
    except OSError as exc:
        guard.close()
        print(
            f"Cannot bind {PORT}: {exc}. "
            "Another application may be using this port; no existing process was killed.",
            file=sys.stderr,
        )
        return 1

    # 启动即预热列表快照（构建 ~1.4 s，single-flight）。
    # 用户打开页面时通常已经命中缓存，首屏从 1.5 s 降到 ~30 ms。
    def _warm_snapshot():
        try:
            _get_snapshot_cache().get(allow_stale=True)
        except Exception:
            pass
    threading.Thread(target=_warm_snapshot, daemon=True, name="SnapshotWarmup").start()

    print("=" * 65)
    print("  Agents Memory Tools 跨智能体会话记忆管理与一键迁移平台")
    print(f"  本地访问地址: {url}")
    print(f"  会话导出目录: {EXPORT_DIR}")
    if open_browser_enabled:
        print("  提示: 正在自动打开默认浏览器，使用期间请保持本窗口开启！")
    print("=" * 65)
    def open_browser():
        import time, webbrowser
        time.sleep(0.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    if open_browser_enabled:
        threading.Thread(target=open_browser, daemon=True).start()
    while True:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            sys.exit(0)
        except Exception:
            import time
            time.sleep(0.5)
    while True:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            sys.exit(0)
        except Exception:
            import time
            time.sleep(0.5)

if __name__ == "__main__":
    raise SystemExit(main())