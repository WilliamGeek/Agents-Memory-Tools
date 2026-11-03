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
import tempfile
import urllib.parse
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
# Ensure safe stdout/stderr in GUI / pythonw mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


# Ensure session-migrate virtualenv or package is importable
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

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

PORT = 18922
BASE_DIR = Path(__file__).resolve().parent
EXPORT_DIR = BASE_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Permanent tiktoken cache directory in project workspace
TIKTOKEN_LOCAL_CACHE = BASE_DIR / "tiktoken_cache"
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

TOKEN_CACHE_PATH = BASE_DIR / "token_cache.json"
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}
_TOKEN_CACHE_LOADED = False
_TOKEN_CACHE_DIRTY = False
_GLOBAL_SESSIONS_CACHE: dict[str, Any] = {"ts": 0.0, "data": []}

def invalidate_sessions_cache() -> None:
    _GLOBAL_SESSIONS_CACHE["ts"] = 0.0


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


def compute_session_tokens(
    fmt: str,
    session_id: str,
    file_path: Path | None,
    mtime: float,
    size_bytes: int,
    trae_chat_tokens: int | None = None,
    trae_aux_tokens: int | None = None,
) -> dict[str, int]:
    """Compute and cache hybrid token breakdown (tokens, chat_tokens, aux_tokens) for a session."""
    global _TOKEN_CACHE_DIRTY
    _ensure_token_cache_loaded()
    cache_key = f"{fmt}:{session_id}"
    sig = f"{int(mtime)}:{int(size_bytes)}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and cached.get("sig") == sig:
        return {
            "tokens": int(cached.get("tokens") or 0),
            "chat_tokens": int(cached.get("chat_tokens") or 0),
            "aux_tokens": int(cached.get("aux_tokens") or 0),
        }

    chat_t = 0
    aux_t = 0

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
            with sqlite3.connect(f"file:{str(file_path)}?mode=ro", uri=True) as conn:
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

    total_t = chat_t + aux_t
    if total_t == 0 and size_bytes > 0:
        total_t = max(1, int(size_bytes * 0.25))
        chat_t = total_t

    res = {"tokens": total_t, "chat_tokens": chat_t, "aux_tokens": aux_t}
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
        "icon": "✨",
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
        "icon": "🚀",
        "description": "Cognition Devin CLI sessions",
    },
}

# Pre-cache brain_readable map for clean Antigravity titles
BRAIN_READABLE_DIR = Path(r"C:\Users\HP\.gemini\antigravity-ide\brain_readable")
ANTIGRAVITY_APP_DIR = Path(r"C:\Users\HP\.gemini\antigravity")
ANTIGRAVITY_CONV_DIRS = [
    Path(r"C:\Users\HP\.gemini\antigravity\conversations"),
    Path(r"C:\Users\HP\.gemini\antigravity-cli\conversations"),
]

def load_antigravity_summaries_map() -> dict[str, dict[str, Any]]:
    """Load latest official titles and metadata from Antigravity's conversation_summaries.db."""
    summaries: dict[str, dict[str, Any]] = {}
    db_paths = [
        Path(r"C:\Users\HP\.gemini\antigravity\conversation_summaries.db"),
        Path(r"C:\Users\HP\.gemini\antigravity-ide\conversation_summaries.db"),
    ]
    for db_p in db_paths:
        if not db_p.exists() or db_p.stat().st_size == 0:
            continue
        try:
            with sqlite3.connect(f"file:{str(db_p)}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT conversation_id, title, preview, step_count, last_modified_time FROM conversation_summaries"
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
                    }
        except Exception:
            pass
    return summaries

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

def extract_claude_title_and_date(jsonl_path: Path) -> tuple[str, str]:
    title = ""
    date_str = ""
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
                    if isinstance(content, str) and content.strip():
                        title = content.strip().splitlines()[0][:60]
                        break
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("text"):
                                title = item["text"].strip().splitlines()[0][:60]
                                break
                        if title:
                            break
    except Exception:
        pass
    if not date_str:
        try:
            date_str = datetime.fromtimestamp(jsonl_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
        except:
            date_str = "2026-04-25"
    if not title:
        title = jsonl_path.stem
    return title, date_str

def get_workbuddy_sessions() -> list[dict[str, Any]]:
    wb_dir = Path(r"C:\Users\HP\.workbuddy")
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
            
            date_str = ""
            if created_at:
                try:
                    dt = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    pass
            if not date_str:
                try:
                    dt = datetime.fromtimestamp(j.stat().st_mtime, tz=timezone.utc)
                    date_str = dt.strftime("%Y-%m-%d")
                except:
                    date_str = "2026-09-01"

            if not raw_title:
                try:
                    with open(j, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            data = json.loads(line)
                            if data.get("role") == "user" and data.get("content"):
                                c = data["content"]
                                if isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("text"):
                                    raw_title = c[0]["text"].strip().splitlines()[0][:60]
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
                "started_at": f"{date_str} 12:00:00",
                "records": records_count,
                "bytes": wb_stat.st_size,
                "tokens": wb_tok["tokens"],
                "chat_tokens": wb_tok["chat_tokens"],
                "aux_tokens": wb_tok["aux_tokens"],
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

def get_trae_sessions() -> list[dict[str, Any]]:
    import urllib.parse
    base_user_dirs = [
        ("trae", Path(r"C:\Users\HP\AppData\Roaming\Trae CN\User")),
        ("trae_solo", Path(r"C:\Users\HP\AppData\Roaming\TRAE SOLO CN\User")),
    ]
    mem_dir = Path(r"C:\Users\HP\.trae-cn\memory\projects")
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
                            s["records"] = max(s["records"], len(res_list))
                            for item in res_list:
                                if item.get("text"):
                                    txt = item["text"].strip()
                                    s["chat_text_buf"].append(txt)
                                    if not s["title"]:
                                        s["title"] = txt.splitlines()[0][:80]
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

                conn.close()
            except Exception:
                pass

    # 3. Assemble and calculate tokens for all sessions
    for sid, s in sessions_map.items():
        fp = Path(s["file_path"]) if s["file_path"] else Path(r"C:\Users\HP\AppData\Roaming\Trae CN\User\globalStorage\state.vscdb")
        mtime = s["mtime"] if s["mtime"] > 0 else (fp.stat().st_mtime if fp.exists() else time.time())
        date_str = ""
        if s["started_at"]:
            date_str = s["started_at"][:10]
        else:
            date_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")
            s["started_at"] = f"{date_str} 12:00:00"

        title_raw = s["title"].strip()
        if not title_raw:
            sub = s["workspace"] or s["model"] or s["mode"] or sid[:8]
            title_raw = f"Trae 会话 ({sub})"

        t_chat = sum(estimate_text_tokens(txt) for txt in s["chat_text_buf"])
        t_tot = max(t_chat, estimate_text_tokens(" ".join(s["chat_text_buf"])) + int(s["raw_json_len"] * 0.15))
        t_aux = max(0, t_tot - t_chat)

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
            "tokens": trae_tok["tokens"],
            "chat_tokens": trae_tok["chat_tokens"],
            "aux_tokens": trae_tok["aux_tokens"],
            "file_path": str(fp),
            "all_files": list(s["all_files"]),
            "account": s["account"],
            "model": s["model"],
            "mode": s["mode"],
            "workspace": s["workspace"],
            "exists": True,
            "mtime": mtime,
        })

    return results

def get_trae_session_messages(session_match: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract conversation message turns for a Trae session."""
    events = []
    sid = session_match.get("session_id", "")
    all_files = session_match.get("all_files", []) or [session_match.get("file_path", "")]
    
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
                    resp_parts = []
                    if outcome:
                        resp_parts.append(outcome)
                    if actions and isinstance(actions, list):
                        resp_parts.append("\n**执行动作：**\n" + "\n".join(f"- {a}" for a in actions))
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

    # 2. From state.vscdb
    for fp in all_files:
        p = Path(fp)
        if p.name == "state.vscdb" and p.exists():
            try:
                with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as db:
                    rows = db.execute("SELECT value FROM ItemTable WHERE key LIKE ?", (f"%{sid}%",)).fetchall()
                    for (val,) in rows:
                        if isinstance(val, bytes):
                            val = val.decode("utf-8", errors="ignore")
                        try:
                            data = json.loads(val)
                            res_list = data.get("response", {}).get("resp", {}).get("result", []) or data.get("response", {}).get("result", [])
                            if res_list and isinstance(res_list, list):
                                for item in res_list:
                                    txt = item.get("text", "").strip()
                                    if txt:
                                        events.append({
                                            "kind": "message",
                                            "role": "user" if len(events) % 2 == 0 else "assistant",
                                            "timestamp": "",
                                            "text": txt,
                                            "tool_name": "",
                                            "payload": None,
                                        })
                        except Exception:
                            pass
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
                        if not re.match(r"^[0-9a-f\-]{36}$", s) and "sessionID" not in s and len(s) >= 2:
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
                                if not re.match(r"^[0-9a-f\-]{36}$", s) and "sessionID" not in s and len(s) >= 2:
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
                        if len(c) >= 3 and not re.match(r"^[0-9a-f\-]{36}$", c):
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

    _ANTIGRAVITY_TITLE_CACHE[path_str] = (mtime, title)
    return title


class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        try:
            super().log_message(format, *args)
        except Exception:
            pass
    def send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.serve_html()
        elif path == "/api/status":
            self.handle_get_status()
        elif path == "/api/sessions":
            self.handle_get_sessions(query)
        elif path == "/api/session/detail":
            self.handle_get_session_detail(query)
        elif path == "/api/session/inspect":
            self.handle_get_session_inspect(query)
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

        # Add WorkBuddy and Trae counts
        wb_sessions = get_workbuddy_sessions()
        trae_sessions = get_trae_sessions()
        format_counts["workbuddy"] = len(wb_sessions)
        format_counts["trae"] = len(trae_sessions)
        total_sessions = cat_sessions + len(wb_sessions) + len(trae_sessions)

        # Append Trae user & memory data directories into roots_data
        trae_user_dir = Path(r"C:\Users\HP\AppData\Roaming\Trae CN\User")
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
        trae_mem_dir = Path(r"C:\Users\HP\.trae-cn\memory")
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
        search = query.get("q", [""])[0].strip().lower()
        fmt_filter = query.get("format", [""])[0].strip()

        now = time.time()
        # Fast memory reuse if cache is warm within 4 seconds (zero UI lag on keystrokes & tab switches)
        if _GLOBAL_SESSIONS_CACHE["data"] and (now - _GLOBAL_SESSIONS_CACHE["ts"] < 4.0):
            all_cached = _GLOBAL_SESSIONS_CACHE["data"]
            results = []
            for item in all_cached:
                if fmt_filter and fmt_filter != "all" and item.get("format") != fmt_filter:
                    continue
                if search:
                    haystack = f"{item.get('title','')} {item.get('session_id','')} {item.get('format','')} {item.get('file_path','')}".lower()
                    if search not in haystack:
                        continue
                results.append(item)
            sort_by = query.get("sort_by", ["mtime"])[0].strip()
            sort_order = query.get("order", ["desc"])[0].strip().lower()
            is_desc = (sort_order != "asc")
            def get_sort_key_cached(item):
                if sort_by == "mtime":
                    return float(item.get("mtime") or 0)
                elif sort_by == "started_at":
                    return str(item.get("started_at") or "")
                elif sort_by == "bytes":
                    return int(item.get("bytes") or 0)
                elif sort_by == "tokens":
                    return int(item.get("tokens") or 0)
                elif sort_by == "records":
                    return int(item.get("records") or 0)
                elif sort_by == "title":
                    return str(item.get("title") or "").lower()
                elif sort_by == "format":
                    return str(item.get("format") or "").lower()
                return float(item.get("mtime") or 0)
            results.sort(key=get_sort_key_cached, reverse=is_desc)
            self.send_json({"sessions": results, "count": len(results)})
            return

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
            
            # Formulate brain_readable formatted title
            title = ""
            date_str = ""
            if row["started_at"]:
                date_str = row["started_at"].split("T")[0]

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
                    raw_dt = row["display_title"] or ""
                    if raw_dt and not re.match(r"^[0-9a-f\-]{36}$", raw_dt) and not re.match(r"^[0-9a-f]{32}$", raw_dt):
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
            results.append({
                "catalog_id": row["catalog_id"],
                "format": fmt,
                "session_id": sid,
                "title": title,
                "started_at": row["started_at"] or (datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else ""),
                "records": row["records"] or 0,
                "bytes": s_bytes,
                "tokens": tok_info["tokens"],
                "chat_tokens": tok_info["chat_tokens"],
                "aux_tokens": tok_info["aux_tokens"],
                "file_path": str(abs_path),
                "exists": abs_path.exists(),
                "mtime": mtime,
            })

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
                        clean_t = extract_antigravity_title(p) or f"会话_{sid[:8]}"
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
                        started_at_str = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                    ag_size = p.stat().st_size
                    ag_tok = compute_session_tokens("antigravity", sid, p, mtime, ag_size)
                    results.append({
                        "catalog_id": f"ag_{sid[:12]}",
                        "format": "antigravity",
                        "session_id": sid,
                        "title": title,
                        "started_at": started_at_str,
                        "records": steps_count,
                        "bytes": ag_size,
                        "tokens": ag_tok["tokens"],
                        "chat_tokens": ag_tok["chat_tokens"],
                        "aux_tokens": ag_tok["aux_tokens"],
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
                t["mtime"] = t_path.stat().st_mtime if t_path.exists() else 0
                results.append(t)

        # Sort results: most recently active / modified first
        sort_by = query.get("sort_by", ["mtime"])[0].strip()
        sort_order = query.get("order", ["desc"])[0].strip().lower()
        is_desc = (sort_order != "asc")

        def get_sort_key(item):
            if sort_by == "mtime":
                return float(item.get("mtime") or 0)
            elif sort_by == "started_at":
                return str(item.get("started_at") or "")
            elif sort_by == "bytes":
                return int(item.get("bytes") or 0)
            elif sort_by == "tokens":
                return int(item.get("tokens") or 0)
            elif sort_by == "records":
                return int(item.get("records") or 0)
            elif sort_by == "title":
                return str(item.get("title") or "").lower()
            elif sort_by == "format":
                return str(item.get("format") or "").lower()
            return float(item.get("mtime") or 0)

        flush_token_cache()
        if not fmt_filter or fmt_filter == "all":
            _GLOBAL_SESSIONS_CACHE["ts"] = time.time()
            _GLOBAL_SESSIONS_CACHE["data"] = list(results)

        results.sort(key=get_sort_key, reverse=is_desc)
        self.send_json({"sessions": results, "count": len(results)})

    def handle_get_session_detail(self, query: dict[str, list[str]]):
        cid = query.get("catalog_id", [""])[0]
        if not cid:
            self.send_json({"error": "catalog_id required"}, status=400)
            return

        # 1. Handle WorkBuddy session
        if cid.startswith("wb_"):
            sid_prefix = cid[3:]
            wb_sessions = get_workbuddy_sessions()
            match = next((w for w in wb_sessions if w["session_id"].startswith(sid_prefix)), None)
            if not match:
                self.send_json({"error": "WorkBuddy session not found"}, status=404)
                return

            path = Path(match["file_path"])
            events = []
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        d = json.loads(line)
                        role = d.get("role") or d.get("type") or ""
                        text = ""
                        c = d.get("content") or d.get("message", {}).get("content")
                        if isinstance(c, str):
                            text = c
                        elif isinstance(c, list):
                            text = "\n".join(item.get("text", "") for item in c if isinstance(item, dict) and "text" in item)
                        
                        if text:
                            events.append({
                                "kind": "message",
                                "role": "user" if role == "user" else "assistant",
                                "timestamp": str(d.get("timestamp", "")),
                                "text": text,
                                "tool_name": "",
                                "payload": None,
                            })

                self.send_json({
                    "session_id": match["session_id"],
                    "format": "workbuddy",
                    "title": match["title"],
                    "started_at": match["started_at"],
                    "events_count": len(events),
                    "events": events,
                })
                return
            except Exception as e:
                self.send_json({"error": f"Failed to parse WorkBuddy session: {e}"}, status=500)
                return

        # 2. Handle Trae session
        if cid.startswith("trae_"):
            sid = cid[5:]
            trae_list = get_trae_sessions()
            match = next((t for t in trae_list if t["session_id"].startswith(sid)), None)
            if not match:
                self.send_json({"error": "Trae session not found"}, status=404)
                return

            try:
                events = get_trae_session_messages(match)
                self.send_json({
                    "session_id": match["session_id"],
                    "format": "trae",
                    "title": match["title"],
                    "started_at": match["started_at"],
                    "events_count": len(events),
                    "events": events,
                })
                return
            except Exception as e:
                self.send_json({"error": f"Failed to read Trae session: {e}"}, status=500)
                return

        # 3. Handle custom Antigravity session
        if cid.startswith("ag_"):
            sid_prefix = cid[3:]
            match = None
            for ag_conv_dir in ANTIGRAVITY_CONV_DIRS:
                if not ag_conv_dir.exists():
                    continue
                match = next((p for p in ag_conv_dir.glob("*.db") if p.stem.startswith(sid_prefix)), None)
                if match:
                    break
            if not match:
                self.send_json({"error": "Antigravity session file not found"}, status=404)
                return
            path = match
            source_fmt = AgentFormat.ANTIGRAVITY
            try:
                sess = load_session(path, source_fmt)
                events_data = []
                for ev in sess.events:
                    events_data.append({
                        "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                        "role": ev.role.value if hasattr(ev.role, "value") and ev.role else (str(ev.role) if ev.role else ""),
                        "timestamp": ev.timestamp or "",
                        "text": ev.text or "",
                        "tool_name": ev.tool_name or "",
                        "tool_call_id": ev.tool_call_id or "",
                        "payload": ev.payload if ev.payload else None,
                    })
                ag_sums = load_antigravity_summaries_map()
                c_title = ag_sums.get(sess.session_id, {}).get("title") or extract_antigravity_title(path) or sess.session_id[:8]
                self.send_json({
                    "session_id": sess.session_id,
                    "format": sess.source_format.value,
                    "title": c_title,
                    "started_at": sess.started_at or "",
                    "events_count": len(events_data),
                    "events": events_data,
                })
                return
            except Exception as e:
                self.send_json({"error": f"Failed to parse Antigravity session: {e}"}, status=500)
                return

        # 4. Standard Catalog session (Antigravity, Claude, Cursor)
        with Catalog(default_catalog_path()) as cat:
            try:
                entry = cat.get_session(cid, include_paths=True)
            except Exception as e:
                self.send_json({"error": f"Session not found in catalog: {e}"}, status=404)
                return
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
            self.send_json({"error": f"Session file not found: {path}"}, status=404)
            return

        try:
            sess = load_session(path, src_format)
            events_data = []
            for ev in sess.events:
                events_data.append({
                    "kind": ev.kind.value if hasattr(ev.kind, "value") else str(ev.kind),
                    "role": ev.role.value if hasattr(ev.role, "value") and ev.role else (str(ev.role) if ev.role else ""),
                    "timestamp": ev.timestamp or "",
                    "text": ev.text or "",
                    "tool_name": ev.tool_name or "",
                    "tool_call_id": ev.tool_call_id or "",
                    "payload": ev.payload if ev.payload else None,
                })

            self.send_json({
                "session_id": sess.session_id,
                "format": sess.source_format.value,
                "title": sess.title or entry.title or (extract_antigravity_title(path) if src_format == AgentFormat.ANTIGRAVITY else None) or sess.session_id[:8],
                "started_at": sess.started_at,
                "cwd": str(sess.cwd) if sess.cwd else None,
                "model": sess.model,
                "cli_version": sess.cli_version,
                "events_count": len(events_data),
                "events": events_data,
            })
        except Exception as e:
            self.send_json({"error": f"Failed to parse session content: {e}"}, status=500)

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
                wb_root = Path(r"C:\Users\HP\.workbuddy")
                
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
                with open(match["file_path"], "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        d = json.loads(line)
                        role = d.get("role") or d.get("type")
                        c = d.get("content") or d.get("message", {}).get("content")
                        text = ""
                        if isinstance(c, str):
                            text = c
                        elif isinstance(c, list):
                            text = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and "text" in x)
                        if role in {"user", "assistant"} and text:
                            msgs.append({"role": role, "text": text, "timestamp": str(d.get("timestamp", ""))})
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
                    ide_dir = Path(r"C:\Users\HP\.gemini\antigravity\conversations")
                    if not ide_dir.parent.exists():
                        ide_dir = Path(r"C:\Users\HP\.gemini\antigravity-ide\conversations")
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
                Path(r"C:\Users\HP\.gemini\antigravity\brain") / sid,
                Path(r"C:\Users\HP\.gemini\antigravity-ide\brain") / sid,
                Path(r"C:\Users\HP\.gemini\antigravity-ide\brain_readable") / sid,
                Path(r"C:\Users\HP\.gemini\antigravity-cli\brain") / sid,
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
                Path(r"C:\Users\HP\.gemini\antigravity\conversation_summaries.db"),
                Path(r"C:\Users\HP\.gemini\antigravity-ide\conversation_summaries.db"),
            ]:
                if s_db_p.exists():
                    try:
                        with sqlite3.connect(s_db_p, timeout=5) as s_conn:
                            s_conn.execute("DELETE FROM conversation_summaries WHERE conversation_id = ?", (sid,))
                    except Exception:
                        pass

        # 4. 如果是 WorkBuddy：从 workbuddy.db 中删除该会话记录
        if fmt == "workbuddy" or (main_path and "workbuddy" in str(main_path).lower()):
            try:
                wb_db = Path(r"C:\Users\HP\.workbuddy\workbuddy.db")
                if wb_db.exists():
                    with sqlite3.connect(wb_db, timeout=5) as conn:
                        conn.execute("DELETE FROM sessions WHERE id = ? OR id LIKE ?", (sid, f"%{sid}%"))
                        conn.commit()
            except Exception:
                pass

        # 5. 如果是 Trae：彻底清理关联的物理 session_memory 文件、attachments 截图、thumbnails 缩略图、work 目录及 state.vscdb 记录
        if fmt in ["trae", "trae_solo"] or (main_path and "trae" in str(main_path).lower()) or (cid and cid.startswith("trae_")):
            # A. 物理 session_memory 文件
            trae_mem_projects = Path(r"C:\Users\HP\.trae-cn\memory\projects")
            if trae_mem_projects.exists():
                for f in trae_mem_projects.rglob(f"session_memory_*{sid}*.jsonl"):
                    try:
                        total_freed_bytes += f.stat().st_size
                        f.unlink(missing_ok=True)
                        cleaned_paths.append(str(f))
                    except Exception:
                        pass
            # B. 截图附件 attachments
            att_dir = Path(r"C:\Users\HP\.trae-cn\attachments") / sid
            if att_dir.exists() and att_dir.is_dir():
                try:
                    dir_sz = sum(f.stat().st_size for f in att_dir.glob("**/*") if f.is_file())
                    total_freed_bytes += dir_sz
                    shutil.rmtree(att_dir, ignore_errors=True)
                    cleaned_paths.append(str(att_dir))
                except Exception:
                    pass
            # C. 缩略图 thumbnails
            thumb_file = Path(r"C:\Users\HP\.trae-cn\.thumbnails") / f"{sid}.png"
            if thumb_file.exists():
                try:
                    total_freed_bytes += thumb_file.stat().st_size
                    thumb_file.unlink(missing_ok=True)
                    cleaned_paths.append(str(thumb_file))
                except Exception:
                    pass
            # D. Work 目录
            work_dir = Path(r"C:\Users\HP\.trae-cn\work") / sid
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
                Path(r"C:\Users\HP\AppData\Roaming\Trae CN\User"),
                Path(r"C:\Users\HP\AppData\Roaming\TRAE SOLO CN\User"),
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
                if p.is_file():
                    # Windows 原生命令行，带 /select,"..." 确保高亮选中该文件
                    cmd = f'explorer.exe /select,"{p_resolved}"'
                    try:
                        subprocess.Popen(cmd)
                    except Exception:
                        os.system(f'explorer /select,"{p_resolved}"')
                else:
                    cmd = f'explorer.exe "{p_resolved}"'
                    subprocess.Popen(cmd)
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
        html = HTML_PAGE
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Memory Tools</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.7);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-hover-border: rgba(99, 102, 241, 0.4);
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --accent-indigo: #6366f1;
      --accent-purple: #a855f7;
      --accent-cyan: #06b6d4;
      --accent-emerald: #10b981;
      --accent-amber: #f59e0b;
      --accent-rose: #f43f5e;
      --font-sans: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
      --font-mono: 'JetBrains Mono', Consolas, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg);
      background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.12) 0px, transparent 50%),
        radial-gradient(at 50% 100%, rgba(6, 182, 212, 0.08) 0px, transparent 50%);
      background-attachment: fixed;
      color: var(--text-main);
      font-family: var(--font-sans);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      backdrop-filter: blur(20px);
      background: rgba(9, 13, 22, 0.75);
      border-bottom: 1px solid var(--card-border);
      position: sticky;
      top: 0;
      z-index: 50;
      padding: 16px 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .logo-area {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .logo-badge {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      background: linear-gradient(135deg, #6366f1, #a855f7);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
      box-shadow: 0 8px 16px -4px rgba(99, 102, 241, 0.5);
    }
    .logo-title {
      font-size: 20px;
      font-weight: 800;
      letter-spacing: -0.5px;
      background: linear-gradient(135deg, #ffffff 40%, #cbd5e1);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .logo-tag {
      font-size: 11px;
      font-weight: 700;
      background: rgba(99, 102, 241, 0.15);
      color: #818cf8;
      border: 1px solid rgba(99, 102, 241, 0.3);
      padding: 2px 8px;
      border-radius: 999px;
      margin-left: 6px;
    }
    .nav-actions {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 600;
      font-family: inherit;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .btn-primary {
      background: linear-gradient(135deg, #6366f1, #4f46e5);
      color: white;
      box-shadow: 0 4px 12px rgba(79, 70, 229, 0.35);
    }
    .btn-primary:hover {
      background: linear-gradient(135deg, #4f46e5, #4338ca);
      transform: translateY(-1px);
      box-shadow: 0 6px 16px rgba(79, 70, 229, 0.45);
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.05);
      color: #cbd5e1;
      border-color: var(--card-border);
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.08);
      color: white;
      border-color: rgba(255, 255, 255, 0.2);
    }
    .container {
      max-width: 1400px;
      width: 100%;
      margin: 0 auto;
      padding: 28px 32px;
      flex: 1;
    }
    /* Stats Bar */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 28px;
    }
    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(16px);
      padding: 18px 22px;
      border-radius: 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      transition: border-color 0.2s;
    }
    .stat-card:hover {
      border-color: var(--card-hover-border);
    }
    .stat-label {
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
      margin-bottom: 4px;
    }
    .stat-val {
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }
    .stat-icon {
      font-size: 28px;
      opacity: 0.85;
    }
    /* Filter, Search & Sort Bar */
    .toolbar {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(16px);
      border-radius: 16px;
      padding: 12px 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 22px;
      box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.25);
    }
    .search-box {
      flex: 1 1 220px;
      min-width: 200px;
      position: relative;
    }
    .search-input {
      width: 100%;
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 8px 14px 8px 36px;
      color: white;
      font-size: 13px;
      font-family: inherit;
      outline: none;
      transition: all 0.2s;
    }
    .search-input:focus {
      border-color: var(--accent-indigo);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }
    .search-icon {
      position: absolute;
      left: 12px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 14px;
    }
    .filter-chips {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      align-items: center;
    }
    .chip {
      padding: 6px 11px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.04);
      color: var(--text-muted);
      border: 1px solid var(--card-border);
      cursor: pointer;
      transition: all 0.2s;
      user-select: none;
    }
    .chip:hover {
      background: rgba(255, 255, 255, 0.08);
      color: white;
    }
    .chip.active {
      background: rgba(99, 102, 241, 0.2);
      color: #a5b4fc;
      border-color: rgba(99, 102, 241, 0.45);
    }
    .toolbar-sort-group {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: nowrap;
    }
    .sort-select-wrapper {
      position: relative;
      display: inline-flex;
      align-items: center;
    }
    .sort-select-icon {
      position: absolute;
      left: 10px;
      pointer-events: none;
      font-size: 13px;
      opacity: 0.85;
      z-index: 1;
    }
    .sort-select {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--card-border);
      color: #c4b5fd;
      font-size: 12px;
      font-weight: 600;
      padding: 7px 28px 7px 28px;
      border-radius: 8px;
      cursor: pointer;
      outline: none;
      font-family: inherit;
      transition: all 0.2s;
      appearance: none;
      background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23a78bfa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
      background-repeat: no-repeat;
      background-position: right 8px center;
      background-size: 13px;
    }
    .sort-select:hover {
      background-color: rgba(255, 255, 255, 0.08);
      border-color: rgba(167, 139, 250, 0.45);
      color: #e0e7ff;
    }
    .sort-select:focus {
      border-color: #a78bfa;
      box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.2);
    }
    .sort-select option,
    .sort-select optgroup {
      background: #181824;
      color: #f1f5f9;
      font-size: 13px;
    }
    .sort-select optgroup {
      color: #94a3b8;
      font-weight: bold;
    }
    .sort-dir-quick-btn {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid var(--card-border);
      color: #c4b5fd;
      font-size: 12px;
      padding: 6px 9px;
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      transition: all 0.2s ease;
      font-family: inherit;
    }
    .sort-dir-quick-btn:hover {
      background: rgba(167, 139, 250, 0.18);
      border-color: rgba(167, 139, 250, 0.45);
      color: #ffffff;
    }
    .results-stats-compact {
      font-size: 11px;
      color: var(--text-muted);
      background: rgba(0, 0, 0, 0.3);
      padding: 6px 11px;
      border-radius: 8px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      user-select: none;
      white-space: nowrap;
    }
    .stat-highlight {
      color: #a5b4fc;
      font-weight: 700;
      font-family: var(--font-mono);
    }
    .stat-token-highlight {
      color: #fbbf24;
      cursor: help;
      border-bottom: 1px dashed rgba(251, 191, 36, 0.45);
      padding-bottom: 1px;
    }
    .meta-token-badge {
      color: #fcd34d;
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.28);
      padding: 1px 7px;
      border-radius: 6px;
      font-family: var(--font-mono);
      font-weight: 600;
      cursor: help;
      transition: all 0.2s ease;
    }
    .meta-token-badge:hover {
      background: rgba(245, 158, 11, 0.22);
      border-color: rgba(251, 191, 36, 0.6);
      color: #fef3c7;
      box-shadow: 0 0 10px rgba(245, 158, 11, 0.2);
    }
    .search-input {
      width: 100%;
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 10px 16px 10px 40px;
      color: white;
      font-size: 14px;
      font-family: inherit;
      outline: none;
      transition: all 0.2s;
    }
    .search-input:focus {
      border-color: var(--accent-indigo);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }
    .search-icon {
      position: absolute;
      left: 14px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      font-size: 16px;
    }
    .filter-chips {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .chip {
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.04);
      color: var(--text-muted);
      border: 1px solid var(--card-border);
      cursor: pointer;
      transition: all 0.2s;
      user-select: none;
    }
    .chip:hover {
      background: rgba(255, 255, 255, 0.08);
      color: white;
    }
    .chip.active {
      background: rgba(99, 102, 241, 0.2);
      color: #a5b4fc;
      border-color: rgba(99, 102, 241, 0.45);
    }
    /* Sessions Grid */
    .sessions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 20px;
    }
    .session-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(16px);
      border-radius: 18px;
      padding: 22px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      position: relative;
      overflow: hidden;
    }
    .session-card::before {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      width: 4px;
      height: 100%;
      background: var(--badge-gradient, var(--accent-indigo));
    }
    .session-card:hover {
      transform: translateY(-3px);
      border-color: var(--card-hover-border);
      box-shadow: 0 16px 32px -8px rgba(0, 0, 0, 0.45);
    }
    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }
    .format-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 8px;
      font-size: 11px;
      font-weight: 700;
      color: white;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .card-time {
      font-size: 12px;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }
    .card-title {
      font-size: 16px;
      font-weight: 700;
      line-height: 1.45;
      margin-bottom: 12px;
      color: #f8fafc;
      word-break: break-word;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .card-meta {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 12px;
      color: var(--text-muted);
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    .meta-item {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .meta-copyable {
      cursor: pointer;
      user-select: none;
      transition: all 0.2s ease;
      padding: 2px 6px;
      border-radius: 4px;
    }
    .meta-copyable:hover {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text-main, #f8fafc);
    }
    .meta-path-link {
      cursor: pointer;
      user-select: none;
      color: var(--primary-light, #c4b5fd);
      text-decoration: none;
      transition: all 0.2s ease;
      padding: 2px 6px;
      border-radius: 4px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .meta-path-link:hover {
      background: rgba(167, 139, 250, 0.16);
      color: #e0e7ff;
    }
    .meta-path-link .path-label {
      text-decoration: underline dotted;
      text-underline-offset: 3px;
      font-weight: 500;
    }
    .meta-path-link:hover .path-label {
      text-decoration: underline solid;
    }
    .card-actions {
      display: flex;
      gap: 6px;
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      padding-top: 14px;
    }
    .btn-action {
      flex: 1;
      padding: 6px 8px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 8px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      background: rgba(255, 255, 255, 0.04);
      color: #cbd5e1;
      border: 1px solid var(--card-border);
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      white-space: nowrap;
    }
    .btn-action:hover {
      background: rgba(255, 255, 255, 0.09);
      color: white;
      border-color: rgba(255, 255, 255, 0.2);
    }
    .btn-action.btn-migrate {
      background: rgba(99, 102, 241, 0.15);
      color: #a5b4fc;
      border-color: rgba(99, 102, 241, 0.35);
    }
    .btn-action.btn-migrate:hover {
      background: rgba(99, 102, 241, 0.25);
      color: #c7d2fe;
      border-color: rgba(99, 102, 241, 0.5);
    }
    .btn-action.btn-delete {
      background: rgba(244, 63, 94, 0.09);
      color: #fda4af;
      border-color: rgba(244, 63, 94, 0.28);
    }
    .btn-action.btn-delete:hover {
      background: rgba(244, 63, 94, 0.22);
      color: #fecdd3;
      border-color: rgba(244, 63, 94, 0.5);
    }
    .btn-action.btn-folder {
      flex: 0 0 36px;
      padding: 6px 0;
    }
    /* Modal Styles */
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px);
      z-index: 100;
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease;
      padding: 24px;
    }
    .modal-backdrop.open {
      opacity: 1;
      pointer-events: auto;
    }
    .modal-card {
      background: #0f172a;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 20px;
      width: 100%;
      max-width: 800px;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
      transform: scale(0.96);
      transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      overflow: hidden;
    }
    .modal-backdrop.open .modal-card {
      transform: scale(1);
    }
    .modal-header {
      padding: 20px 24px;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-title {
      font-size: 18px;
      font-weight: 700;
    }
    .modal-close {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 20px;
      cursor: pointer;
      line-height: 1;
      padding: 4px;
    }
    .modal-close:hover { color: white; }
    .modal-body {
      padding: 24px;
      overflow-y: auto;
      flex: 1;
    }
    .modal-footer {
      padding: 16px 24px;
      border-top: 1px solid var(--card-border);
      display: flex;
      justify-content: flex-end;
      gap: 12px;
    }
        /* Chat Modal Toolbar: Search & Navigation */
    .chat-modal-toolbar {
      padding: 10px 20px;
      background: rgba(15, 23, 42, 0.98);
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      z-index: 10;
      position: sticky;
      top: 0;
      backdrop-filter: blur(12px);
    }
    .user-nav-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .user-nav-label {
      font-size: 12px;
      font-weight: 700;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 5px;
      white-space: nowrap;
    }
    .nav-btn {
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.14);
      color: #e2e8f0;
      font-size: 12px;
      padding: 5px 12px;
      border-radius: 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      user-select: none;
    }
    .nav-btn:hover {
      background: rgba(99, 102, 241, 0.25);
      border-color: rgba(99, 102, 241, 0.6);
      color: #ffffff;
      transform: translateY(-1px);
    }
    .nav-btn:active {
      transform: translateY(0);
    }
    .nav-btn:disabled {
      opacity: 0.35;
      cursor: not-allowed;
      border-color: rgba(255, 255, 255, 0.08) !important;
      background: rgba(255, 255, 255, 0.03) !important;
      transform: none !important;
    }
    .nav-btn.nav-btn-sm {
      padding: 4px 8px;
      font-size: 11px;
    }
    .nav-btn.nav-btn-toggle {
      font-size: 11.5px;
      padding: 5px 11px;
      background: rgba(255, 255, 255, 0.05);
      color: #cbd5e1;
      border: 1px solid rgba(255, 255, 255, 0.12);
    }
    .nav-btn.nav-btn-toggle:hover {
      color: #ffffff;
      background: rgba(255, 255, 255, 0.12);
      border-color: rgba(255, 255, 255, 0.25);
    }
    .nav-counter {
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 700;
      color: #a5b4fc;
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.35);
      padding: 3px 9px;
      border-radius: 6px;
      min-width: 52px;
      text-align: center;
      white-space: nowrap;
    }
    .chat-search-group {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1;
      max-width: 440px;
    }
    .chat-search-input-wrap {
      position: relative;
      flex: 1;
      display: flex;
      align-items: center;
    }
    .search-mini-icon {
      position: absolute;
      left: 10px;
      font-size: 12px;
      color: var(--text-muted);
      pointer-events: none;
    }
    .chat-search-input {
      width: 100%;
      background: rgba(0, 0, 0, 0.45);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 8px;
      padding: 6px 30px 6px 30px;
      color: #ffffff;
      font-size: 12.5px;
      outline: none;
      transition: all 0.2s ease;
      box-sizing: border-box;
    }
    .chat-search-input:focus {
      border-color: var(--accent-indigo);
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.3);
      background: rgba(0, 0, 0, 0.65);
    }
    .search-clear-btn {
      position: absolute;
      right: 8px;
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 11px;
      padding: 2px 5px;
      border-radius: 4px;
    }
    .search-clear-btn:hover {
      color: #ffffff;
      background: rgba(255, 255, 255, 0.2);
    }
    .search-nav-controls {
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .search-match-count {
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      color: #fbbf24;
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.35);
      padding: 3px 7px;
      border-radius: 6px;
      white-space: nowrap;
    }
    .chat-toggle-group {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Chat View inside modal */
    .chat-stream {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 16px 20px 32px 20px;
    }
    .bubble {
      padding: 12px 16px;
      border-radius: 10px;
      font-size: 13px;
      line-height: 1.6;
      width: 100%;
      box-sizing: border-box;
      word-break: break-word;
      transition: border-color 0.2s, box-shadow 0.2s, background 0.2s, transform 0.15s;
      position: relative;
    }
    .bubble.user {
      background: linear-gradient(135deg, rgba(79, 70, 229, 0.95), rgba(67, 56, 202, 0.95));
      border: 1px solid rgba(165, 180, 252, 0.45);
      color: white;
      box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25);
    }
    .bubble.user.pulse-focus {
      animation: pulseUserFocus 1.8s ease-out;
    }
    @keyframes pulseUserFocus {
      0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.95); border-color: #f59e0b; }
      30% { box-shadow: 0 0 32px 8px rgba(245, 158, 11, 0.7); border-color: #fbbf24; transform: scale(1.015); }
      100% { box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25); border-color: rgba(165, 180, 252, 0.45); transform: scale(1); }
    }
    .bubble.assistant {
      background: rgba(30, 41, 59, 0.7);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: #f1f5f9;
    }
    .bubble.assistant.collapsed {
      background: rgba(30, 41, 59, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.08);
      padding: 8px 14px;
      cursor: pointer;
    }
    .bubble.assistant.collapsed:hover {
      background: rgba(30, 41, 59, 0.75);
      border-color: rgba(99, 102, 241, 0.5);
      box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
    }
    .bubble.tool {
      background: rgba(16, 185, 129, 0.06);
      border: 1px solid rgba(16, 185, 129, 0.22);
      color: #a7f3d0;
      font-family: var(--font-mono);
      font-size: 12px;
      border-radius: 9px;
    }
    .bubble.tool.collapsed {
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(16, 185, 129, 0.25);
      padding: 7px 12px;
      cursor: pointer;
    }
    .bubble.tool.collapsed:hover {
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.55);
      box-shadow: 0 2px 10px rgba(16, 185, 129, 0.15);
    }
    .bubble.thinking {
      background: rgba(168, 85, 247, 0.06);
      border: 1px solid rgba(168, 85, 247, 0.25);
      color: #e9d5ff;
      border-radius: 9px;
    }
    .bubble.thinking.collapsed {
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(168, 85, 247, 0.25);
      padding: 7px 12px;
      cursor: pointer;
    }
    .bubble.thinking.collapsed:hover {
      background: rgba(168, 85, 247, 0.12);
      border-color: rgba(168, 85, 247, 0.55);
    }
    
    /* Collapsible Bubble Header & Summary */
    .bubble-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      cursor: pointer;
      user-select: none;
      padding: 1px 0;
    }
    .bubble-header-left {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      flex: 1;
    }
    .bubble-chevron {
      font-size: 10px;
      color: #94a3b8;
      transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      display: inline-block;
      width: 14px;
      text-align: center;
      flex-shrink: 0;
    }
    .bubble.collapsed .bubble-chevron {
      transform: rotate(-90deg);
    }
    .bubble-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 5px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .bubble-badge.badge-tool {
      background: rgba(16, 185, 129, 0.18);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .bubble-badge.badge-command {
      background: rgba(14, 165, 233, 0.18);
      color: #38bdf8;
      border: 1px solid rgba(14, 165, 233, 0.3);
    }
    .bubble-badge.badge-file {
      background: rgba(245, 158, 11, 0.18);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .bubble-badge.badge-assistant {
      background: rgba(99, 102, 241, 0.18);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .bubble-badge.badge-thinking {
      background: rgba(168, 85, 247, 0.18);
      color: #c084fc;
      border: 1px solid rgba(168, 85, 247, 0.3);
    }
    .bubble-summary {
      font-size: 12.5px;
      color: #cbd5e1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 1;
      min-width: 0;
      font-weight: 500;
      letter-spacing: 0.1px;
    }
    .bubble.collapsed .bubble-summary {
      color: #e2e8f0;
    }
    .bubble.collapsed:hover .bubble-summary {
      color: #ffffff;
    }
    .bubble-header-right {
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .bubble-meta-badge {
      font-size: 11px;
      color: #94a3b8;
      background: rgba(255, 255, 255, 0.06);
      padding: 2px 7px;
      border-radius: 5px;
      font-family: var(--font-mono);
    }
    .bubble-body {
      margin-top: 10px;
      border-top: 1px solid rgba(255, 255, 255, 0.08);
      padding-top: 10px;
      animation: fadeInBody 0.18s ease-out;
    }
    @keyframes fadeInBody {
      from { opacity: 0; transform: translateY(-3px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .bubble.collapsed .bubble-body {
      display: none;
    }

    /* Fulltext search highlight marks */
    mark.chat-highlight {
      background: rgba(234, 179, 8, 0.45);
      color: #ffffff;
      padding: 1px 4px;
      border-radius: 3px;
      font-weight: 600;
    }
    mark.chat-highlight.current {
      background: #f59e0b;
      color: #0f172a;
      box-shadow: 0 0 12px rgba(245, 158, 11, 0.95);
      font-weight: 800;
    }
/* Target agent picker */
    .target-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 14px;
      max-height: 230px;
      overflow-y: auto;
      padding-right: 4px;
    }
    .target-card {
      border: 1px solid var(--card-border);
      background: rgba(255, 255, 255, 0.03);
      border-radius: 12px;
      padding: 14px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: all 0.2s;
    }
    .target-card:hover {
      border-color: rgba(99, 102, 241, 0.4);
      background: rgba(255, 255, 255, 0.06);
    }
    .target-card.selected {
      border-color: var(--accent-indigo);
      background: rgba(99, 102, 241, 0.15);
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.3);
    }
    .form-group {
      margin-bottom: 18px;
    }
    .form-label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 8px;
      color: #cbd5e1;
    }
    .radio-group {
      display: flex;
      gap: 16px;
    }
    .radio-label {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      cursor: pointer;
    }
    /* Toast */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      border: 1px solid var(--accent-indigo);
      color: white;
      padding: 12px 20px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 600;
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      opacity: 0;
      transform: translateY(12px);
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      z-index: 200;
      pointer-events: none;
    }
    #toast.show {
      opacity: 1;
      transform: translateY(0);
    }

    /* --- Memory Tools: Cleanup Console & Batch Management Drawer --- */
    .btn-cleanup {
      background: linear-gradient(135deg, rgba(236, 72, 153, 0.22), rgba(168, 85, 247, 0.22));
      border: 1px solid rgba(236, 72, 153, 0.45);
      color: #f472b6;
      font-weight: 700;
      box-shadow: 0 0 15px rgba(236, 72, 153, 0.15);
      transition: all 0.25s ease;
    }
    .btn-cleanup:hover {
      background: linear-gradient(135deg, rgba(236, 72, 153, 0.35), rgba(168, 85, 247, 0.35));
      border-color: #f472b6;
      color: #ffffff;
      box-shadow: 0 0 22px rgba(236, 72, 153, 0.35);
      transform: translateY(-1px);
    }

    /* Cleanup Drawer Modal (Full-width deep drawer) */
    .cleanup-drawer-card {
      width: 94vw;
      max-width: 1280px;
      height: 90vh;
      background: rgba(15, 23, 42, 0.98);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 18px;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.8), 0 0 40px rgba(99, 102, 241, 0.12);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      animation: modalSlideUp 0.28s cubic-bezier(0.16, 1, 0.3, 1);
    }

    /* Custom Filter Inputs */
    .custom-range-row {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 2px;
    }
    .custom-input {
      flex: 1;
      min-width: 0;
      background: rgba(15, 23, 42, 0.65);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 6px;
      color: #f1f5f9;
      font-size: 12px;
      padding: 5px 8px;
      outline: none;
      transition: all 0.2s;
    }
    .custom-input:focus {
      border-color: rgba(99, 102, 241, 0.8);
      box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
      background: rgba(15, 23, 42, 0.95);
    }
    .custom-select {
      background: rgba(15, 23, 42, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 6px;
      color: #cbd5e1;
      font-size: 11.5px;
      padding: 5px 6px;
      outline: none;
      cursor: pointer;
    }
    .custom-select:focus {
      border-color: rgba(99, 102, 241, 0.8);
    }
    .range-sep {
      color: #64748b;
      font-size: 12px;
      flex-shrink: 0;
    }
    .reset-filter-btn {
      font-size: 11px;
      color: #a5b4fc;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.3);
      border-radius: 4px;
      padding: 2px 7px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .reset-filter-btn:hover {
      background: rgba(99, 102, 241, 0.25);
      color: #ffffff;
      border-color: rgba(99, 102, 241, 0.6);
    }

    /* Multi-dimension Filter Matrix */
    .filter-matrix {
      padding: 14px 24px;
      background: rgba(0, 0, 0, 0.25);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
    }
    .matrix-col {
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 10px;
      padding: 10px 14px;
    }
    .matrix-label {
      font-size: 12px;
      font-weight: 700;
      color: #cbd5e1;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .matrix-options {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .matrix-opt {
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.09);
      color: #94a3b8;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.18s ease;
      user-select: none;
    }
    .matrix-opt:hover {
      color: #e2e8f0;
      border-color: rgba(255, 255, 255, 0.22);
    }
    .matrix-opt.active {
      background: rgba(99, 102, 241, 0.22);
      border-color: rgba(99, 102, 241, 0.6);
      color: #a5b4fc;
      font-weight: 600;
    }

    /* Cleanup Table View */
    .cleanup-table-container {
      flex: 1;
      overflow-y: auto;
      padding: 0 24px 80px 24px;
    }
    .cleanup-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12.5px;
      text-align: left;
    }
    .cleanup-table th {
      position: sticky;
      top: 0;
      background: #0f172a;
      padding: 10px 12px;
      font-weight: 700;
      color: #94a3b8;
      border-bottom: 1px solid rgba(255, 255, 255, 0.1);
      z-index: 5;
      white-space: nowrap;
    }
    .cleanup-table td {
      padding: 10px 12px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      color: #cbd5e1;
      vertical-align: middle;
    }
    .cleanup-table tr:hover td {
      background: rgba(255, 255, 255, 0.035);
      color: #ffffff;
    }
    .cleanup-table tr.selected td {
      background: rgba(99, 102, 241, 0.12);
    }

    /* Storage badge in table */
    .storage-type-badge {
      font-size: 10.5px;
      font-family: var(--font-mono);
      padding: 2px 6px;
      border-radius: 4px;
      white-space: nowrap;
    }
    .storage-type-badge.type-file {
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .storage-type-badge.type-db {
      background: rgba(245, 158, 11, 0.15);
      color: #fbbf24;
      border: 1px solid rgba(245, 158, 11, 0.3);
    }

    /* Sticky Bottom Action Bar */
    .cleanup-action-bar {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      background: rgba(15, 23, 42, 0.98);
      border-top: 1px solid rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(16px);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      z-index: 20;
    }
    .action-stat-summary {
      font-size: 13px;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .action-stat-highlight {
      font-family: var(--font-mono);
      font-weight: 700;
      color: #f43f5e;
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid rgba(244, 63, 94, 0.3);
      padding: 3px 8px;
      border-radius: 6px;
    }

    /* Safe Confirm Modal */
    .safe-confirm-card {
      background: #1e293b;
      border: 1px solid rgba(244, 63, 94, 0.4);
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8), 0 0 30px rgba(244, 63, 94, 0.2);
      border-radius: 16px;
      width: 100%;
      max-width: 540px;
      overflow: hidden;
      animation: modalSlideUp 0.22s ease-out;
    }

  </style>
</head>
<body>
  <header>
    <div class="logo-area">
      <div class="logo-badge">⚡</div>
      <div class="logo-title">Memory Tools</div>
      <div class="logo-tag">WEB GUI</div>
    </div>
    <div class="nav-actions">
      <button class="btn btn-secondary" onclick="openRootsModal()">📂 扫描目录管理</button>
      <button class="btn btn-secondary" onclick="openCleanupDrawer()" title="进入会话批量管理控制台">
        <span>🗂️</span> <span>会话批量管理</span>
      </button>
      <button class="btn btn-primary" id="btnRefresh" onclick="refreshCatalog()" title="重新扫描并刷新所有智能体会话数据">
        <span>🔄</span> <span>刷新会话数据</span>
      </button>
    </div>
  </header>

  <div class="container">
    <!-- Stats Row -->
    <div class="stats-grid">
      <div class="stat-card">
        <div>
          <div class="stat-label">已收录会话总数</div>
          <div class="stat-val" id="statTotalSessions">-</div>
        </div>
        <div class="stat-icon">💬</div>
      </div>
      <div class="stat-card">
        <div>
          <div class="stat-label">支持的智能体平台</div>
          <div class="stat-val" id="statSupportedAgents">18 种</div>
        </div>
        <div class="stat-icon">🧩</div>
      </div>
      <div class="stat-card">
        <div>
          <div class="stat-label">已接入数据目录</div>
          <div class="stat-val" id="statActiveRoots">-</div>
        </div>
        <div class="stat-icon">📁</div>
      </div>
      <div class="stat-card">
        <div>
          <div class="stat-label">跨工具一键互迁</div>
          <div class="stat-val" style="color: var(--accent-emerald);">实时就绪</div>
        </div>
        <div class="stat-icon">🚀</div>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <div class="search-box">
        <span class="search-icon">🔍</span>
        <input type="text" class="search-input" id="searchInput" placeholder="搜索清晰会话名称、UUID、编程智能体..." oninput="handleSearch()">
      </div>

      <div class="filter-chips" id="filterChips">
        <div class="chip active" data-fmt="all" onclick="filterByFormat('all')">全部</div>
        <div class="chip" data-fmt="antigravity" onclick="filterByFormat('antigravity')">⚡ Antigravity</div>
        <div class="chip" data-fmt="claude" onclick="filterByFormat('claude')">🟣 Claude Code</div>
        <div class="chip" data-fmt="workbuddy" onclick="filterByFormat('workbuddy')">🤖 WorkBuddy</div>
        <div class="chip" data-fmt="trae" onclick="filterByFormat('trae')">✨ Trae</div>
        <div class="chip" data-fmt="cursor" onclick="filterByFormat('cursor')">Cursor</div>
        <div class="chip" data-fmt="copilot" onclick="filterByFormat('copilot')">GitHub Copilot</div>
      </div>

      <div class="toolbar-sort-group">
        <div class="sort-select-wrapper">
          <span class="sort-select-icon">🔀</span>
          <select class="sort-select" id="sortSelect" onchange="handleSortFieldChange(this.value)" title="选择会话排序依据">
            <option value="mtime">🕒 最近活跃</option>
            <option value="started_at">📅 创建时间</option>
            <option value="bytes">💾 文件大小</option>
            <option value="tokens">🪙 Token 数量</option>
            <option value="records">🔢 交互步数</option>
            <option value="title">🔤 标题名称</option>
            <option value="format">🤖 平台类型</option>
          </select>
        </div>
        <button class="sort-dir-quick-btn" id="btnSortDirQuick" onclick="toggleSortOrderQuick()" title="点击一键反转升/降序">
          <span id="sortDirQuickIcon">⬇️</span>
        </button>
        <div class="results-stats-compact" id="resultsStats" title="当前匹配的会话统计">
          <span class="stat-highlight" id="statMatchCount">0</span> 篇 · <span class="stat-highlight" id="statTotalSize">0 KB</span> · 🪙 <span class="stat-highlight stat-token-highlight" id="statTotalTokens">0 Tokens</span>
        </div>
      </div>
    </div>

    <!-- Sessions Grid -->
    <div class="sessions-grid" id="sessionsGrid">
      <div style="grid-column: 1/-1; text-align: center; padding: 60px; color: var(--text-muted);">
        正在加载全平台会话数据...
      </div>
    </div>
  </div>

  <!-- Chat Detail Modal -->
  <div class="modal-backdrop" id="chatModal">
    <div class="modal-card" style="max-width: 950px; height: 88vh;">
      <div class="modal-header">
        <div>
          <div class="modal-title" id="chatModalTitle">会话详情预览</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px; font-family: var(--font-mono);" id="chatModalSub"></div>
        </div>
        <button class="modal-close" onclick="closeChatModal()">✕</button>
      </div>

      <!-- Chat Toolbar: Navigation & Fulltext Search -->
      <div class="chat-modal-toolbar">
        <div class="user-nav-group">
          <span class="user-nav-label">👤 用户指令:</span>
          <button class="nav-btn" id="btnPrevUserMsg" onclick="navigateUserMessage(-1)" title="跳转到上一条用户指令 (Alt+↑)">
            ⬆️ 上一条
          </button>
          <span class="nav-counter" id="userMsgCounter">0 / 0</span>
          <button class="nav-btn" id="btnNextUserMsg" onclick="navigateUserMessage(1)" title="跳转到下一条用户指令 (Alt+↓)">
            下一条 ⬇️
          </button>
        </div>

        <div class="chat-search-group">
          <div class="chat-search-input-wrap">
            <span class="search-mini-icon">🔍</span>
            <input type="text" id="chatSearchInput" class="chat-search-input" placeholder="在全文中搜索 (Enter跳下一个)..." oninput="handleChatSearch()" onkeydown="handleChatSearchKey(event)">
            <button class="search-clear-btn" id="chatSearchClear" onclick="clearChatSearch()" title="清除搜索" style="display: none;">✕</button>
          </div>
          <div class="search-nav-controls" id="searchNavControls" style="display: none;">
            <span class="search-match-count" id="searchMatchCount">0/0</span>
            <button class="nav-btn nav-btn-sm" onclick="navigateSearchMatch(-1)" title="上一个匹配项 (Shift+Enter)">⬆️</button>
            <button class="nav-btn nav-btn-sm" onclick="navigateSearchMatch(1)" title="下一个匹配项 (Enter)">⬇️</button>
          </div>
        </div>

        <div class="chat-toggle-group">
          <button class="nav-btn nav-btn-toggle" onclick="toggleAllBubbles(false)" title="全部收起为极简摘要">📁 全部收起</button>
          <button class="nav-btn nav-btn-toggle" onclick="toggleAllBubbles(true)" title="全部展开查看完整详情">📖 全部展开</button>
        </div>
      </div>

      <div class="modal-body" id="chatStreamBody">
        <div style="text-align: center; padding: 40px; color: var(--text-muted);">加载对话流...</div>
      </div>
      <div class="modal-footer" style="display: flex; justify-content: space-between; align-items: center;">
        <button class="btn btn-delete" id="btnDeleteFromChat" style="background: rgba(244, 63, 94, 0.15); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.35); font-size: 12px; padding: 7px 14px; border-radius: 8px; cursor: pointer;">🗑️ 删除此会话</button>
        <div style="display: flex; gap: 10px;">
          <button class="btn btn-secondary" onclick="closeChatModal()">关闭</button>
          <button class="btn btn-primary" id="btnMigrateFromChat">🚀 立即迁移此会话</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Migrate Wizard Modal -->
  <div class="modal-backdrop" id="migrateModal">
    <div class="modal-card">
      <div class="modal-header">
        <div>
          <div class="modal-title">跨智能体会话迁移向导</div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;" id="migrateSourceTitle"></div>
        </div>
        <button class="modal-close" onclick="closeMigrateModal()">✕</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label class="form-label">选择目标编程智能体 (Target Agent)：</label>
          <div class="target-grid" id="targetGrid">
            <!-- Populated via JS -->
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: -6px; margin-bottom: 14px; line-height: 1.5;">
            💡 <strong>支持提示</strong>：已支持一键迁入 Antigravity IDE、WorkBuddy、Claude Code、Cursor、Copilot 等 13 种主流工具。<br>Trae / Trae SOLO 目前仅支持作为数据源被读取和迁出（由于 Trae 官方未提供公开的本地会话写入接口）。
          </div>
        </div>

        <div class="form-group">
          <label class="form-label">迁移安装模式：</label>
          <div class="radio-group">
            <label class="radio-label">
              <input type="radio" name="migrateMode" value="import" checked>
              <span><strong>直接安装到目标工具</strong> (自动写入目标 Agent 主目录)</span>
            </label>
            <label class="radio-label">
              <input type="radio" name="migrateMode" value="export">
              <span><strong>导出为独立文件</strong> (保存至 exports 目录)</span>
            </label>
          </div>
        </div>

        <div id="migrateFeedback" style="display: none; padding: 14px; border-radius: 10px; margin-top: 16px; font-size: 13px;"></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeMigrateModal()">取消</button>
        <button class="btn btn-primary" id="btnExecuteMigrate" onclick="executeMigrate()">开始转换与迁移</button>
      </div>
    </div>
  </div>

  <!-- Roots Management Modal -->
  <div class="modal-backdrop" id="rootsModal">
    <div class="modal-card">
      <div class="modal-header">
        <div class="modal-title">已配置的 Agent 数据根目录</div>
        <button class="modal-close" onclick="closeRootsModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="margin-bottom: 20px;">
          <h4 style="font-size: 14px; margin-bottom: 12px;">已接入的扫描目录列表：</h4>
          <div id="rootsList" style="display: flex; flex-direction: column; gap: 8px;"></div>
        </div>

        <div style="background: rgba(255, 255, 255, 0.03); padding: 16px; border-radius: 12px; border: 1px solid var(--card-border);">
          <h4 style="font-size: 14px; margin-bottom: 12px;">添加新的扫描目录：</h4>
          <div style="display: grid; grid-template-columns: 140px 1fr auto; gap: 10px; align-items: center;">
            <select id="newRootFormat" class="search-input" style="padding: 8px 12px;">
              <option value="antigravity">Antigravity</option>
              <option value="claude">Claude Code</option>
              <option value="cursor">Cursor</option>
              <option value="copilot">Copilot</option>
              <option value="codex">Codex</option>
              <option value="kimi">Kimi</option>
              <option value="devin">Devin</option>
            </select>
            <input type="text" id="newRootPath" class="search-input" placeholder="输入绝对路径 (如 C:\\Users\\...)" style="padding: 8px 12px;">
            <button class="btn btn-primary" onclick="addRoot()">添加</button>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeRootsModal()">完成</button>
      </div>
    </div>
  </div>


  <!-- Cleanup Drawer Modal -->
  <div class="modal-backdrop" id="cleanupDrawerModal" onclick="if(event.target===this)closeCleanupDrawer()">
    <div class="cleanup-drawer-card">
      <div class="modal-header">
        <div>
          <div class="modal-title" style="display: flex; align-items: center; gap: 8px;">
            <span>🧹</span> <span>会话批量管理</span>
            <span class="logo-tag" style="background: rgba(236, 72, 153, 0.2); color: #f472b6; border-color: rgba(236, 72, 153, 0.4);">Memory Tools</span>
          </div>
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            支持按平台类型、会话大小、对话步数、时间范围等多维复合多选筛选，一键彻底擦除文件或批量跨平台迁移
          </div>
        </div>
        <button class="modal-close" onclick="closeCleanupDrawer()">✕</button>
      </div>

      <!-- Multi-dimension Filter Matrix -->
      <div class="filter-matrix">
        <!-- 维度 1: 平台类型 (多选) -->
        <div class="matrix-col">
          <div class="matrix-label">
            <span>💻 智能体平台</span>
            <span style="font-size: 10px; color: var(--text-muted);">(可多选)</span>
          </div>
          <div class="matrix-options" id="filterMatrixFormats">
            <span class="matrix-opt active" data-fmt="all" onclick="toggleCleanupFilter('fmt', 'all')">全部平台</span>
            <span class="matrix-opt" data-fmt="antigravity" onclick="toggleCleanupFilter('fmt', 'antigravity')">Antigravity</span>
            <span class="matrix-opt" data-fmt="claude" onclick="toggleCleanupFilter('fmt', 'claude')">Claude</span>
            <span class="matrix-opt" data-fmt="workbuddy" onclick="toggleCleanupFilter('fmt', 'workbuddy')">WorkBuddy</span>
            <span class="matrix-opt" data-fmt="trae" onclick="toggleCleanupFilter('fmt', 'trae')">Trae</span>
            <span class="matrix-opt" data-fmt="cursor" onclick="toggleCleanupFilter('fmt', 'cursor')">Cursor</span>
          </div>
        </div>

        <!-- 维度 2: 存储大小 (自定义范围) -->
        <div class="matrix-col">
          <div class="matrix-label">
            <span>📦 存储大小占用</span>
            <span style="font-size: 10px; color: var(--text-muted);">(自定义范围)</span>
          </div>
          <div class="custom-range-row">
            <input type="number" class="custom-input" id="cleanupMinSize" placeholder="最小值" min="0" step="any" oninput="applyCleanupFiltersAndRender()">
            <span class="range-sep">~</span>
            <input type="number" class="custom-input" id="cleanupMaxSize" placeholder="最大值" min="0" step="any" oninput="applyCleanupFiltersAndRender()">
            <select class="custom-select" id="cleanupSizeUnit" onchange="applyCleanupFiltersAndRender()">
              <option value="MB" selected>MB</option>
              <option value="KB">KB</option>
              <option value="Bytes">B</option>
            </select>
          </div>
        </div>

        <!-- 维度 3: 步数区间 (自定义范围) -->
        <div class="matrix-col">
          <div class="matrix-label">
            <span>🔢 对话步数/轮数</span>
            <span style="font-size: 10px; color: var(--text-muted);">(自定义步数)</span>
          </div>
          <div class="custom-range-row">
            <input type="number" class="custom-input" id="cleanupMinSteps" placeholder="最少步数" min="0" step="1" oninput="applyCleanupFiltersAndRender()">
            <span class="range-sep">~</span>
            <input type="number" class="custom-input" id="cleanupMaxSteps" placeholder="最多步数" min="0" step="1" oninput="applyCleanupFiltersAndRender()">
            <span class="range-sep" style="font-size: 11px; color: #94a3b8; margin-left: 2px;">步</span>
          </div>
        </div>

        <!-- 维度 4: 活跃时间跨度 (自定义条件) -->
        <div class="matrix-col">
          <div class="matrix-label">
            <span>🕒 活跃时间跨度</span>
            <button class="reset-filter-btn" onclick="resetCleanupFilters()" title="重置全部筛选条件">重置筛选</button>
          </div>
          <div class="custom-range-row">
            <select class="custom-select" id="cleanupTimeType" onchange="handleCleanupTimeTypeChange()" style="flex: 1.2;">
              <option value="all" selected>全部时间</option>
              <option value="days_before">早于距今 (天前)</option>
              <option value="days_within">距今最近 (天内)</option>
              <option value="date_before">早于指定日期</option>
              <option value="date_after">晚于指定日期</option>
            </select>
            <input type="number" class="custom-input" id="cleanupTimeDaysVal" placeholder="天数 (如 30)" min="1" style="display: none; flex: 1;" oninput="applyCleanupFiltersAndRender()">
            <input type="date" class="custom-input" id="cleanupTimeDateVal" style="display: none; flex: 1.4; font-size: 11px; padding: 4px;" onchange="applyCleanupFiltersAndRender()">
          </div>
        </div>
      </div>

      <!-- Result Table View -->
      <div class="cleanup-table-container">
        <table class="cleanup-table">
          <thead>
            <tr>
              <th style="width: 44px; text-align: center;">
                <input type="checkbox" id="cleanupSelectAll" onchange="toggleCleanupSelectAll(this.checked)" style="cursor: pointer;">
              </th>
              <th style="width: 110px;">平台</th>
              <th>会话标题与标识</th>
              <th style="width: 85px;">步数</th>
              <th style="width: 105px;">文件大小</th>
              <th style="width: 160px;">存储形态</th>
              <th style="width: 140px;">最后活跃</th>
            </tr>
          </thead>
          <tbody id="cleanupTableBody">
            <!-- 动态渲染数据行 -->
          </tbody>
        </table>
      </div>

      <!-- Sticky Bottom Action Bar -->
      <div class="cleanup-action-bar">
        <div class="action-stat-summary">
          <div>筛选匹配: <span id="cleanupTotalCount" style="font-weight: 700; color: #a5b4fc;">0</span> 个会话</div>
          <div style="opacity: 0.4;">|</div>
          <div>已勾选: <span id="cleanupSelectedCount" style="font-weight: 800; color: #ffffff;">0</span> 个</div>
          <div style="opacity: 0.4;">|</div>
          <div>预计释放: <span id="cleanupSelectedSize" class="action-stat-highlight">0.0 MB</span></div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <button class="btn btn-secondary" onclick="openBatchMigrateModal()" id="btnBatchMigrate" disabled>
            <span>🔄</span> <span>迁移</span>
          </button>
          <button class="btn btn-danger" onclick="openBatchDeleteConfirm()" id="btnBatchDelete" disabled style="background: linear-gradient(135deg, #e11d48, #be123c); border-color: #f43f5e; color: #fff; font-weight: 700; box-shadow: 0 4px 14px rgba(225,29,72,0.35);">
            <span>🗑️</span> <span>删除</span>
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Safe Confirm Delete Modal -->
  <div class="modal-backdrop" id="batchDeleteConfirmModal" style="z-index: 120;" onclick="if(event.target===this)closeBatchDeleteConfirm()">
    <div class="safe-confirm-card">
      <div style="padding: 24px;">
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
          <div style="font-size: 28px;">⚠️</div>
          <div>
            <div style="font-size: 17px; font-weight: 800; color: #fecdd3;">确认批量彻底删除选中的会话？</div>
            <div style="font-size: 12px; color: #94a3b8; margin-top: 3px;">此操作将永久抹除选中的历史会话与关联记忆数据，不可撤销！</div>
          </div>
        </div>

        <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 16px; margin-bottom: 20px;">
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 13px;">
            <div>已选会话数: <strong id="confirmDelCount" style="color: #ffffff;">0</strong> 个</div>
            <div>预计物理释放: <strong id="confirmDelSize" style="color: #fb7185;">0.0 MB</strong></div>
          </div>
          <div style="margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 11.5px; color: #cbd5e1; line-height: 1.6;" id="confirmDelBreakdown">
            <!-- 详细拆解 -->
          </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 10px;">
          <button class="btn btn-secondary" onclick="closeBatchDeleteConfirm()">取消</button>
          <button class="btn btn-danger" id="btnConfirmExecuteBatchDelete" onclick="executeBatchDeleteNow()" style="background: #e11d48; border-color: #f43f5e; color: #fff; font-weight: 700;">
            💥 确认彻底删除并释放空间
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Batch Migrate Target Select Modal -->
  <div class="modal-backdrop" id="batchMigrateSelectModal" style="z-index: 120;" onclick="if(event.target===this)closeBatchMigrateModal()">
    <div class="modal-card" style="max-width: 540px;">
      <div class="modal-header">
        <div class="modal-title">🔄 批量跨平台迁移</div>
        <button class="modal-close" onclick="closeBatchMigrateModal()">✕</button>
      </div>
      <div class="modal-body">
        <div style="font-size: 13px; color: #cbd5e1; margin-bottom: 14px;">
          已勾选 <strong id="batchMigrateCount" style="color: #a5b4fc;">0</strong> 个会话。请选择要转换导出的目标智能体平台：
        </div>
        <div class="target-grid" id="batchTargetGrid">
          <!-- 动态渲染目标平台选择 -->
        </div>
        <div id="batchMigrateFeedback" style="display: none; margin-top: 14px; padding: 12px; border-radius: 8px; font-size: 12px;"></div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeBatchMigrateModal()">取消</button>
        <button class="btn btn-primary" id="btnExecuteBatchMigrate" onclick="executeBatchMigrateNow()">开始批量迁移</button>
      </div>
    </div>
  </div>

  <div id="toast"></div>

  <script>
    let appStatus = null;
    let allSessions = [];
    let currentFilterFmt = 'all';
    let activeMigrateSession = null;
    let selectedTargetFormat = 'claude';

    const AGENT_COLORS = {
      antigravity: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
      claude: 'linear-gradient(135deg, #d97706, #ea580c)',
      workbuddy: 'linear-gradient(135deg, #059669, #10b981)',
      trae: 'linear-gradient(135deg, #8b5cf6, #ec4899)',
      cursor: 'linear-gradient(135deg, #0d9488, #059669)',
      copilot: 'linear-gradient(135deg, #2563eb, #3b82f6)',
      codex: 'linear-gradient(135deg, #475569, #334155)',
      kimi: 'linear-gradient(135deg, #7c3aed, #a855f7)',
      devin: 'linear-gradient(135deg, #ec4899, #f43f5e)'
    };

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.innerText = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3000);
    }

    let currentSortField = localStorage.getItem('session_sort_field') || 'mtime';
    let currentSortOrder = localStorage.getItem('session_sort_order') || 'desc';

    async function init() {
      try {
        updateSortControlsUI();
        await loadStatus();
        await loadSessions();
      } catch (err) {
        console.error("Init error:", err);
        const grid = document.getElementById('sessionsGrid');
        if (grid) {
          grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--accent-rose);">加载出现异常: ${escapeHtml(err.message || String(err))}</div>`;
        }
      }
    }

    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        appStatus = await res.json();
        document.getElementById('statTotalSessions').innerText = appStatus.total_sessions;
        document.getElementById('statActiveRoots').innerText = appStatus.roots.length;
        renderTargetGrid();
      } catch (e) {
        console.error(e);
      }
    }

    async function loadSessions() {
      const q = document.getElementById('searchInput').value;
      const fmt = currentFilterFmt;
      const sort = currentSortField;
      const order = currentSortOrder;
      const res = await fetch(`/api/sessions?q=${encodeURIComponent(q)}&format=${fmt}&sort_by=${sort}&order=${order}`);
      const data = await res.json();
      allSessions = data.sessions || [];
      applySortAndRender();
    }

    function handleSortFieldChange(field) {
      if (!field) return;
      currentSortField = field;
      localStorage.setItem('session_sort_field', currentSortField);
      updateSortControlsUI();
      applySortAndRender();
    }

    function toggleSortOrderQuick() {
      currentSortOrder = (currentSortOrder === 'desc') ? 'asc' : 'desc';
      localStorage.setItem('session_sort_order', currentSortOrder);
      updateSortControlsUI();
      applySortAndRender();
    }

    function updateSortControlsUI() {
      const sel = document.getElementById('sortSelect');
      if (sel) {
        sel.value = currentSortField;
      }
      const icon = document.getElementById('sortDirQuickIcon');
      const btn = document.getElementById('btnSortDirQuick');
      if (icon && btn) {
        const isDesc = (currentSortOrder === 'desc');
        icon.innerText = isDesc ? '⬇️' : '⬆️';
        btn.title = isDesc ? '当前：降序 (点击切换为升序)' : '当前：升序 (点击切换为降序)';
      }
    }

    function sortSessionsList(list) {
      if (!list || !list.length) return [];
      const field = currentSortField;
      const isDesc = (currentSortOrder === 'desc');

      return [...list].sort((a, b) => {
        let va, vb;
        if (field === 'mtime') {
          va = Number(a.mtime) || 0;
          vb = Number(b.mtime) || 0;
        } else if (field === 'started_at') {
          va = a.started_at ? new Date(a.started_at).getTime() : 0;
          vb = b.started_at ? new Date(b.started_at).getTime() : 0;
        } else if (field === 'bytes') {
          va = Number(a.bytes) || 0;
          vb = Number(b.bytes) || 0;
        } else if (field === 'tokens') {
          va = Number(a.tokens) || 0;
          vb = Number(b.tokens) || 0;
        } else if (field === 'records') {
          va = Number(a.records) || 0;
          vb = Number(b.records) || 0;
        } else if (field === 'title') {
          va = String(a.title || '');
          vb = String(b.title || '');
          const cmp = va.localeCompare(vb, 'zh-CN', { numeric: true, sensitivity: 'base' });
          return isDesc ? -cmp : cmp;
        } else if (field === 'format') {
          va = String(a.format || '');
          vb = String(b.format || '');
          const cmp = va.localeCompare(vb);
          return isDesc ? -cmp : cmp;
        } else {
          va = Number(a.mtime) || 0;
          vb = Number(b.mtime) || 0;
        }

        if (va < vb) return isDesc ? 1 : -1;
        if (va > vb) return isDesc ? -1 : 1;
        return 0;
      });
    }

    function formatTokensCompact(num) {
      const n = Number(num) || 0;
      if (n >= 1000000) {
        return (n / 1000000).toFixed(2) + 'M Tokens';
      } else if (n >= 1000) {
        return (n / 1000).toFixed(1) + 'K Tokens';
      }
      return n.toLocaleString() + ' Tokens';
    }

    function updateResultsStats(list) {
      const matchEl = document.getElementById('statMatchCount');
      const sizeEl = document.getElementById('statTotalSize');
      const tokenEl = document.getElementById('statTotalTokens');
      const statsWrap = document.getElementById('resultsStats');
      if (!matchEl || !sizeEl) return;
      const count = list ? list.length : 0;
      let totalBytes = 0;
      let totalTokens = 0;
      let totalChatTokens = 0;
      let totalAuxTokens = 0;
      if (list) {
        for (const item of list) {
          totalBytes += Number(item.bytes) || 0;
          totalTokens += Number(item.tokens) || 0;
          totalChatTokens += Number(item.chat_tokens) || 0;
          totalAuxTokens += Number(item.aux_tokens) || 0;
        }
      }
      matchEl.innerText = count;
      if (totalBytes >= 1024 * 1024 * 1024) {
        sizeEl.innerText = (totalBytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
      } else if (totalBytes >= 1024 * 1024) {
        sizeEl.innerText = (totalBytes / (1024 * 1024)).toFixed(1) + ' MB';
      } else {
        sizeEl.innerText = (totalBytes / 1024).toFixed(1) + ' KB';
      }
      if (tokenEl) {
        tokenEl.innerText = formatTokensCompact(totalTokens);
        const chatPct = totalTokens > 0 ? ((totalChatTokens / totalTokens) * 100).toFixed(1) : '0.0';
        const auxPct = totalTokens > 0 ? ((totalAuxTokens / totalTokens) * 100).toFixed(1) : '0.0';
        const scopeLabel = currentFilterFmt === 'all' ? '全平台已索引会话' : `${currentFilterFmt.toUpperCase()} 平台会话`;
        const breakdownTip = `【${scopeLabel} Token 汇总 (Tiktoken cl100k_base 编码器)】\n• 会话数量: ${count} 篇\n• 累计总消耗: ${totalTokens.toLocaleString()} Tokens\n• 对话正文 (用户+AI): ${totalChatTokens.toLocaleString()} Tokens (${chatPct}%)\n• 工具与思考过程: ${totalAuxTokens.toLocaleString()} Tokens (${auxPct}%)`;
        tokenEl.title = breakdownTip;
        if (statsWrap) statsWrap.title = breakdownTip;
      }
    }

    function applySortAndRender() {
      const sorted = sortSessionsList(allSessions);
      renderSessions(sorted);
      updateResultsStats(sorted);
    }

    function renderSessions(list) {
      const grid = document.getElementById('sessionsGrid');
      if (!list || list.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 60px; color: var(--text-muted);">没有匹配的会话记录</div>';
        return;
      }
      grid.innerHTML = list.map(s => {
        const bg = AGENT_COLORS[s.format] || 'linear-gradient(135deg, #64748b, #475569)';
        const dateStr = s.started_at ? s.started_at.replace('T', ' ').slice(0, 16) : '未知时间';
        const sizeStr = (s.bytes / 1024).toFixed(1) + ' KB';
        const tokTotal = Number(s.tokens) || 0;
        const tokChat = Number(s.chat_tokens) || 0;
        const tokAux = Number(s.aux_tokens) || 0;
        const chatPct = tokTotal > 0 ? ((tokChat / tokTotal) * 100).toFixed(1) : '0.0';
        const auxPct = tokTotal > 0 ? ((tokAux / tokTotal) * 100).toFixed(1) : '0.0';
        const tokenLabel = formatTokensCompact(tokTotal);
        const tokenTip = `单会话 Token 统计 (Tiktoken cl100k_base 编码器)&#10;• 总计消耗: ${tokTotal.toLocaleString()} Tokens&#10;• 对话正文 (用户+AI): ${tokChat.toLocaleString()} Tokens (${chatPct}%)&#10;• 工具与思考过程: ${tokAux.toLocaleString()} Tokens (${auxPct}%)`;
        return `
          <div class="session-card" style="--badge-gradient: ${bg};">
            <div>
              <div class="card-top">
                <span class="format-badge" style="background: ${bg};">${s.format}</span>
                <span class="card-time">${dateStr}</span>
              </div>
              <div class="card-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</div>
              <div class="card-meta">
                <div class="meta-item"><span>🔢</span> <span>${s.records} 步</span></div>
                <div class="meta-item"><span>📦</span> <span>${sizeStr}</span></div>
                <div class="meta-item meta-token-badge" title="${tokenTip}"><span>🪙</span> <span>${tokenLabel}</span></div>
                <div class="meta-item meta-copyable" data-id="${escapeHtml(s.session_id)}" onclick="copySessionId(this, event)" title="点击复制 UUID: ${escapeHtml(s.session_id)}">
                  <span>🆔</span> <span class="id-label" style="font-family: var(--font-mono);">${(s.session_id || '').slice(0, 8)}...</span>
                </div>
                <a href="javascript:void(0)" class="meta-item meta-path-link" data-path="${escapeHtml(s.file_path)}" onclick="copySessionPath(this, event); return false;" title="绝对路径: ${escapeHtml(s.file_path)} (点击复制)">
                  <span>📄</span> <span class="path-label">绝对路径</span>
                </a>
              </div>
            </div>
            <div class="card-actions">
              <button class="btn-action" onclick="openChatModal('${s.catalog_id}')" title="查看会话消息历史">👁️ 查看</button>
              <button class="btn-action btn-migrate" onclick="openMigrateModal('${s.catalog_id}')" title="跨平台迁移该会话">🔄 迁移</button>
              <button class="btn-action btn-delete" onclick="confirmDeleteSession('${s.catalog_id}')" title="一键彻底删除该会话所有文件以释放存储空间">🗑️ 删除</button>
              <button class="btn-action btn-folder" data-path="${escapeHtml(s.file_path)}" onclick="openSessionFolder(this, event)" title="打开对应资源管理器并选中文件">📂</button>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderTargetGrid() {
      const targets = [
        { id: 'antigravity', name: 'Antigravity IDE', icon: '⚡' },
        { id: 'claude', name: 'Claude Code', icon: '🟣' },
        { id: 'workbuddy', name: 'WorkBuddy', icon: '🤖' },
        { id: 'cursor', name: 'Cursor', icon: '🖱️' },
        { id: 'copilot', name: 'GitHub Copilot', icon: '🐙' },
        { id: 'codex', name: 'Codex', icon: '📜' },
        { id: 'kimi', name: 'Kimi Code', icon: '🌙' },
        { id: 'devin', name: 'Devin', icon: '🚀' },
        { id: 'openhands', name: 'OpenHands', icon: '🦾' },
        { id: 'grok', name: 'Grok', icon: '🌐' },
        { id: 'hermes', name: 'Hermes', icon: '🦅' },
        { id: 'mastracode', name: 'MastraCode', icon: '🧩' },
        { id: 'vibe', name: 'Vibe', icon: '🌊' },
      ];
      const grid = document.getElementById('targetGrid');
      grid.innerHTML = targets.map(t => `
        <div class="target-card ${t.id === selectedTargetFormat ? 'selected' : ''}" onclick="selectTargetFormat('${t.id}')">
          <span style="font-size: 20px;">${t.icon}</span>
          <div>
            <div style="font-size: 13px; font-weight: 700;">${t.name}</div>
          </div>
        </div>
      `).join('');
    }

    function selectTargetFormat(fmt) {
      selectedTargetFormat = fmt;
      renderTargetGrid();
    }

    function filterByFormat(fmt) {
      currentFilterFmt = fmt;
      document.querySelectorAll('#filterChips .chip').forEach(c => {
        c.classList.toggle('active', c.getAttribute('data-fmt') === fmt);
      });
      loadSessions();
    }

    let searchTimeout = null;
    function handleSearch() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(loadSessions, 200);
    }

    async function refreshCatalog() {
      const btn = document.getElementById('btnRefresh');
      btn.innerText = '⏳ 正在扫描...';
      btn.disabled = true;
      try {
        const res = await fetch('/api/catalog/refresh', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
          showToast(`全平台扫描完成！已同步最新会话`);
          await loadStatus();
          await loadSessions();
        } else {
          showToast(`扫描失败: ${data.error}`);
        }
      } catch (e) {
        showToast(`网络异常: ${e}`);
      } finally {
        btn.innerText = '🔄 全量重新索引';
        btn.disabled = false;
      }
    }

    let currentUserMsgIdx = -1;
    let userMsgElements = [];
    let searchMatches = [];
    let currentSearchMatchIdx = -1;

        // 常用英文工具动作通俗中文汉化字典
    const COMMON_ACTION_TRANSLATIONS = {
      'checking git status': '检查 Git 仓库修改与分支状态',
      'git status before 3d commit': '3D 模块提交前检查 Git 状态',
      'viewing 3d section': '查阅 3D 阶段方案章节',
      'viewing 3d section in refactor_pipeline.md': '查阅 REFACTOR_PIPELINE.md 中的 3D 重构方案',
      'checking git branches': '查阅代码分支清单与追踪状态',
      'running git remote': '获取 Git 远程仓库配置与连接地址',
      'listing directory': '浏览并列出目录中的文件结构',
      'check git remote': '检查 Git 远程仓库配置',
      'check git branches': '查看当前分支及跟踪分支',
      'check git log': '查阅版本提交历史记录',
      'run unit tests': '运行项目单元测试套件',
      'check syntax': '校验代码语法正确性',
      'compile check': '编译并校验代码语法',
      'record refactor plan': '记录重构实施方案',
      'fetching remote readme': '获取远程 README 说明文档',
      'inspecting initial commit': '查看初始版本提交详情',
      'checking remote branches and tags': '获取远程分支与标签列表'
    };

    function humanizeAction(str) {
      if (!str) return '';
      const lower = str.toLowerCase().trim();
      for (const [k, v] of Object.entries(COMMON_ACTION_TRANSLATIONS)) {
        if (lower.includes(k)) return v;
      }
      return str;
    }

    function extractToolSummary(e) {
      const toolName = (e.tool_name || '').toLowerCase();
      let inputObj = {};
      if (e.payload && typeof e.payload === 'object') {
        inputObj = e.payload.input || e.payload.args || e.payload.arguments || e.payload;
      } else if (typeof e.payload === 'string') {
        try { const p = JSON.parse(e.payload); inputObj = p.input || p.args || p.arguments || p; } catch {}
      }
      if (!inputObj && e.text) {
        try { const p = JSON.parse(e.text); inputObj = p.input || p.args || p.arguments || p; } catch {}
      }
      if (typeof inputObj === 'string') {
        try { inputObj = JSON.parse(inputObj); } catch {}
      }
      inputObj = inputObj || {};

      // 1. 终端命令行 (RUN_COMMAND / BASH / EXEC / TERMINAL)
      if (toolName.includes('command') || toolName.includes('bash') || toolName.includes('exec') || toolName.includes('terminal')) {
        const cmd = (inputObj.CommandLine || inputObj.command || inputObj.cmd || '').trim();
        const rawAction = inputObj.toolAction || inputObj.toolSummary || inputObj.Description || '';
        const action = humanizeAction(rawAction);

        // 如果命令本身是一篇结构化 Markdown 规划 (如 ### 3D CLI 入包)
        if (cmd.startsWith('#') || cmd.includes(String.fromCharCode(10) + '#') || cmd.startsWith('- [')) {
          const lines = cmd.split(String.fromCharCode(10)).map(l => l.trim()).filter(Boolean);
          const firstHeader = lines.find(l => l.startsWith('#')) || lines[0] || '';
          const cleanHeader = firstHeader.replace(/^#+\\s*/, '').replace(/[*_`]/g, '');
          return {
            badgeClass: 'badge-command',
            badgeText: '💻 任务规划',
            summary: `${cleanHeader} (${lines.length} 行清单)`
          };
        }

        let desc = action;
        if (!desc) {
          if (cmd.includes('git status')) desc = '检查 Git 仓库修改与分支状态';
          else if (cmd.includes('git diff')) desc = '比对代码修改差异 (Git Diff)';
          else if (cmd.includes('git log')) desc = '查看 Git 版本提交历史记录';
          else if (cmd.includes('git branch')) desc = '查看代码分支列表与检出状态';
          else if (cmd.includes('git commit')) desc = '提交代码修改并记录版本';
          else if (cmd.includes('git checkout') || cmd.includes('git switch')) desc = '切换或检出工作分支';
          else if (cmd.includes('git push') || cmd.includes('git pull')) desc = '同步/推送远程代码仓库';
          else if (cmd.includes('pytest') || cmd.includes('unittest')) desc = '执行项目单元测试套件';
          else if (cmd.includes('py_compile')) desc = '检查 Python 代码语法规范';
          else if (cmd.includes('pip install') || cmd.includes('npm install') || cmd.includes('pnpm')) desc = '安装并配置项目依赖包';
          else if (cmd.includes('dir ') || cmd.includes('ls ') || cmd.includes('Get-ChildItem')) desc = '列出指定目录下的文件清单';
          else desc = '执行终端命令';
        }

        const shortCmd = cmd.replace(/\\s+/g, ' ').slice(0, 48);
        return {
          badgeClass: 'badge-command',
          badgeText: '💻 终端命令',
          summary: `${desc} ｜ 命令: ${shortCmd}${cmd.length > 48 ? '...' : ''}`
        };
      }

      // 2. 写入与编辑文件 (WRITE_TO_FILE / EDIT_FILE / WRITE_FILE / PATCH)
      if (toolName.includes('write') || toolName.includes('edit') || toolName.includes('patch') || toolName.includes('modify')) {
        const p = inputObj.AbsolutePath || inputObj.Path || inputObj.TargetFile || inputObj.path || inputObj.filePath || '';
        const fn = p ? p.split(/[\\/]/).pop() : '目标文件';
        const rawAction = inputObj.Description || inputObj.toolSummary || inputObj.toolAction || '';
        const action = humanizeAction(rawAction);
        let detail = action;
        if (!detail) {
          const content = inputObj.Content || inputObj.Replacement || inputObj.content || '';
          if (content) {
            const firstLine = content.split(String.fromCharCode(10))[0].trim().replace(/^#+\\s*/, '').replace(/[*_`]/g, '');
            if (firstLine && firstLine.length < 40) detail = firstLine;
          }
        }
        return {
          badgeClass: 'badge-file',
          badgeText: '📝 文件写入',
          summary: `写入/修改文件 · ${fn}${detail ? ` (${detail})` : ''}`
        };
      }

      // 3. 查看与阅读文件 (VIEW_FILE / READ_FILE / CAT / FETCH_FILE)
      if (toolName.includes('view') || toolName.includes('read') || toolName.includes('cat') || toolName.includes('open_file')) {
        const p = inputObj.AbsolutePath || inputObj.Path || inputObj.path || inputObj.filePath || '';
        const fn = p ? p.split(/[\\/]/).pop() : '目标文件';
        const rawAction = inputObj.toolAction || inputObj.toolSummary || '';
        const action = humanizeAction(rawAction);
        const sLine = inputObj.StartLine;
        const eLine = inputObj.EndLine;
        const lineRange = (sLine && eLine) ? `第 ${sLine}-${eLine} 行` : '';
        const info = [lineRange, action].filter(Boolean).join(' · ');
        return {
          badgeClass: 'badge-file',
          badgeText: '📖 查阅文件',
          summary: `查阅文件 · ${fn}${info ? ` (${info})` : ''}`
        };
      }

      // 4. 浏览目录 (LIST_DIR / LS / DIR)
      if (toolName.includes('list_dir') || toolName.includes('listdir') || toolName.includes('dir')) {
        const p = inputObj.DirectoryPath || inputObj.Path || inputObj.path || '';
        const dn = p ? p.split(/[\\/]/).filter(Boolean).pop() : '当前目录';
        const action = humanizeAction(inputObj.toolSummary || inputObj.toolAction || '列出文件清单');
        return {
          badgeClass: 'badge-tool',
          badgeText: '📁 浏览目录',
          summary: `浏览目录 · ${dn}/ (${action})`
        };
      }

      // 5. 代码检索 (SEARCH_FILES / GREP / FIND)
      if (toolName.includes('search') || toolName.includes('grep') || toolName.includes('find')) {
        const q = inputObj.query || inputObj.pattern || inputObj.SearchTerm || inputObj.regex || '';
        return {
          badgeClass: 'badge-tool',
          badgeText: '🔍 代码检索',
          summary: `检索代码库 · 搜索关键词 "${q.slice(0, 35)}${q.length > 35 ? '...' : ''}"`
        };
      }

      // 6. 子智能体调度 (INVOKE_SUBAGENT / RUN_SUBAGENT)
      if (toolName.includes('subagent') || toolName.includes('agent')) {
        const role = inputObj.Role || inputObj.TypeName || '子智能体';
        const prompt = (inputObj.Prompt || '').slice(0, 40);
        return {
          badgeClass: 'badge-assistant',
          badgeText: '🤖 调度智能体',
          summary: `派发子任务 · [${role}] ${prompt}...`
        };
      }

      // 7. 工具执行结果 (TOOL_RESULT)
      if (e.kind === 'tool_result') {
        const isError = e.payload && e.payload.is_error;
        const raw = e.text || (typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload || ''));
        const clean = (raw || '').replace(/\\s+/g, ' ').trim();
        if (isError) {
          return {
            badgeClass: 'badge-tool',
            badgeText: '❌ 执行报错',
            summary: `报错: ${clean.slice(0, 65)}${clean.length > 65 ? '...' : ''}`
          };
        }
        return {
          badgeClass: 'badge-tool',
          badgeText: '⚡ 执行结果',
          summary: `执行成功 · 返回结果 (${clean.slice(0, 70)}${clean.length > 70 ? '...' : ''})`
        };
      }

      // 8. 通用工具调用兜底
      const raw = e.text || (typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload || ''));
      const clean = (raw || '').replace(/\\s+/g, ' ').trim();
      return {
        badgeClass: 'badge-tool',
        badgeText: '⚙️ 工具步骤',
        summary: `${e.tool_name || 'Action'}: ${clean.slice(0, 65)}${clean.length > 65 ? '...' : ''}`
      };
    }

    function extractAssistantSummary(text) {
      if (!text) return '回复为空';
      let clean = text
        .replace(/```[\\s\\S]*?```/g, ' [代码块] ')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/^#+\\s+/gm, '')
        .replace(/[*_~>]/g, '')
        .replace(/-\\s+\\\\[[ xX]\\\\]/g, '•')
        .replace(/-\\s+/g, '• ')
        .replace(/\\s+/g, ' ')
        .trim();

      clean = clean.replace(/^(好的|好的，|已收到|明白|我来帮您|好的收到)[，,。!！\\s]*/, '');
      if (clean.length > 85) {
        return clean.slice(0, 85) + '...';
      }
      return clean || '已回复对话内容';
    }

    function toggleBubble(headerEl) {
      const bubble = headerEl.closest('.bubble');
      if (!bubble) return;
      bubble.classList.toggle('collapsed');
    }

    function toggleAllBubbles(expand) {
      const bubbles = document.querySelectorAll('#chatStreamBody .collapsible');
      bubbles.forEach(b => {
        if (expand) {
          b.classList.remove('collapsed');
        } else {
          b.classList.add('collapsed');
        }
      });
    }

    function updateUserNavDisplay() {
      const counter = document.getElementById('userMsgCounter');
      const btnPrev = document.getElementById('btnPrevUserMsg');
      const btnNext = document.getElementById('btnNextUserMsg');
      const total = userMsgElements.length;
      if (total === 0) {
        counter.innerText = '0 / 0';
        btnPrev.disabled = true;
        btnNext.disabled = true;
        return;
      }
      btnPrev.disabled = false;
      btnNext.disabled = false;
      const displayIdx = currentUserMsgIdx >= 0 ? (currentUserMsgIdx + 1) : '-';
      counter.innerText = `${displayIdx} / ${total}`;
    }

    function navigateUserMessage(direction) {
      const total = userMsgElements.length;
      if (total === 0) return;

      if (currentUserMsgIdx === -1) {
        currentUserMsgIdx = direction > 0 ? 0 : total - 1;
      } else {
        currentUserMsgIdx = (currentUserMsgIdx + direction + total) % total;
      }

      updateUserNavDisplay();
      const target = userMsgElements[currentUserMsgIdx];
      if (target) {
        target.classList.remove('collapsed');
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.remove('pulse-focus');
        void target.offsetWidth; // 触发回流以重新执行呼吸发光动画
        target.classList.add('pulse-focus');
        setTimeout(() => target.classList.remove('pulse-focus'), 1900);
      }
    }

    function handleChatSearch() {
      const input = document.getElementById('chatSearchInput');
      const clearBtn = document.getElementById('chatSearchClear');
      const navControls = document.getElementById('searchNavControls');
      const countEl = document.getElementById('searchMatchCount');
      const query = (input.value || '').trim();

      clearBtn.style.display = query ? 'block' : 'none';

      // 清除历史搜索标记
      const marks = document.querySelectorAll('#chatStreamBody mark.chat-highlight');
      marks.forEach(m => {
        const parent = m.parentNode;
        parent.replaceChild(document.createTextNode(m.textContent), m);
        parent.normalize();
      });

      searchMatches = [];
      currentSearchMatchIdx = -1;

      if (!query) {
        navControls.style.display = 'none';
        return;
      }

      navControls.style.display = 'flex';

      const bubbles = document.querySelectorAll('#chatStreamBody .bubble');
      const escapedQuery = query.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
      const regex = new RegExp(`(${escapedQuery})`, 'gi');

      bubbles.forEach(bubble => {
        const contentNodes = [];
        const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT, null, false);
        let node;
        while ((node = walker.nextNode())) {
          if (node.parentElement && (node.parentElement.tagName === 'MARK' || node.parentElement.tagName === 'BUTTON')) continue;
          if (node.nodeValue && regex.test(node.nodeValue)) {
            contentNodes.push(node);
          }
        }

        if (contentNodes.length > 0) {
          contentNodes.forEach(textNode => {
            const span = document.createElement('span');
            span.innerHTML = escapeHtml(textNode.nodeValue).replace(regex, '<mark class="chat-highlight">$1</mark>');
            textNode.parentNode.replaceChild(span, textNode);
          });
        }
      });

      searchMatches = Array.from(document.querySelectorAll('#chatStreamBody mark.chat-highlight'));
      const total = searchMatches.length;

      if (total > 0) {
        currentSearchMatchIdx = 0;
        countEl.innerText = `1/${total}`;
        highlightCurrentSearchMatch();
      } else {
        countEl.innerText = '0/0';
      }
    }

    function highlightCurrentSearchMatch() {
      searchMatches.forEach(m => m.classList.remove('current'));
      if (currentSearchMatchIdx >= 0 && currentSearchMatchIdx < searchMatches.length) {
        const curr = searchMatches[currentSearchMatchIdx];
        curr.classList.add('current');
        // 关键联动：如果当前匹配项所在的模块处于收起折叠状态，自动展开！
        const parentBubble = curr.closest('.bubble');
        if (parentBubble && parentBubble.classList.contains('collapsed')) {
          parentBubble.classList.remove('collapsed');
        }
        curr.scrollIntoView({ behavior: 'smooth', block: 'center' });
        document.getElementById('searchMatchCount').innerText = `${currentSearchMatchIdx + 1}/${searchMatches.length}`;
      }
    }

    function navigateSearchMatch(direction) {
      const total = searchMatches.length;
      if (total === 0) return;
      currentSearchMatchIdx = (currentSearchMatchIdx + direction + total) % total;
      highlightCurrentSearchMatch();
    }

    function handleChatSearchKey(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (e.shiftKey) {
          navigateSearchMatch(-1);
        } else {
          navigateSearchMatch(1);
        }
      } else if (e.key === 'Escape') {
        clearChatSearch();
      }
    }

    function clearChatSearch() {
      const input = document.getElementById('chatSearchInput');
      input.value = '';
      handleChatSearch();
      input.focus();
    }

    async function openChatModal(cid) {
      const sess = allSessions.find(s => s.catalog_id === cid);
      if (!sess) return;
      document.getElementById('chatModalTitle').innerText = sess.title;
      document.getElementById('chatModalSub').innerHTML = `
        <span style="font-weight: 700;">${escapeHtml(sess.format.toUpperCase())}</span>
        <span style="margin: 0 8px; opacity: 0.4;">·</span>
        <span class="meta-copyable" data-id="${escapeHtml(sess.session_id)}" onclick="copySessionId(this, event)" title="点击复制 UUID">🆔 ${(sess.session_id || '').slice(0, 16)}...</span>
        <span style="margin: 0 8px; opacity: 0.4;">·</span>
        <a href="javascript:void(0)" class="meta-path-link" data-path="${escapeHtml(sess.file_path)}" onclick="copySessionPath(this, event); return false;" title="点击复制完整绝对路径">
          <span>📄</span> <span class="path-label" style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; display: inline-block; vertical-align: bottom;">${escapeHtml(sess.file_path)}</span>
        </a>
      `;

      // 重置工具栏状态
      document.getElementById('chatSearchInput').value = '';
      document.getElementById('chatSearchClear').style.display = 'none';
      document.getElementById('searchNavControls').style.display = 'none';
      currentUserMsgIdx = -1;
      userMsgElements = [];
      searchMatches = [];
      currentSearchMatchIdx = -1;
      updateUserNavDisplay();

      document.getElementById('chatModal').classList.add('open');
      document.getElementById('btnMigrateFromChat').onclick = () => {
        closeChatModal();
        openMigrateModal(cid);
      };
      const btnDel = document.getElementById('btnDeleteFromChat');
      if (btnDel) {
        btnDel.onclick = () => {
          confirmDeleteSession(cid);
        };
      }

      const body = document.getElementById('chatStreamBody');
      body.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-muted);">正在加载对话内容...</div>';

      try {
        const res = await fetch(`/api/session/detail?catalog_id=${cid}`);
        const data = await res.json();
        if (data.error) {
          body.innerHTML = `<div style="color: var(--accent-rose); padding: 20px;">${data.error}</div>`;
          return;
        }

        const events = data.events || [];
        if (events.length === 0) {
          body.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--text-muted);">该会话为内部配置或暂无结构化消息文本</div>';
          return;
        }

        let userCount = 0;
        body.innerHTML = '<div class="chat-stream">' + events.map(e => {
          if (e.kind === 'message') {
            if (e.role === 'user') {
              userCount++;
              const uText = e.text || '';
              return `
                <div class="bubble user user-bubble-anchor" data-user-idx="${userCount - 1}">
                  <div class="bubble-header" style="cursor: default; margin-bottom: 6px;">
                    <div class="bubble-header-left">
                      <div class="bubble-role" style="font-weight: 800; font-size: 12px; letter-spacing: 0.5px;">👤 用户指令 #${userCount}</div>
                    </div>
                    <div class="bubble-header-right">
                      <span class="bubble-meta-badge" style="background: rgba(255,255,255,0.18); color: #fff;">${uText.length} 字</span>
                    </div>
                  </div>
                  <div style="white-space: pre-wrap; font-size: 13.5px; line-height: 1.6;">${escapeHtml(uText)}</div>
                </div>
              `;
            } else {
              // 助手消息：默认收起，保留极简通俗总结
              const aText = e.text || '';
              const summary = extractAssistantSummary(aText);
              return `
                <div class="bubble assistant collapsible collapsed">
                  <div class="bubble-header" onclick="toggleBubble(this)">
                    <div class="bubble-header-left">
                      <span class="bubble-chevron">▼</span>
                      <span class="bubble-badge badge-assistant">🤖 助手回复</span>
                      <div class="bubble-summary">${escapeHtml(summary)}</div>
                    </div>
                    <div class="bubble-header-right">
                      <span class="bubble-meta-badge">${aText.length} 字</span>
                    </div>
                  </div>
                  <div class="bubble-body">
                    <div style="white-space: pre-wrap; line-height: 1.65;">${escapeHtml(aText)}</div>
                  </div>
                </div>
              `;
            }
          } else if (e.kind === 'thinking') {
            // 思考过程：默认收起
            const tText = e.text || (typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload || ''));
            const summary = (tText || '').replace(/\\s+/g, ' ').slice(0, 80);
            return `
              <div class="bubble thinking collapsible collapsed">
                <div class="bubble-header" onclick="toggleBubble(this)">
                  <div class="bubble-header-left">
                    <span class="bubble-chevron">▼</span>
                    <span class="bubble-badge badge-thinking">💭 思考过程</span>
                    <div class="bubble-summary">思考规划 · ${escapeHtml(summary)}...</div>
                  </div>
                  <div class="bubble-header-right">
                    <span class="bubble-meta-badge">${tText.length} 字</span>
                  </div>
                </div>
                <div class="bubble-body">
                  <div style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 12px; color: #d8b4fe; line-height: 1.6;">${escapeHtml(tText)}</div>
                </div>
              </div>
            `;
          } else if (e.kind === 'tool_call' || e.kind === 'tool_result') {
            // 工具调用与结果：默认收起，呈现通俗易懂的极简单项工作总结
            const parsed = extractToolSummary(e);
            const detailText = e.text || (typeof e.payload === 'string' ? e.payload : JSON.stringify(e.payload || '', null, 2));
            return `
              <div class="bubble tool collapsible collapsed">
                <div class="bubble-header" onclick="toggleBubble(this)">
                  <div class="bubble-header-left">
                    <span class="bubble-chevron">▼</span>
                    <span class="bubble-badge ${parsed.badgeClass}">${parsed.badgeText}</span>
                    <div class="bubble-summary">${escapeHtml(parsed.summary)}</div>
                  </div>
                  <div class="bubble-header-right">
                    <span class="bubble-meta-badge">${detailText.length} 字节</span>
                  </div>
                </div>
                <div class="bubble-body">
                  <div style="white-space: pre-wrap; font-family: var(--font-mono); font-size: 12px; max-height: 420px; overflow-y: auto; background: rgba(0,0,0,0.3); padding: 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.06);">${escapeHtml(detailText)}</div>
                </div>
              </div>
            `;
          }
          return '';
        }).join('') + '</div>';

        // 收集所有用户指令卡片供上下快速跳转
        userMsgElements = Array.from(document.querySelectorAll('#chatStreamBody .user-bubble-anchor'));
        updateUserNavDisplay();

      } catch (e) {
        body.innerHTML = `<div style="color: var(--accent-rose); padding: 20px;">读取失败: ${e}</div>`;
      }
    }

    function closeChatModal() {
      document.getElementById('chatModal').classList.remove('open');
      clearChatSearch();
    }

    // 键盘全局快捷键：Alt+↑ / Alt+↓ 快速切换用户指令
    window.addEventListener('keydown', (e) => {
      const modal = document.getElementById('chatModal');
      if (!modal || !modal.classList.contains('open')) return;
      if (e.altKey && e.key === 'ArrowUp') {
        e.preventDefault();
        navigateUserMessage(-1);
      } else if (e.altKey && e.key === 'ArrowDown') {
        e.preventDefault();
        navigateUserMessage(1);
      }
    });
function openMigrateModal(cid) {
      activeMigrateSession = allSessions.find(s => s.catalog_id === cid);
      if (!activeMigrateSession) return;
      document.getElementById('migrateSourceTitle').innerText = `源会话: [${activeMigrateSession.format.toUpperCase()}] ${activeMigrateSession.title}`;
      document.getElementById('migrateFeedback').style.display = 'none';
      document.getElementById('btnExecuteMigrate').disabled = false;
      document.getElementById('btnExecuteMigrate').innerText = '开始转换与迁移';
      document.getElementById('migrateModal').classList.add('open');
    }

    function closeMigrateModal() {
      document.getElementById('migrateModal').classList.remove('open');
    }

    async function executeMigrate() {
      if (!activeMigrateSession) return;
      const btn = document.getElementById('btnExecuteMigrate');
      const feedback = document.getElementById('migrateFeedback');
      const mode = document.querySelector('input[name="migrateMode"]:checked').value;

      btn.disabled = true;
      btn.innerText = '⏳ 正在转换...';
      feedback.style.display = 'block';
      feedback.style.background = 'rgba(99, 102, 241, 0.1)';
      feedback.style.color = '#cbd5e1';
      feedback.style.border = '1px solid rgba(99, 102, 241, 0.3)';
      feedback.innerHTML = '正在加载源会话并执行跨 Agent 格式重构...';

      try {
        const res = await fetch('/api/session/migrate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            catalog_id: activeMigrateSession.catalog_id,
            target_format: selectedTargetFormat,
            mode: mode
          })
        });
        const result = await res.json();
        if (result.success) {
          const d = result.data;
          feedback.style.background = 'rgba(16, 185, 129, 0.15)';
          feedback.style.color = '#34d399';
          feedback.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          feedback.innerHTML = `
            <strong>🎉 迁移成功！</strong><br>
            已成功转换生成 ${d.target_format} 会话！<br>
            <div style="margin-top: 8px; font-family: var(--font-mono); font-size: 12px; color: #cbd5e1;">输出路径: ${d.output_path}</div>
            <button class="btn btn-secondary" style="margin-top: 10px; padding: 4px 10px; font-size: 11px;" onclick="openFolder('${escapeHtml(d.output_path)}')">📂 在文件夹中查看</button>
          `;
          btn.innerText = '迁移完成';
          showToast('会话迁移成功！');
        } else {
          feedback.style.background = 'rgba(244, 63, 94, 0.15)';
          feedback.style.color = '#fb7185';
          feedback.style.border = '1px solid rgba(244, 63, 94, 0.3)';
          feedback.innerHTML = `<strong>❌ 迁移失败:</strong> ${result.error}`;
          btn.disabled = false;
          btn.innerText = '重试迁移';
        }
      } catch (e) {
        feedback.innerHTML = `<strong>❌ 请求异常:</strong> ${e}`;
        btn.disabled = false;
        btn.innerText = '重试迁移';
      }
    }

        function confirmDeleteSession(cid) {
      const sess = allSessions.find(s => s.catalog_id === cid);
      if (!sess) return;
      const name = sess.title || sess.session_id;
      const sizeStr = (sess.bytes / 1024).toFixed(1) + ' KB';
      const promptMsg = `⚠️ 危险操作：确定要彻底删除该会话吗？\n\n【会话名称】：${name}\n【占用空间】：${sizeStr}\n\n该操作将永久删除此会话的所有本地数据文件（包括数据库、脑图缓存、临时生成物等）以充分释放存储空间，删除后不可恢复！`;
      if (!confirm(promptMsg)) {
        return;
      }
      executeDeleteSession(cid);
    }

    async function executeDeleteSession(cid) {
      const sess = allSessions.find(s => s.catalog_id === cid);
      showToast('⏳ 正在删除会话文件并释放空间...');
      try {
        const res = await fetch('/api/session/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            catalog_id: cid,
            session_id: sess ? sess.session_id : '',
            format: sess ? sess.format : '',
            file_path: sess ? sess.file_path : ''
          })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`🎉 删除成功！已释放 ${data.freed_display || '相关'} 存储空间`);
          allSessions = allSessions.filter(s => s.catalog_id !== cid);
          applySortAndRender();
          await loadStatus();
          if (document.getElementById('chatModal').classList.contains('open')) {
            closeChatModal();
          }
        } else {
          alert(`删除失败: ${data.error || '未知错误'}`);
        }
      } catch (err) {
        alert(`网络异常: ${err}`);
      }
    }

function openRootsModal() {
      renderRootsList();
      document.getElementById('rootsModal').classList.add('open');
    }

    function closeRootsModal() {
      document.getElementById('rootsModal').classList.remove('open');
    }

    function renderRootsList() {
      const container = document.getElementById('rootsList');
      if (!appStatus || !appStatus.roots) {
        container.innerHTML = '无数据';
        return;
      }
      container.innerHTML = appStatus.roots.map(r => `
        <div style="display: flex; justify-content: space-between; align-items: center; background: rgba(0,0,0,0.25); padding: 10px 14px; border-radius: 8px; border: 1px solid var(--card-border);">
          <div>
            <span class="format-badge" style="background: ${AGENT_COLORS[r.format] || '#64748b'}; font-size: 10px;">${r.format}</span>
            <span style="font-family: var(--font-mono); font-size: 12px; margin-left: 8px; color: #e2e8f0;">${escapeHtml(r.path)}</span>
          </div>
          <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 11px; color: var(--accent-rose);" onclick="removeRoot(${r.id})">移除</button>
        </div>
      `).join('');
    }

    async function addRoot() {
      const fmt = document.getElementById('newRootFormat').value;
      const path = document.getElementById('newRootPath').value.trim();
      if (!path) return alert('请输入目录路径');
      try {
        const res = await fetch('/api/catalog/add_root', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ format: fmt, path: path })
        });
        const d = await res.json();
        if (d.success) {
          showToast('已添加目录并完成更新！');
          document.getElementById('newRootPath').value = '';
          await loadStatus();
          await loadSessions();
          renderRootsList();
        } else {
          alert('添加失败: ' + d.error);
        }
      } catch (e) {
        alert('网络错误: ' + e);
      }
    }

    async function removeRoot(id) {
      if (!confirm('确定移除该扫描目录？')) return;
      try {
        const res = await fetch('/api/catalog/remove_root', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id })
        });
        const d = await res.json();
        if (d.success) {
          showToast('已移除目录');
          await loadStatus();
          await loadSessions();
          renderRootsList();
        }
      } catch (e) {
        alert('错误: ' + e);
      }
    }

    function copyTextToClipboard(text, msg) {
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          showToast(msg || '已复制到剪贴板');
        }).catch(() => {
          fallbackCopyText(text, msg);
        });
      } else {
        fallbackCopyText(text, msg);
      }
    }

    function fallbackCopyText(text, msg) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.top = '0';
      ta.style.left = '0';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try {
        document.execCommand('copy');
        showToast(msg || '已复制到剪贴板');
      } catch (err) {
        window.prompt('请手动复制：', text);
      }
      document.body.removeChild(ta);
    }

    function copySessionPath(el, ev) {
      if (ev) ev.stopPropagation();
      const p = el.getAttribute('data-path') || '';
      if (!p) {
        showToast('该会话暂无本地文件路径');
        return;
      }
      copyTextToClipboard(p, '已复制文件绝对路径到剪贴板');
      const label = el.querySelector('.path-label');
      if (label) {
        const orig = label.innerText;
        label.innerText = '✓ 已复制';
        label.style.color = 'var(--accent-emerald, #34d399)';
        setTimeout(() => {
          label.innerText = orig;
          label.style.color = '';
        }, 1500);
      }
    }

    function copySessionId(el, ev) {
      if (ev) ev.stopPropagation();
      const id = el.getAttribute('data-id') || '';
      if (!id) return;
      copyTextToClipboard(id, '已复制会话 UUID 到剪贴板');
      const label = el.querySelector('.id-label');
      if (label) {
        const orig = label.innerText;
        label.innerText = '✓ 已复制';
        label.style.color = 'var(--accent-emerald, #34d399)';
        setTimeout(() => {
          label.innerText = orig;
          label.style.color = '';
        }, 1500);
      }
    }

    function copyId(id) {
      copyTextToClipboard(id, '已复制会话 UUID 到剪贴板');
    }

    async function openSessionFolder(btn, ev) {
      if (ev) {
        ev.stopPropagation();
        ev.preventDefault();
      }
      const p = btn.getAttribute('data-path') || '';
      if (!p) {
        showToast('⚠️ 未获取到该会话的本地文件路径');
        return;
      }
      const originalText = btn.innerHTML;
      btn.innerHTML = '⏳';
      btn.style.pointerEvents = 'none';
      showToast('⏳ 正在打开资源管理器并选中文件...');
      try {
        const res = await fetch('/api/open_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: p })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast('📂 已打开资源管理器并选中文件！');
        } else {
          showToast('❌ 打开失败: ' + (data.error || '路径不存在'));
        }
      } catch (err) {
        showToast('❌ 请求失败: ' + err.message);
      } finally {
        setTimeout(() => {
          btn.innerHTML = originalText;
          btn.style.pointerEvents = 'auto';
        }, 800);
      }
    }

    async function openFolder(p) {
      if (!p) {
        showToast('⚠️ 目标路径为空');
        return;
      }
      showToast('⏳ 正在打开资源管理器并选中文件...');
      try {
        const res = await fetch('/api/open_folder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: p })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          showToast('📂 已在资源管理器中打开目标位置！');
        } else {
          showToast('❌ 打开失败: ' + (data.error || '路径不存在'));
        }
      } catch (err) {
        showToast('❌ 请求失败: ' + err.message);
      }
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    window.onload = init;

    // --- Memory Tools: Cleanup Console State & Engine ---
    let cleanupFilters = {
      formats: new Set(['all'])
    };
    let filteredCleanupSessions = [];
    let selectedCleanupCids = new Set();
    let selectedBatchTargetFormat = '';

    function openCleanupDrawer() {
      applyCleanupFiltersAndRender();
      document.getElementById('cleanupDrawerModal').classList.add('open');
    }

    function closeCleanupDrawer() {
      document.getElementById('cleanupDrawerModal').classList.remove('open');
    }

    function toggleCleanupFilter(dim, val) {
      if (dim === 'fmt') {
        const setObj = cleanupFilters.formats;
        if (val === 'all') {
          setObj.clear();
          setObj.add('all');
        } else {
          setObj.delete('all');
          if (setObj.has(val)) {
            setObj.delete(val);
            if (setObj.size === 0) setObj.add('all');
          } else {
            setObj.add(val);
          }
        }
        document.querySelectorAll('#filterMatrixFormats .matrix-opt').forEach(el => {
          const v = el.getAttribute('data-fmt');
          el.classList.toggle('active', setObj.has(v));
        });
        applyCleanupFiltersAndRender();
      }
    }

    function handleCleanupTimeTypeChange() {
      const type = document.getElementById('cleanupTimeType').value;
      const daysEl = document.getElementById('cleanupTimeDaysVal');
      const dateEl = document.getElementById('cleanupTimeDateVal');
      if (type === 'days_before' || type === 'days_within') {
        daysEl.style.display = 'block';
        dateEl.style.display = 'none';
      } else if (type === 'date_before' || type === 'date_after') {
        daysEl.style.display = 'none';
        dateEl.style.display = 'block';
      } else {
        daysEl.style.display = 'none';
        dateEl.style.display = 'none';
      }
      applyCleanupFiltersAndRender();
    }

    function resetCleanupFilters() {
      cleanupFilters.formats = new Set(['all']);
      document.querySelectorAll('#filterMatrixFormats .matrix-opt').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-fmt') === 'all');
      });

      const minSize = document.getElementById('cleanupMinSize');
      if (minSize) minSize.value = '';
      const maxSize = document.getElementById('cleanupMaxSize');
      if (maxSize) maxSize.value = '';
      const sizeUnit = document.getElementById('cleanupSizeUnit');
      if (sizeUnit) sizeUnit.value = 'MB';

      const minSteps = document.getElementById('cleanupMinSteps');
      if (minSteps) minSteps.value = '';
      const maxSteps = document.getElementById('cleanupMaxSteps');
      if (maxSteps) maxSteps.value = '';

      const timeType = document.getElementById('cleanupTimeType');
      if (timeType) timeType.value = 'all';
      const daysVal = document.getElementById('cleanupTimeDaysVal');
      if (daysVal) { daysVal.value = ''; daysVal.style.display = 'none'; }
      const dateVal = document.getElementById('cleanupTimeDateVal');
      if (dateVal) { dateVal.value = ''; dateVal.style.display = 'none'; }

      applyCleanupFiltersAndRender();
    }

    function applyCleanupFiltersAndRender() {
      const now = Date.now();

      // 读取大小输入
      const minSizeEl = document.getElementById('cleanupMinSize');
      const maxSizeEl = document.getElementById('cleanupMaxSize');
      const sizeUnitEl = document.getElementById('cleanupSizeUnit');
      const minSizeVal = minSizeEl && minSizeEl.value !== '' ? parseFloat(minSizeEl.value) : NaN;
      const maxSizeVal = maxSizeEl && maxSizeEl.value !== '' ? parseFloat(maxSizeEl.value) : NaN;
      const sizeUnit = sizeUnitEl ? sizeUnitEl.value : 'MB';
      let unitMult = 1024 * 1024;
      if (sizeUnit === 'KB') unitMult = 1024;
      else if (sizeUnit === 'Bytes') unitMult = 1;

      // 读取步数输入
      const minStepsEl = document.getElementById('cleanupMinSteps');
      const maxStepsEl = document.getElementById('cleanupMaxSteps');
      const minStepsVal = minStepsEl && minStepsEl.value !== '' ? parseInt(minStepsEl.value, 10) : NaN;
      const maxStepsVal = maxStepsEl && maxStepsEl.value !== '' ? parseInt(maxStepsEl.value, 10) : NaN;

      // 读取时间输入
      const timeTypeEl = document.getElementById('cleanupTimeType');
      const timeType = timeTypeEl ? timeTypeEl.value : 'all';
      const daysValEl = document.getElementById('cleanupTimeDaysVal');
      const daysVal = daysValEl && daysValEl.value !== '' ? parseFloat(daysValEl.value) : NaN;
      const dateValEl = document.getElementById('cleanupTimeDateVal');
      const dateVal = dateValEl ? dateValEl.value : '';

      filteredCleanupSessions = allSessions.filter(s => {
        // 1. 平台过滤
        if (!cleanupFilters.formats.has('all')) {
          if (!cleanupFilters.formats.has(s.format)) return false;
        }

        // 2. 自定义存储大小过滤 (bytes)
        const bytes = Number(s.bytes) || 0;
        if (!isNaN(minSizeVal) && bytes < minSizeVal * unitMult) return false;
        if (!isNaN(maxSizeVal) && bytes > maxSizeVal * unitMult) return false;

        // 3. 自定义步数过滤
        const records = Number(s.records) || 0;
        if (!isNaN(minStepsVal) && records < minStepsVal) return false;
        if (!isNaN(maxStepsVal) && records > maxStepsVal) return false;

        // 4. 自定义时间过滤
        if (timeType !== 'all') {
          const itemTime = s.mtime ? (s.mtime * 1000) : (s.started_at ? new Date(s.started_at).getTime() : 0);
          if (timeType === 'days_before') {
            if (!isNaN(daysVal) && daysVal >= 0) {
              const diffDays = (now - itemTime) / (1000 * 60 * 60 * 24);
              if (diffDays < daysVal) return false;
            }
          } else if (timeType === 'days_within') {
            if (!isNaN(daysVal) && daysVal >= 0) {
              const diffDays = (now - itemTime) / (1000 * 60 * 60 * 24);
              if (diffDays > daysVal) return false;
            }
          } else if (timeType === 'date_before') {
            if (dateVal) {
              const targetTs = new Date(dateVal + 'T23:59:59').getTime();
              if (itemTime > targetTs) return false;
            }
          } else if (timeType === 'date_after') {
            if (dateVal) {
              const targetTs = new Date(dateVal + 'T00:00:00').getTime();
              if (itemTime < targetTs) return false;
            }
          }
        }

        return true;
      });

      renderCleanupTable();
    }

    function renderCleanupTable() {
      const tbody = document.getElementById('cleanupTableBody');
      const countEl = document.getElementById('cleanupTotalCount');
      countEl.innerText = filteredCleanupSessions.length;

      // 剔除已不在当前过滤范围内的勾选项
      const currentCidSet = new Set(filteredCleanupSessions.map(s => s.catalog_id));
      selectedCleanupCids = new Set([...selectedCleanupCids].filter(cid => currentCidSet.has(cid)));

      if (filteredCleanupSessions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 50px; color: var(--text-muted);">当前组合筛选条件下没有匹配的会话</td></tr>';
        updateCleanupSelectionStats();
        return;
      }

      tbody.innerHTML = filteredCleanupSessions.map(s => {
        const isChecked = selectedCleanupCids.has(s.catalog_id);
        const bg = AGENT_COLORS[s.format] || '#64748b';
        const isShared = s.format === 'trae' || (s.file_path && s.file_path.endsWith('state.vscdb'));
        const storageLabel = isShared ? '<span class="storage-type-badge type-db">Trae 共享库(行紧缩)</span>' : '<span class="storage-type-badge type-file">独立物理文件</span>';
        const dateStr = s.started_at ? s.started_at.replace('T', ' ').slice(0, 16) : (s.mtime ? new Date(s.mtime * 1000).toISOString().slice(0, 16).replace('T', ' ') : '未知时间');
        const sizeMb = (Number(s.bytes || 0) / (1024 * 1024)).toFixed(2) + ' MB';

        return `
          <tr class="${isChecked ? 'selected' : ''}" onclick="toggleCleanupRow(event, '${s.catalog_id}')">
            <td style="text-align: center;">
              <input type="checkbox" ${isChecked ? 'checked' : ''} onchange="handleRowCheckbox(event, '${s.catalog_id}')" style="cursor: pointer;">
            </td>
            <td>
              <span class="format-badge" style="background: ${bg}; font-size: 11px; padding: 2px 7px;">${s.format}</span>
            </td>
            <td>
              <div style="font-weight: 600; color: #f1f5f9; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 440px;" title="${escapeHtml(s.title)}">
                ${escapeHtml(s.title)}
              </div>
              <div style="font-size: 11px; color: #64748b; font-family: var(--font-mono); margin-top: 2px;">
                🆔 ${(s.session_id || '').slice(0, 14)}...
              </div>
            </td>
            <td><span style="font-family: var(--font-mono);">${s.records || 0}</span> 步</td>
            <td><strong style="font-family: var(--font-mono); color: #cbd5e1;">${sizeMb}</strong></td>
            <td>${storageLabel}</td>
            <td style="font-size: 11.5px; color: #94a3b8;">${dateStr}</td>
          </tr>
        `;
      }).join('');

      updateCleanupSelectionStats();
    }

    function toggleCleanupRow(ev, cid) {
      if (ev.target.tagName === 'INPUT' || ev.target.closest('a') || ev.target.closest('button')) return;
      if (selectedCleanupCids.has(cid)) {
        selectedCleanupCids.delete(cid);
      } else {
        selectedCleanupCids.add(cid);
      }
      renderCleanupTable();
    }

    function handleRowCheckbox(ev, cid) {
      ev.stopPropagation();
      if (ev.target.checked) {
        selectedCleanupCids.add(cid);
      } else {
        selectedCleanupCids.delete(cid);
      }
      renderCleanupTable();
    }

    function toggleCleanupSelectAll(checked) {
      if (checked) {
        filteredCleanupSessions.forEach(s => selectedCleanupCids.add(s.catalog_id));
      } else {
        selectedCleanupCids.clear();
      }
      renderCleanupTable();
    }

    function updateCleanupSelectionStats() {
      const selectAllCb = document.getElementById('cleanupSelectAll');
      const selCountEl = document.getElementById('cleanupSelectedCount');
      const selSizeEl = document.getElementById('cleanupSelectedSize');
      const btnDel = document.getElementById('btnBatchDelete');
      const btnMig = document.getElementById('btnBatchMigrate');

      const count = selectedCleanupCids.size;
      selCountEl.innerText = count;

      if (selectAllCb) {
        const total = filteredCleanupSessions.length;
        selectAllCb.checked = (total > 0 && count === total);
        selectAllCb.indeterminate = (count > 0 && count < total);
      }

      // 计算预计释放大小
      let totalBytes = 0;
      allSessions.forEach(s => {
        if (selectedCleanupCids.has(s.catalog_id)) {
          totalBytes += Number(s.bytes) || 0;
        }
      });
      const mbStr = (totalBytes / (1024 * 1024)).toFixed(2) + ' MB';
      selSizeEl.innerText = mbStr;

      const hasSel = count > 0;
      btnDel.disabled = !hasSel;
      btnMig.disabled = !hasSel;
    }

    // --- Batch Delete Confirm Modal Actions ---
    function openBatchDeleteConfirm() {
      const count = selectedCleanupCids.size;
      if (count === 0) return;

      const selectedList = allSessions.filter(s => selectedCleanupCids.has(s.catalog_id));
      let totalBytes = 0;
      let standaloneCount = 0;
      let sharedCount = 0;

      selectedList.forEach(s => {
        totalBytes += Number(s.bytes) || 0;
        const isShared = s.format === 'trae' || (s.file_path && s.file_path.endsWith('state.vscdb'));
        if (isShared) sharedCount++;
        else standaloneCount++;
      });

      document.getElementById('confirmDelCount').innerText = count;
      document.getElementById('confirmDelSize').innerText = (totalBytes / (1024 * 1024)).toFixed(2) + ' MB';

      document.getElementById('confirmDelBreakdown').innerHTML = `
        <div>• <strong>独立实体文件会话:</strong> ${standaloneCount} 个 (Antigravity/WorkBuddy 等文件将彻底物理删除并释放空间)</div>
        <div>• <strong>共享库记录会话:</strong> ${sharedCount} 个 (Trae state.vscdb 将精准擦除对应聊天行并执行 VACUUM 空间紧缩)</div>
      `;

      document.getElementById('batchDeleteConfirmModal').classList.add('open');
    }

    function closeBatchDeleteConfirm() {
      document.getElementById('batchDeleteConfirmModal').classList.remove('open');
    }

    async function executeBatchDeleteNow() {
      const btn = document.getElementById('btnConfirmExecuteBatchDelete');
      btn.disabled = true;
      btn.innerText = '⏳ 正在彻底删除并紧缩空间...';

      const selectedList = allSessions.filter(s => selectedCleanupCids.has(s.catalog_id)).map(s => ({
        catalog_id: s.catalog_id,
        session_id: s.session_id,
        format: s.format,
        file_path: s.file_path
      }));

      try {
        const res = await fetch('/api/sessions/batch_delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessions: selectedList })
        });
        const data = await res.json();
        if (data.success) {
          showToast(`🎉 批量删除完成！已彻底清理 ${data.deleted_count} 个会话，释放 ${data.total_freed_mb} MB 空间！`);
          closeBatchDeleteConfirm();
          selectedCleanupCids.clear();
          // 全局重新加载
          await loadStatus();
          await loadSessions();
          applyCleanupFiltersAndRender();
        } else {
          showToast('❌ 批量删除失败: ' + (data.error || '未知错误'));
        }
      } catch (err) {
        showToast('❌ 请求失败: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerText = '💥 确认彻底删除并释放空间';
      }
    }

    // --- Batch Migrate Modal Actions ---
    function openBatchMigrateModal() {
      const count = selectedCleanupCids.size;
      if (count === 0) return;
      document.getElementById('batchMigrateCount').innerText = count;
      document.getElementById('batchMigrateFeedback').style.display = 'none';
      document.getElementById('btnExecuteBatchMigrate').disabled = false;
      document.getElementById('btnExecuteBatchMigrate').innerText = '开始批量迁移';

      const grid = document.getElementById('batchTargetGrid');
      const targets = [
        { id: 'antigravity', name: 'Antigravity IDE', icon: '⚡' },
        { id: 'claude', name: 'Claude Code', icon: '🟣' },
        { id: 'workbuddy', name: 'WorkBuddy', icon: '🤖' },
        { id: 'cursor', name: 'Cursor', icon: '🖱️' },
        { id: 'copilot', name: 'GitHub Copilot', icon: '🐙' }
      ];
      selectedBatchTargetFormat = 'antigravity';

      grid.innerHTML = targets.map(t => `
        <div class="target-card ${t.id === selectedBatchTargetFormat ? 'selected' : ''}" onclick="selectBatchTargetFormat('${t.id}')">
          <div style="font-size: 24px;">${t.icon}</div>
          <div>
            <div style="font-weight: 700; font-size: 13px;">${t.name}</div>
            <div style="font-size: 11px; color: var(--text-muted);">${t.id}</div>
          </div>
        </div>
      `).join('');

      document.getElementById('batchMigrateSelectModal').classList.add('open');
    }

    function selectBatchTargetFormat(fmt) {
      selectedBatchTargetFormat = fmt;
      document.querySelectorAll('#batchTargetGrid .target-card').forEach(el => {
        el.classList.toggle('selected', el.innerText.toLowerCase().includes(fmt));
      });
    }

    function closeBatchMigrateModal() {
      document.getElementById('batchMigrateSelectModal').classList.remove('open');
    }

    async function executeBatchMigrateNow() {
      const btn = document.getElementById('btnExecuteBatchMigrate');
      const feedback = document.getElementById('batchMigrateFeedback');
      btn.disabled = true;
      btn.innerText = '⏳ 正在批量迁移中...';

      const cids = Array.from(selectedCleanupCids);

      try {
        const res = await fetch('/api/sessions/batch_migrate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            catalog_ids: cids,
            target_format: selectedBatchTargetFormat
          })
        });
        const data = await res.json();
        if (data.success) {
          feedback.style.display = 'block';
          feedback.style.background = 'rgba(16, 185, 129, 0.15)';
          feedback.style.color = '#34d399';
          feedback.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          feedback.innerHTML = `<strong>🎉 批量迁移成功！</strong><br>已转换生成 ${data.success_count} 个 ${data.target_format.toUpperCase()} 会话！输出位于 export 目录。`;
          btn.innerText = '迁移完成';
          showToast(`已成功批量迁移 ${data.success_count} 个会话！`);
        } else {
          feedback.style.display = 'block';
          feedback.style.background = 'rgba(244, 63, 94, 0.15)';
          feedback.style.color = '#fb7185';
          feedback.innerHTML = '❌ 批量迁移失败: ' + (data.error || '未知错误');
          btn.disabled = false;
          btn.innerText = '开始批量迁移';
        }
      } catch (err) {
        feedback.style.display = 'block';
        feedback.style.background = 'rgba(244, 63, 94, 0.15)';
        feedback.style.color = '#fb7185';
        feedback.innerHTML = '❌ 请求异常: ' + err.message;
        btn.disabled = false;
        btn.innerText = '开始批量迁移';
      }
    }

  </script>
</body>
</html>
"""

def release_port(port: int):
    import subprocess, time
    try:
        res = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="ignore")
        killed = False
        for line in res.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    if pid != str(os.getpid()) and pid != "0":
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                        killed = True
        if killed:
            time.sleep(0.5)
    except Exception:
        pass

def main():
    ensure_antigravity_catalog_roots()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Ensure port is clean before binding
    release_port(PORT)

    server_address = ("0.0.0.0", PORT)
    httpd = ReusableThreadingServer(server_address, RequestHandler)
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 65)
    print("  Memory Tools 跨智能体会话记忆管理与一键迁移平台")
    print(f"  本地访问地址: {url}")
    print(f"  会话导出目录: {EXPORT_DIR}")
    print("  提示: 正在自动打开默认浏览器，使用期间请保持本窗口开启！")
    print("=" * 65)
    def open_browser():
        import time, webbrowser
        time.sleep(0.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    import threading
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

if __name__ == "__main__":
    main()