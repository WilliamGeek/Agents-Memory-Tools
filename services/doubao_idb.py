"""豆包聊天明文 IndexedDB（Chromium LevelDB）解析服务。

为什么单独一层
--------------
1. 豆包当前聊天内容写在 ``User Data\\<profile>\\IndexedDB\\chrome_doubao-chat_0.indexeddb.leveldb``，
   不在加密的 ``sdk_storage\\im.db`` 里（实测见 handoff §7.7）；
2. LevelDB + 自定义序列化 + Snappy 的解析较重，必须按文件签名缓存，才能在
   聊天过程中"热更新"而不是每次请求都全量重扫；
3. web_app 只消费本模块返回的结构化结果，不直接碰二进制细节。

数据格式
--------
``[varint 字段名长度][字段名][类型字节][值]``，类型：
``0x22`` UTF-8、``0x63`` UTF-16LE、``0x49`` 整数、``0x4e`` 8 字节 double、
``0x41`` 数组、``0x6f`` 对象、``0x46/0x54`` 布尔、``0x5f`` null。

角色判定
--------
``mainTaskDataMap`` 保存的是"当前任务态"：第一个文本块是用户请求，其余文本块
属于助手本轮回复。因此用「首条=user、其余合并=assistant」的稳定启发式，
避免任务态里重复的 ``message_from`` 造成角色错配。
"""
from __future__ import annotations

import re
import struct
import threading
from pathlib import Path
from typing import Any

LEVELDB_GLOB = "*/IndexedDB/chrome_doubao-chat_0.indexeddb.leveldb"


def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
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


def snappy_decompress(data: bytes) -> bytes:
    """纯 Python Snappy 解压（Chromium LevelDB 数据块）。"""
    pos = 0
    n = len(data)
    ulen, pos = read_varint(data, pos)
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


def leveldb_dirs(user_data_root: Path) -> list[Path]:
    """返回所有 profile 下的豆包聊天 LevelDB 目录。"""
    if not user_data_root.exists():
        return []
    return sorted(p for p in user_data_root.glob(LEVELDB_GLOB) if p.is_dir())


def _iter_values(idb_dir: Path) -> list[bytes]:
    """读取 .ldb + .log 并尝试 Snappy 解压值。"""
    blobs: list[bytes] = []
    if not idb_dir.exists():
        return blobs

    def _try_dec(val: bytes) -> bytes:
        for off in range(min(12, len(val))):
            try:
                return snappy_decompress(val[off:])
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
            _, p = read_varint(footer, p)
            _, p = read_varint(footer, p)
            idx_off, p = read_varint(footer, p)
            idx_size, p = read_varint(footer, p)

            def _read_blk(off: int, size: int) -> bytes:
                blk = raw[off:off + size]
                return snappy_decompress(blk) if raw[off + size] == 1 else blk

            def _iter_kv(blk: bytes):
                num_restarts = struct.unpack_from("<I", blk, len(blk) - 4)[0]
                data_end = len(blk) - 4 - num_restarts * 4
                q = 0
                while q < data_end:
                    _, q = read_varint(blk, q)
                    un, q = read_varint(blk, q)
                    vl, q = read_varint(blk, q)
                    q += un
                    yield blk[q:q + vl]
                    q += vl

            idx_blk = _read_blk(idx_off, idx_size)
            for h in _iter_kv(idx_blk):
                hp = 0
                boff, hp = read_varint(h, hp)
                bsize, hp = read_varint(h, hp)
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
                _, length, rtype = struct.unpack_from("<IHB", raw, pos)
                pos += 7
                if pos + length > len(raw) or rtype == 0:
                    break
                chunk = raw[pos:pos + length]
                pos += length
                if rtype == 1:
                    recs.append(chunk)
                elif rtype == 2:
                    buf = bytearray(chunk)
                elif rtype in (3, 4):
                    buf.extend(chunk)
                    if rtype == 4:
                        recs.append(bytes(buf))
                        buf = bytearray()
            for rec in recs:
                if len(rec) < 12:
                    continue
                p = 12
                while p < len(rec):
                    vt = rec[p]
                    p += 1
                    kl, p = read_varint(rec, p)
                    p += kl
                    if vt == 1:
                        vl, p = read_varint(rec, p)
                        blobs.append(_try_dec(rec[p:p + vl]))
                        p += vl
        except Exception:
            continue
    return blobs


_CONV_RE = re.compile(rb'\x0fconversation_id".([0-9]{10,25})', re.S)
_TEXT_RE = re.compile(rb"\x04text([\x22\x63])")


def _decode_text(buf: bytes, pos: int, tag: int) -> str:
    ln, q = read_varint(buf, pos)
    if ln <= 0 or ln > 65536 or q + ln > len(buf):
        return ""
    raw = buf[q:q + ln]
    return raw.decode("utf-16-le" if tag == 0x63 else "utf-8", errors="ignore").strip()


def _parse_conversations(values: list[bytes]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    conv_blobs = [b for b in values if b"conversation-list-data" in b]
    if not conv_blobs:
        return out
    blob = max(conv_blobs, key=len)
    for m in _CONV_RE.finditer(blob):
        cid = m.group(1).decode("ascii", "ignore")
        window = blob[m.end():m.end() + 2400]
        title = ""
        nm = re.search(rb"\x04name\x00?", window)
        if nm:
            pos = nm.end()
            tag = window[pos] if pos < len(window) else 0
            if tag in (0x63, 0x22):
                ln, q = read_varint(window, pos + 1)
                if 1 <= ln <= 400 and q + ln <= len(window):
                    enc = "utf-16-le" if tag == 0x63 else "utf-8"
                    title = window[q:q + ln].decode(enc, errors="ignore").strip()
        ts = 0
        tm = re.search(rb'update_time".([0-9]{10,13})', window) or re.search(
            rb'create_time".([0-9]{10,13})', window
        )
        if tm:
            ts = int(tm.group(1))
            if ts > 10**12:
                ts //= 1000
        cur = out.get(cid)
        if cur is None:
            out[cid] = {"cid": cid, "title": title, "ts": ts}
        elif title and not cur["title"]:
            cur["title"] = title
            cur["ts"] = cur["ts"] or ts
    return out


def _parse_tasks(values: list[bytes]) -> dict[str, list[dict[str, str]]]:
    """从 mainTaskDataMap 提取事件：文本块 + 文件操作，首条文本为用户指令。"""
    out: dict[str, list[dict[str, str]]] = {}
    for blob in values:
        if b"mainTaskDataMap" not in blob:
            continue
        m = _CONV_RE.search(blob)
        if not m:
            continue
        cid = m.group(1).decode("ascii", "ignore")
        raw_events: list[tuple[int, dict[str, str]]] = []
        for tm in _TEXT_RE.finditer(blob):
            s = _decode_text(blob, tm.end(), tm.group(1)[0])
            if not s or len(s) > 8000:
                continue
            raw_events.append((tm.start(), {"kind": "message", "role": "", "text": s}))
        # 文件类动作：file_operation_block -> file_name
        for fm in re.finditer(rb"\x14file_operation_block", blob):
            seg = blob[fm.end():fm.end() + 600]
            nm = re.search(rb"\x09file_name([\x63\x22])", seg)
            if not nm:
                continue
            ln, q = read_varint(seg, nm.end())
            if not (1 <= ln <= 1000 and q + ln <= len(seg)):
                continue
            enc = "utf-16-le" if nm.group(1)[0] == 0x63 else "utf-8"
            path = seg[q:q + ln].decode(enc, errors="ignore").strip()
            if path:
                raw_events.append((fm.start(), {
                    "kind": "tool_call",
                    "role": "assistant",
                    "tool_name": "文件操作",
                    "text": path,
                }))
        raw_events.sort(key=lambda x: x[0])
        seen: set[tuple[str, str]] = set()
        items: list[dict[str, str]] = []
        user_set = False
        for _, item in raw_events:
            key = (item["kind"], item["text"])
            if key in seen:
                continue
            seen.add(key)
            if item["kind"] == "message":
                if not user_set:
                    item["role"] = "user"
                    user_set = True
                else:
                    item["role"] = "assistant"
            items.append(item)
        if items and len(items) > len(out.get(cid, [])):
            out[cid] = items
    return out


_lock = threading.Lock()
_cache: dict[str, Any] = {"sig": None, "data": {}}


def _signature(root: Path, dirs: list[Path]) -> tuple:
    items = []
    for d in dirs:
        for f in sorted(d.glob("*")):
            try:
                st = f.stat()
            except OSError:
                continue
            items.append((str(f), st.st_mtime_ns, st.st_size))
    return (str(root), tuple(items))


def load(user_data_root: Path) -> dict[str, dict[str, Any]]:
    """加载全部会话（带签名缓存，文件变化即热更新）。"""
    dirs = leveldb_dirs(user_data_root)
    sig = _signature(user_data_root, dirs)
    with _lock:
        if _cache["sig"] == sig:
            return _cache["data"]

    values: list[bytes] = []
    conv: dict[str, dict[str, Any]] = {}
    tasks: dict[str, list[str]] = {}
    for d in dirs:
        vals = _iter_values(d)
        values.extend(vals)
        for cid, meta in _parse_conversations(vals).items():
            cur = conv.get(cid)
            if cur is None:
                conv[cid] = meta
            else:
                if meta.get("title") and not cur.get("title"):
                    cur["title"] = meta["title"]
                if not cur.get("ts") and meta.get("ts"):
                    cur["ts"] = meta["ts"]
        for cid, texts in _parse_tasks(vals).items():
            if len(texts) > len(tasks.get(cid, [])):
                tasks[cid] = texts
    data: dict[str, dict[str, Any]] = {}
    for cid, meta in conv.items():
        data[cid] = {**meta, "messages": tasks.get(cid) or [], "dir": str(dirs[0]) if dirs else ""}
    for cid, items in tasks.items():
        if cid in data:
            continue
        data[cid] = {
            "cid": cid,
            "title": "",
            "ts": 0,
            "messages": items,
            "dir": str(dirs[0]) if dirs else "",
        }
    with _lock:
        _cache["sig"] = sig
        _cache["data"] = data
    return data
