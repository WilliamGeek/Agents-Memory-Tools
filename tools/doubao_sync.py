"""豆包（Doubao）云端会话同步工具。

背景
----
豆包桌面端的完整聊天记录不在本地 IndexedDB 里（那里只有会话元数据和最近任务态），
正文在云端。本工具用**本机已登录的 Chromium Cookie** 调用豆包自身的只读接口：

1. ``POST /samantha/im/conversation/list``  会话列表（分页）
2. ``POST /alice/message/index_list``        按消息序号批量取正文（单次上限 40）

Cookie 来自 ``User Data\\<profile>\\Network\\Cookies``（v10：DPAPI + AES-256-GCM，
明文前 32 字节是 Chromium 的 host_key 指纹）。文件被浏览器独占锁定时，会退化为
卷影副本（VSS）只读复制，并在用完后立即删除快照。

产物
----
``cache/doubao_cloud/conversations/<cid>.json``  每个会话一个规范化文件
``cache/doubao_cloud/manifest.json``             增量同步清单

命令行
------
``python tools/doubao_sync.py``            增量同步
``python tools/doubao_sync.py --full``     全量重拉
``python tools/doubao_sync.py --only CID`` 只同步一个会话
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - 运行环境缺依赖时给出明确错误
    AESGCM = None

PROJ = Path(__file__).resolve().parent.parent
if str(PROJ) not in sys.path:
    sys.path.insert(0, str(PROJ))
import runtime_paths

CACHE_DIR = runtime_paths.CACHE_DIR / "doubao_cloud"
CONV_DIR = CACHE_DIR / "conversations"
COOKIE_FILE = CACHE_DIR / ".cookies.json"
MANIFEST_FILE = CACHE_DIR / "manifest.json"

LOCAL_APPDATA = runtime_paths.local_app_data_dir()
DOUBAO_DATA = LOCAL_APPDATA / "Doubao" / "User Data"

BASE = "https://www.doubao.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Doubao/2.36.8 Chrome/147.0.7727.149 Safari/537.36"
)
COMMON_PARAMS = {
    "aid": "582478",
    "real_aid": "582478",
    "device_platform": "web",
    "doubao_device_platform": "desktop",
    "pkg_type": "release_version",
    "version_code": "20800",
    "update_version_code": "20800",
    "pc_version": "2.36.8",
    "language": "zh",
    "region": "CN",
    "device_id": "1141719210406352",
    "web_platform": "browser",
    "samantha_web": "1",
    "use-olympus-account": "1",
}
COOKIE_TTL = 6 * 3600
MAX_BATCH = 40
MANIFEST_LOCK = threading.Lock()


# --------------------------------------------------------------------------- #
# Chromium Cookie 解密
# --------------------------------------------------------------------------- #
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi_unprotect(data: bytes) -> bytes:
    blob_in = _DATA_BLOB(len(data), (ctypes.c_ubyte * len(data)).from_buffer_copy(data))
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _master_key(local_state: Path) -> bytes:
    state = json.loads(local_state.read_text(encoding="utf-8"))
    enc = base64.b64decode(state["os_crypt"]["encrypted_key"])
    if enc[:5] != b"DPAPI":
        raise ValueError("unsupported os_crypt key")
    return _dpapi_unprotect(enc[5:])


def _decrypt_v10(key: bytes, blob: bytes) -> str:
    if blob[:3] != b"v10":
        raise ValueError(f"unsupported cookie prefix {blob[:3]!r}")
    plain = AESGCM(key).decrypt(blob[3:15], blob[15:], None)
    # Chromium 127+ 在明文前加了 32 字节 host_key 指纹
    if len(plain) >= 32 and not plain[:32].isascii():
        plain = plain[32:]
    return plain.decode("utf-8", errors="ignore")


def _shared_copy(files: list[Path], dest_dir: Path) -> dict[str, Path]:
    """用带 FILE_SHARE_* 的 Win32 句柄复制被浏览器占用的文件。

    Chromium 打开 Cookies SQLite 时通常允许读写共享，但 Python 的
    open() 会以更严格的共享模式失败；VSS 在非管理员/服务未启动时也不可用。
    这里用 CreateFileW(GENERIC_READ, FILE_SHARE_READ|WRITE|DELETE) 直接读。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.ReadFile.restype = ctypes.c_int
    generic_read = 0x80000000
    share = 0x1 | 0x2 | 0x4
    open_existing = 3
    normal = 0x80
    pairs: dict[str, Path] = {}
    for idx, src in enumerate(files):
        out = dest_dir / f"{idx}_{src.name}"
        handle = k32.CreateFileW(
            str(src), generic_read, share, None, open_existing, normal, None
        )
        invalid = ctypes.c_void_p(-1).value
        if not handle or handle == invalid:
            # 某个 profile 的 Cookie 库可能被以不共享方式占用；跳过它，
            # 只从可读的 profile 里取 Cookie，避免整体退回 VSS。
            continue
        try:
            with open(out, "wb") as fh:
                buf = ctypes.create_string_buffer(1 << 20)
                while True:
                    read = ctypes.c_ulong(0)
                    if not k32.ReadFile(handle, buf, len(buf), ctypes.byref(read), None):
                        raise OSError(f"ReadFile failed for {src}")
                    if read.value == 0:
                        break
                    fh.write(buf.raw[: read.value])
        finally:
            k32.CloseHandle(handle)
        pairs[str(src)] = out
    if not pairs:
        raise OSError("共享句柄复制没有可读文件")
    return pairs


def _vss_copy(files: list[Path], dest_dir: Path) -> dict[str, Path]:
    """用卷影副本只读复制被独占锁定的文件，完成后删除快照。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    pairs = []
    for idx, src in enumerate(files):
        rel = str(src).split(":\\", 1)[1]
        out = dest_dir / f"{idx}_{src.name}"
        pairs.append((str(src), rel, out))
    ps = [
        "$ErrorActionPreference='Stop'",
        "$c=[wmiclass]'root\\cimv2:Win32_ShadowCopy'",
        "$r=$c.Create('C:\\','ClientAccessible')",
        "if($r.ReturnValue -ne 0){exit 2}",
        "$id=$r.ShadowID",
        "$dev=(Get-CimInstance Win32_ShadowCopy | Where-Object {$_.ID -eq $id}).DeviceObject",
        "try{",
    ]
    for _, rel, out in pairs:
        ps.append(
            "Copy-Item -LiteralPath (Join-Path $dev '%s') -Destination '%s' -Force"
            % (rel.replace("'", "''"), str(out).replace("'", "''"))
        )
    ps += [
        "}finally{",
        "Get-CimInstance Win32_ShadowCopy | Where-Object {$_.ID -eq $id} | Remove-CimInstance -ErrorAction SilentlyContinue",
        "}",
    ]
    script = "\n".join(ps)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=180,
    )
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="ignore")[-800:]
        raise RuntimeError(f"VSS copy failed ({proc.returncode}): {msg}")
    return {src_key: out for src_key, _, out in pairs}


def _readable_files(paths: list[Path]) -> tuple[dict[str, Path], Path | None]:
    """优先直接读；失败则共享句柄复制，最后才用 VSS。"""
    direct: dict[str, Path] = {}
    for p in paths:
        try:
            with open(p, "rb"):
                pass
            direct[str(p)] = p
        except Exception:
            pass
    if len(direct) == len(paths):
        return direct, None
    tmp = CACHE_DIR / "_shared"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        return _shared_copy(paths, tmp), tmp
    except Exception:
        pass
    tmp = CACHE_DIR / "_vss"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    return _vss_copy(paths, tmp), tmp


def collect_cookies() -> dict[str, str]:
    if AESGCM is None:
        raise RuntimeError("cryptography 未安装，无法解密 Chromium Cookie")
    db_files = sorted(DOUBAO_DATA.glob("*/Network/Cookies"))
    state_file = DOUBAO_DATA / "Local State"
    if not db_files or not state_file.exists():
        raise RuntimeError("未找到豆包 Cookie 库或 Local State")
    readable, cleanup = _readable_files([state_file] + db_files)
    try:
        key = _master_key(readable[str(state_file)])
        cookies: dict[str, str] = {}
        for db in db_files:
            path = readable.get(str(db))
            if path is None:
                continue
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                rows = conn.execute(
                    "select host_key,name,encrypted_value from cookies "
                    "where host_key like '%doubao%' and encrypted_value != x''"
                ).fetchall()
                conn.close()
            except Exception:
                continue
            for host, name, blob in rows:
                try:
                    cookies[name] = _decrypt_v10(key, bytes(blob))
                except Exception:
                    continue
        if not cookies:
            raise RuntimeError("豆包 Cookie 解密结果为空")
        return cookies
    finally:
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)


def load_cookies(force: bool = False) -> dict[str, str]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached: dict[str, Any] | None = None
    if COOKIE_FILE.exists():
        try:
            cached = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cached = None
    if not force and cached:
        age = time.time() - float(cached.get("fetched_at") or 0)
        if age < COOKIE_TTL and cached.get("cookies"):
            return dict(cached["cookies"])
    try:
        cookies = collect_cookies()
    except Exception:
        if cached and cached.get("cookies"):
            return dict(cached["cookies"])
        raise
    COOKIE_FILE.write_text(
        json.dumps({"fetched_at": time.time(), "cookies": cookies}, ensure_ascii=False),
        encoding="utf-8",
    )
    return cookies


# --------------------------------------------------------------------------- #
# API 客户端
# --------------------------------------------------------------------------- #
class ApiError(RuntimeError):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code


class DoubaoClient:
    def __init__(self, cookies: dict[str, str]):
        self.s = requests.Session()
        self.s.cookies.update(cookies)
        self.s.headers.update({
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE,
            "Referer": f"{BASE}/chat/",
        })

    def _post(self, path: str, params: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = self.s.post(
                    BASE + path,
                    params={**COMMON_PARAMS, **params},
                    json=payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    timeout=60,
                )
                data = r.json()
                code = int(data.get("code") or 0)
                if code == 0 and r.status_code == 200:
                    return data
                err = ApiError(f"{path} code={code} msg={data.get('msg')}", code)
                # 只有「批量过大」值得重试/拆分；索引不存在等业务错误直接失败
                if code != 710010202:
                    raise err
                last = err
            except ApiError:
                raise
            except Exception as exc:
                last = exc
            time.sleep(0.6 * (attempt + 1))
        raise last or ApiError(f"{path} failed")

    def list_conversations(self, page_size: int = 20, limit: int = 0) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = ""
        while True:
            data = self._post(
                "/samantha/im/conversation/list",
                {"conversation_types": "3", "cursor": cursor, "batch_size": str(page_size)},
                {},
            )
            body = data.get("data") or {}
            for item in body.get("thread_list") or []:
                conv = item.get("conversation") or {}
                if conv.get("conversation_id"):
                    out.append(conv)
            if limit and len(out) >= limit:
                return out[:limit]
            if not body.get("has_more") or not body.get("next_cursor"):
                return out
            cursor = str(body["next_cursor"])
            time.sleep(0.1)

    def fetch_messages(self, cid: str, start: int, end: int) -> list[dict[str, Any]]:
        indices = list(range(max(1, start), end + 1))
        result: list[dict[str, Any]] = []
        for i in range(0, len(indices), MAX_BATCH):
            chunk = indices[i:i + MAX_BATCH]
            result.extend(self._fetch_chunk(cid, chunk))
            time.sleep(0.05)
        return result

    def fetch_latest_messages(self, cid: str) -> list[dict[str, Any]]:
        """补拉最新消息。

        `index_list` 对部分历史会话会缺最后一个 index（常见于旧会话或被
        截断的会话），但 `latest_messagelist` 仍能返回该条。只把缺失 index
        合并进主结果，不覆盖已取得的正文。
        """
        data = self._post(
            "/alice/conversation/latest_messagelist",
            {},
            {"request_list": [{"conversation_id": str(cid)}]},
        )
        body = data.get("data") or {}
        message_map = body.get("message_map") or {}
        rows = message_map.get(str(cid)) or []
        return rows if isinstance(rows, list) else []

    def _fetch_chunk(self, cid: str, indices: list[int]) -> list[dict[str, Any]]:
        try:
            data = self._post(
                "/alice/message/index_list",
                {},
                {"conversation_id": cid, "message_index_list": indices, "is_reverse": True},
            )
            return (data.get("data") or {}).get("message_list") or []
        except ApiError as exc:
            # 登录失效/参数错误属于永久失败，拆分无意义；索引缺失(710010702)才继续拆分
            if exc.code in (710012000, 671010000, 710020702):
                raise
            if len(indices) <= 1:
                return []
            mid = len(indices) // 2
            return self._fetch_chunk(cid, indices[:mid]) + self._fetch_chunk(cid, indices[mid:])
        except Exception:
            if len(indices) <= 1:
                return []
            mid = len(indices) // 2
            return self._fetch_chunk(cid, indices[:mid]) + self._fetch_chunk(cid, indices[mid:])


# --------------------------------------------------------------------------- #
# 规范化
# --------------------------------------------------------------------------- #
_ROLE = {1: "user", 2: "assistant", 3: "system"}


def _json_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _clip(text: Any, limit: int = 20000) -> str:
    s = str(text or "").strip()
    return s[:limit]


def _events_from_blocks(blocks: list[Any], role: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        try:
            bt = int(block.get("block_type") or 0)
        except Exception:
            bt = 0
        data = _json_maybe(block.get("content"))
        header = data.get("header") if isinstance(data, dict) else None
        header = header if isinstance(header, dict) else {}

        if bt == 10000:
            text = _clip(data.get("text")) if isinstance(data, dict) else _clip(data)
            if text:
                out.append({"kind": "message", "role": role, "text": text})
        elif bt in (10040, 10091):
            continue
        elif bt == 10011:
            # 豆包「深入研究」报告块：content 里只有 brief 摘要，完整 HTML
            # 在 resource_id 指向的资源中；brief 本身也是正文，不能丢。
            if isinstance(data, dict):
                body = _clip(data.get("brief") or data.get("text"), 200000)
                title = _clip(data.get("title") or "深入研究", 120)
                if body:
                    out.append({
                        "kind": "message",
                        "role": role,
                        "tool_name": title,
                        "text": body,
                    })
        elif bt == 10013:
            # 研究结果的网页入口，保留资源标识，便于后续补全文。
            if isinstance(data, dict):
                title = _clip(data.get("title") or "研究资源", 120)
                resource = _clip(data.get("resource_id") or "", 2000)
                if resource:
                    out.append({
                        "kind": "tool_call",
                        "role": role,
                        "tool_name": title,
                        "text": resource,
                    })
        elif bt == 10019:
            path = ""
            if isinstance(data, dict):
                path = _clip(data.get("path") or data.get("file_name"), 2000)
            op = _clip(header.get("summary") or "文件操作", 120)
            if path:
                out.append({"kind": "tool_call", "role": role, "tool_name": op, "text": path})
        elif bt == 10024:
            if isinstance(data, dict):
                tool = _clip(data.get("tool_name") or "工具", 120)
                text = _clip(data.get("summary") or data.get("title"), 2000)
                if text:
                    out.append({"kind": "tool_call", "role": role, "tool_name": tool, "text": text})
        elif bt == 10083:
            if isinstance(data, dict):
                code = _clip(data.get("content"), 4000)
                summary = _clip(header.get("summary") or "代码执行", 120)
                if code:
                    out.append({"kind": "tool_call", "role": role, "tool_name": summary, "text": code})
        elif bt == 10063:
            if isinstance(data, dict):
                text = _clip(data.get("path") or data.get("name"), 2000)
                if text:
                    out.append({"kind": "tool_call", "role": role, "tool_name": "附件", "text": text})
        else:
            if isinstance(data, dict):
                text = data.get("text") or data.get("content") or data.get("result")
                if text:
                    tool = _clip(data.get("tool_name") or header.get("summary") or f"块{bt}", 120)
                    out.append({
                        "kind": "tool_call",
                        "role": role,
                        "tool_name": tool,
                        "text": _clip(text, 4000),
                    })
    return out


def _events_from_message(msg: dict[str, Any]) -> list[dict[str, str]]:
    role = _ROLE.get(int(msg.get("user_type") or 0), "assistant")
    ctype = int(msg.get("content_type") or 0)
    content = msg.get("content")
    if content in (None, ""):
        content = msg.get("content_block")
    if isinstance(content, list):
        return _events_from_blocks(content, role)
    data = _json_maybe(content)

    if ctype == 1 and isinstance(data, str):
        text = _clip(data)
        return [{"kind": "message", "role": role, "text": text}] if text else []
    if ctype == 9999 and isinstance(data, list):
        return _events_from_blocks(data, role)
    if ctype == 20 and isinstance(data, dict):
        text = _clip(data.get("text"))
        return [{"kind": "message", "role": role, "text": text}] if text else []
    if isinstance(data, str):
        text = _clip(data)
        return [{"kind": "message", "role": role, "text": text}] if text else []
    if isinstance(data, dict):
        text = data.get("text") or data.get("content") or data.get("title")
        if isinstance(text, (dict, list)):
            text = json.dumps(text, ensure_ascii=False)
        text = _clip(text)
        return [{"kind": "message", "role": role, "text": text}] if text else []
    return []


def normalize_conversation(conv: dict[str, Any], raw_msgs: list[dict[str, Any]]) -> dict[str, Any]:
    cid = str(conv.get("conversation_id") or "")
    fallback_ts = int(conv.get("update_time") or 0)
    events: list[dict[str, Any]] = []
    last_text = ""
    for msg in sorted(raw_msgs, key=lambda m: int(m.get("index") or 0)):
        ts = int(msg.get("create_time") or msg.get("update_time") or fallback_ts or 0)
        for ev in _events_from_message(msg):
            text = ev.get("text") or ""
            if not text or text == last_text:
                continue
            last_text = text
            events.append({**ev, "ts": ts})
    return {
        "cid": cid,
        "title": _clip(conv.get("name") or f"豆包对话 ({cid[-8:]})", 300),
        "ts": fallback_ts,
        "message_index": int(conv.get("message_index") or 0),
        "message_cursor": int(conv.get("message_cursor") or 1),
        "updated_at": int(time.time()),
        "messages": events,
    }


# --------------------------------------------------------------------------- #
# 同步
# --------------------------------------------------------------------------- #
def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_FILE.exists():
        return {"conversations": {}}
    try:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("conversations"), dict):
            return data
    except Exception:
        pass
    return {"conversations": {}}


def _save_manifest(manifest: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST_FILE)


def sync_all(full: bool = False, only: str = "", limit: int = 0,
             concurrency: int = 4, quiet: bool = False) -> dict[str, Any]:
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    cookies = load_cookies()
    client = DoubaoClient(cookies)
    convs = client.list_conversations(limit=limit)
    if only:
        convs = [c for c in convs if str(c.get("conversation_id")) == str(only)]
    manifest = {"conversations": {}} if full else _load_manifest()
    known = manifest.setdefault("conversations", {})

    stats = {"total": len(convs), "synced": 0, "skipped": 0, "failed": 0, "events": 0}
    lock = threading.Lock()

    def work(conv: dict[str, Any]) -> None:
        cid = str(conv.get("conversation_id") or "")
        if not cid:
            return
        mi = int(conv.get("message_index") or 0)
        mc = int(conv.get("message_cursor") or 1)
        prev = known.get(cid) or {}
        if not full and prev.get("message_index") == mi and int(prev.get("update_time") or 0) == int(conv.get("update_time") or 0):
            with lock:
                # 即使本轮 skipped，也要记录“刚检查过”，否则详情按需刷新会
                # 每 120 秒反复触发 --only，永远显示 refresh_pending。
                known[cid] = {**prev, "checked_at": int(time.time())}
                stats["skipped"] += 1
            return
        try:
            raw = client.fetch_messages(cid, mc, mi) if mi > 0 else []
            # 某些历史会话的最后一个 index 在 index_list 中缺失，但
            # latest_messagelist 仍保留；按 index 去重补齐，避免“只有用户
            # 提问、没有助手回复”的假空会话。
            if mi > 0 and len(raw) < mi:
                try:
                    latest = client.fetch_latest_messages(cid)
                    existing = {int(m.get("index") or 0) for m in raw}
                    for m in latest:
                        idx = int(m.get("index") or 0)
                        if idx not in existing:
                            raw.append(m)
                            existing.add(idx)
                    raw.sort(key=lambda m: int(m.get("index") or 0))
                except Exception as exc:
                    if not quiet:
                        print(f"  ! latest fallback {cid}: {exc}")
            norm = normalize_conversation(conv, raw)
            out = CONV_DIR / f"{cid}.json"
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(norm, ensure_ascii=False), encoding="utf-8")
            tmp.replace(out)
            with lock:
                known[cid] = {
                    "message_index": mi,
                    "message_cursor": mc,
                    "update_time": int(conv.get("update_time") or 0),
                    "title": norm["title"],
                    "ts": norm["ts"],
                    "events": len(norm["messages"]),
                    "synced_at": int(time.time()),
                }
                stats["synced"] += 1
                stats["events"] += len(norm["messages"])
            if not quiet:
                print(f"  [{stats['synced']}/{len(convs)}] {norm['title'][:40]} ({len(norm['messages'])} events)")
        except Exception as exc:
            with lock:
                stats["failed"] += 1
                known.setdefault(cid, {})["error"] = str(exc)[:200]
            if not quiet:
                print(f"  ! {cid}: {exc}")

    workers = max(1, min(concurrency, 8))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, c) for c in convs]
        for fut in as_completed(futures):
            fut.result()

    manifest["synced_at"] = int(time.time())
    manifest["stats"] = stats
    _save_manifest(manifest)
    return stats


def rebuild_manifest_from_files() -> int:
    """用已落盘的会话 JSON 重建清单（用于中断后续跑，避免全量重拉）。"""
    entries: dict[str, Any] = {}
    for p in CONV_DIR.glob("*.json"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        cid = str(obj.get("cid") or p.stem)
        entries[cid] = {
            "message_index": int(obj.get("message_index") or 0),
            "message_cursor": int(obj.get("message_cursor") or 1),
            "update_time": int(obj.get("ts") or 0),
            "title": obj.get("title") or "",
            "ts": int(obj.get("ts") or 0),
            "events": len(obj.get("messages") or []),
            "synced_at": int(obj.get("updated_at") or 0),
        }
    _save_manifest({"conversations": entries, "synced_at": int(time.time())})
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="豆包云端会话同步")
    parser.add_argument("--full", action="store_true", help="忽略清单，全量重拉")
    parser.add_argument("--only", default="", help="只同步指定 conversation_id")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 个会话")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--rebuild-manifest", action="store_true",
                        help="只根据已落盘 JSON 重建清单，不访问网络")
    args = parser.parse_args(argv)

    if args.rebuild_manifest:
        n = rebuild_manifest_from_files()
        print(f"manifest rebuilt: {n} conversations")
        return 0

    t0 = time.time()
    stats = sync_all(
        full=args.full, only=args.only, limit=args.limit,
        concurrency=args.concurrency, quiet=args.quiet,
    )
    print(
        "done: total={total} synced={synced} skipped={skipped} failed={failed} "
        "events={events} secs={secs:.1f}".format(**stats, secs=time.time() - t0)
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
