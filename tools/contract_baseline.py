#!/usr/bin/env python3
"""契约基线护栏（T01）。

用途
----
把「当前正在跑的 web_app.py 对 13 个接口的响应结构」固化成一份可比对的结构快照，
之后每次改后端都跑一次 `--check`：**旧字段一个不少、类型不降级**才算通过；
新增字段一律放行（否则每加一个字段都要改基线，护栏会失去意义）。

设计约束（与架构文档 §2.1 对齐）
--------------------------------
1. 只比较 **结构**（字段名 + 类型 + 嵌套形状），不比较具体值。
   这样数据变化（新增会话、mtime 变化）不会造成假失败。
2. `null` 视为「任意类型的可空版本」，因此 `payload: null` 对
   `payload: {..}` 不会误报（事件里 payload 时有时无）。
3. 深度上限 `MAX_DEPTH`，超过后只记录类型，不继续展开 —— 详情响应里的
   `payload` 是任意 JSON，无限展开既无意义也会让基线文件失去可读性。
4. 数组只采样前 `MAX_ARRAY_SAMPLE` 个元素并做「形状并集」，避免
   「第 5 条会话恰好没有 children 字段」这类采样抖动造成假失败。

用法
----
    python tools/contract_baseline.py --capture                       # 抓改造前基线
    python tools/contract_baseline.py --check                         # 改造后比对
    python tools/contract_baseline.py --check --base http://127.0.0.1:18923
    python tools/contract_baseline.py --check --mutate-drop file_path # 自检：护栏必须变红

退出码：0 = 通过；1 = 有契约破坏；2 = 网络/文件错误。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
BASELINE_PATH = BASE_DIR / "docs" / "refactor" / "contract-baseline.json"
DEFAULT_BASE = "http://127.0.0.1:18923"
# 语料里最大的会话（6635 事件 / 12 轮），详情契约用它采样
DETAIL_CID = "1eaa5a8745ff40cb"

MAX_ARRAY_SAMPLE = 4
MAX_DEPTH = 4
HTTP_TIMEOUT = 120.0

# 本机自测不应经过任何 HTTP 代理（Windows 上常见 HTTP_PROXY 环境变量会拦截
# 127.0.0.1 请求并返回代理自身的错误页），因此显式禁用 ProxyHandler。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# GET 接口：真打一遍，记录完整响应结构
GET_ENDPOINTS: list[dict[str, str]] = [
    {"id": "status", "path": "/api/status"},
    {"id": "sessions_all", "path": "/api/sessions"},
    {"id": "sessions_format_antigravity", "path": "/api/sessions?format=antigravity"},
    # Trae 行独有 account/all_files/mode/model/workspace 等字段；用 format 过滤
    # 显式覆盖，避免 sessions_search 的采样集合随数据/标题变化而丢失这些键。
    {"id": "sessions_format_trae", "path": "/api/sessions?format=trae"},
    {"id": "sessions_search", "path": "/api/sessions?q=Git&format=all"},
    {"id": "session_detail", "path": f"/api/session/detail?catalog_id={DETAIL_CID}"},
    {"id": "session_inspect", "path": f"/api/session/inspect?catalog_id={DETAIL_CID}"},
    {"id": "search_content", "path": "/api/search/content?q=Git&limit=5"},
]

# POST 接口：不真打（会改磁盘：扫描/迁移/删除）。只登记「路径 + 受理的 JSON 键」，
# 即"签名契约"。真打 POST 需要可回滚的沙箱语料，超出本轮护栏的收益。
POST_ENDPOINTS: list[dict[str, Any]] = [
    {"path": "/api/catalog/refresh", "keys": []},
    {"path": "/api/catalog/add_root", "keys": ["format", "path"]},
    {"path": "/api/catalog/remove_root", "keys": ["id"]},
    {"path": "/api/session/migrate", "keys": ["catalog_id", "target_format", "mode", "custom_out_dir"]},
    {"path": "/api/session/delete", "keys": ["catalog_id", "session_id", "format", "file_path"]},
    {"path": "/api/sessions/batch_delete", "keys": ["sessions"]},
    {"path": "/api/sessions/batch_migrate", "keys": ["catalog_ids", "target_format"]},
    {"path": "/api/open_folder", "keys": ["path"]},
]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def fetch_json(base: str, path: str) -> tuple[int, Any]:
    """请求一个接口，返回 (status, json)。网络级错误向上抛。"""
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也要记录结构（错误包也是契约）
        raw = exc.read()
        status = int(exc.code)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return status, {"_non_json_bytes": len(raw)}


# --------------------------------------------------------------------------
# 结构描述
# --------------------------------------------------------------------------
def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def describe(value: Any, depth: int = 0) -> dict[str, Any]:
    """把任意 JSON 值折叠成结构描述。"""
    vtype = _type_of(value)
    if vtype == "object":
        node: dict[str, Any] = {"type": "object"}
        if depth >= MAX_DEPTH:
            node["depth_capped"] = True
            return node
        node["fields"] = {str(k): describe(v, depth + 1) for k, v in value.items()}
        return node
    if vtype == "array":
        node = {"type": "array", "items": {"type": "any"}}
        if depth >= MAX_DEPTH:
            node["depth_capped"] = True
            return node
        merged: dict[str, Any] | None = None
        for item in value[:MAX_ARRAY_SAMPLE]:
            desc = describe(item, depth + 1)
            merged = desc if merged is None else merge_desc(merged, desc)
        if merged is not None:
            node["items"] = merged
        return node
    return {"type": vtype}


def merge_desc(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """合并两个结构描述，用于数组元素的「形状并集」。"""
    ltype, rtype = left.get("type"), right.get("type")
    if ltype == rtype:
        if ltype == "object":
            fields: dict[str, Any] = dict(left.get("fields") or {})
            for key, desc in (right.get("fields") or {}).items():
                fields[key] = desc if key not in fields else merge_desc(fields[key], desc)
            node: dict[str, Any] = {"type": "object", "fields": fields}
            if left.get("depth_capped") or right.get("depth_capped"):
                node["depth_capped"] = True
            return node
        if ltype == "array":
            litems = left.get("items") or {"type": "any"}
            ritems = right.get("items") or {"type": "any"}
            return {"type": "array", "items": merge_desc(litems, ritems)}
        return {"type": ltype}
    # 类型不一致：null 视作可空，其余记为 mixed（check 阶段对 mixed 放行）
    if ltype == "null":
        out = dict(right)
        out["nullable"] = True
        return out
    if rtype == "null":
        out = dict(left)
        out["nullable"] = True
        return out
    types = sorted({str(ltype), str(rtype)})
    return {"type": "mixed", "types": types}


# --------------------------------------------------------------------------
# 比对
# --------------------------------------------------------------------------
def compare(baseline: dict[str, Any], current: dict[str, Any], path: str) -> list[str]:
    """返回问题列表；空列表 = 契约未被破坏。"""
    problems: list[str] = []
    btype = baseline.get("type")
    ctype = current.get("type") if isinstance(current, dict) else "missing"

    if btype in {"any", "mixed"} or current is None:
        return problems
    # baseline 允许 null 的地方，现在返回了真实类型：只放行不报错
    if btype == "null" or ctype == "null":
        return problems
    if btype != ctype:
        problems.append(f"{path}: 类型变化 {btype} -> {ctype}")
        return problems

    if btype == "object" and not baseline.get("depth_capped"):
        bfields = baseline.get("fields") or {}
        cfields = current.get("fields") or {}
        for key, bdesc in bfields.items():
            child = f"{path}.{key}"
            if key not in cfields:
                problems.append(f"{child}: 字段缺失")
                continue
            problems.extend(compare(bdesc, cfields[key], child))
    elif btype == "array":
        bitems = baseline.get("items") or {"type": "any"}
        citems = current.get("items") or {"type": "any"}
        if bitems.get("type") not in {"any", "mixed"}:
            problems.extend(compare(bitems, citems, f"{path}[]"))
    return problems


# --------------------------------------------------------------------------
# capture / check
# --------------------------------------------------------------------------
def capture(base: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "base": base,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "detail_cid": DETAIL_CID,
        "get": {},
        "post": {e["path"]: {"method": "POST", "keys": e["keys"], "probe": "signature"} for e in POST_ENDPOINTS},
    }
    for endpoint in GET_ENDPOINTS:
        status, body = fetch_json(base, endpoint["path"])
        payload["get"][endpoint["id"]] = {
            "method": "GET",
            "path": endpoint["path"],
            "status": status,
            "schema": describe(body),
        }
        n_entries = len(body.get("sessions") or []) if isinstance(body, dict) else 0
        extra = f" sessions={n_entries}" if n_entries else ""
        print(f"  captured {endpoint['id']:<32} status={status}{extra}")
    return payload


def load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.exists():
        raise FileNotFoundError(f"基线文件不存在：{BASELINE_PATH}（先跑 --capture）")
    with open(BASELINE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def mutate_drop(schema: dict[str, Any], field_name: str) -> bool:
    """从当前结构描述里删掉第一个出现的 field_name（自检护栏是否真的会变红）。"""
    fields = schema.get("fields")
    if isinstance(fields, dict) and field_name in fields:
        del fields[field_name]
        return True
    if isinstance(fields, dict):
        for desc in fields.values():
            if mutate_drop(desc, field_name):
                return True
    items = schema.get("items")
    if isinstance(items, dict) and mutate_drop(items, field_name):
        return True
    return False


def check(base: str, mutate_drop_field: str | None = None) -> int:
    baseline = load_baseline()
    failures = 0
    checked = 0

    stored_get: dict[str, Any] = baseline.get("get") or {}
    for endpoint in GET_ENDPOINTS:
        endpoint_id = endpoint["id"]
        stored = stored_get.get(endpoint_id)
        if not stored:
            print(f"  [?] {endpoint_id}: 基线缺失（新接口，放行并提示 --capture）")
            continue
        status, body = fetch_json(base, endpoint["path"])
        current_schema = describe(body)
        if mutate_drop_field and mutate_drop(current_schema, mutate_drop_field):
            print(f"  [!] 自检：已从 {endpoint_id} 的当前结构里删除字段 {mutate_drop_field}")
        problems = compare(stored["schema"], current_schema, endpoint_id)
        checked += 1
        if problems:
            failures += 1
            print(f"  [FAIL] {endpoint_id} ({endpoint['path']}) status={status}")
            for problem in problems:
                print(f"         - {problem}")
        else:
            print(f"  [ OK ] {endpoint_id} ({endpoint['path']}) status={status}")

    stored_post: dict[str, Any] = baseline.get("post") or {}
    for endpoint in POST_ENDPOINTS:
        stored = stored_post.get(endpoint["path"])
        if not stored:
            print(f"  [?] POST {endpoint['path']}: 基线缺失（放行）")
            continue
        checked += 1
        if list(stored.get("keys") or []) != list(endpoint["keys"]):
            failures += 1
            print(f"  [FAIL] POST {endpoint['path']}: 受理键变化 {stored.get('keys')} -> {endpoint['keys']}")
        else:
            print(f"  [ OK ] POST {endpoint['path']} keys={endpoint['keys']}")

    print("-" * 68)
    if failures:
        print(f"结论：FAIL —— {failures}/{checked} 个接口破坏契约")
        return 1
    print(f"结论：PASS —— {checked} 个接口结构向后兼容（只增不删不改名）")
    return 0


def main(argv: list[str] | None = None) -> int:
    global BASELINE_PATH
    parser = argparse.ArgumentParser(description="接口契约基线护栏")
    parser.add_argument("--capture", action="store_true", help="抓取当前服务响应结构并写入基线文件")
    parser.add_argument("--check", action="store_true", help="对比当前服务与基线")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"服务地址，默认 {DEFAULT_BASE}")
    parser.add_argument("--out", default=str(BASELINE_PATH), help="基线文件路径")
    parser.add_argument("--mutate-drop", default=None, help="自检：人为删掉一个字段，验证 --check 会变红")
    args = parser.parse_args(argv)

    BASELINE_PATH = Path(args.out)

    if args.capture == args.check:  # 二者都没给，或都给了
        parser.print_help()
        return 2

    try:
        if args.capture:
            print(f"抓取契约基线 <- {args.base}")
            payload = capture(args.base)
            BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            print(f"已写入基线：{BASELINE_PATH}")
            print(f"  GET {len(payload['get'])} 个 / POST {len(payload['post'])} 个")
            return 0
        print(f"校验契约 <- {args.base}（基线 {BASELINE_PATH}）")
        return check(args.base, args.mutate_drop)
    except FileNotFoundError as exc:
        print(f"错误：{exc}")
        return 2
    except (urllib.error.URLError, OSError) as exc:
        print(f"网络错误：{exc}（服务是否已在 {args.base} 启动？）")
        return 2


if __name__ == "__main__":
    sys.exit(main())
