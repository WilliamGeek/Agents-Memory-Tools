"""列表字段投影（lite 字段白名单）。

背景
----
`GET /api/sessions` 全量响应 285 KB / 364 条（≈780 B/条），其中大部分体积来自
**从来不被卡片渲染**的字段：`children`（14993 B）、`all_files`（Trae 的文件集合）、
`account` / `workspace` / `mode` / `model` / `aux_tokens` 等。

`fields=lite` 只保留「卡片 + 排序 + 折叠判定 + 复制按钮」真正需要的键，
把单条压到 ~630 B。**旧页面（`/`）不传 `fields`，因此完全不受影响。**

硬规则（写在这里，后续改动必须遵守）
------------------------------------
1. `LITE_FIELDS` 之外的东西一律不出现；新增字段想进 lite 必须显式加白。
2. `session_id` / `file_path` **绝不能**被删：卡片上的「复制 UUID / 复制路径」
   依赖它们（`SessionCard.tsx` 一行不改）。
3. 数值 `0` 与布尔 `false` **永不省略**：`exists: false` 一旦被省，
   前端 `normalize.ts` 的 `raw.exists !== false` 会把它变成 `true`。
4. 只省略 `None` / `""` / `[]` / `{}` 这类「无信息空值」。
"""
from __future__ import annotations

from typing import Any

#: lite 模式返回的字段白名单（顺序即快照里的键顺序，便于人眼比对）
LITE_FIELDS: tuple[str, ...] = (
    "catalog_id",
    "session_id",
    "format",
    "title",
    "started_at",
    "mtime",
    "records",
    "bytes",
    "tokens",
    "file_path",
    "exists",
    "children_count",
    "lineage_size",
    "is_lineage_branch",
    "branch_label",
    "side_question",
    "lineage_head_title",
    "lineage_head_steps",
    "parent_id",
    "is_child",
    "agent_name",
    "usage_source",
    "input_tokens",
    "output_tokens",
)

#: lite 模式显式砍掉的字段（写出来是为了让 diff 一眼看到"砍了什么"）
LITE_DROP: tuple[str, ...] = (
    "children",
    "parent_title",
    "account",
    "workspace",
    "mode",
    "model",
    "aux_tokens",
    "parent_catalog_id",
    "all_files",
    "lineage",
    "lineage_head_id",
    "nesting_depth",
    "thoughts_tokens",
    "content_tokens",
    "chat_tokens",
)

#: 永远保留（即便是空字符串），避免消费方读 `undefined`
_ALWAYS_KEEP: frozenset[str] = frozenset(
    {"catalog_id", "session_id", "format", "title", "file_path", "mtime", "exists"}
)


def _is_empty(value: Any) -> bool:
    """只把「无信息空值」视为空；0 / False 不算空。"""
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


def project_lite(item: dict[str, Any]) -> dict[str, Any]:
    """把一条全量会话记录投影成 lite 版本（纯函数，不修改入参）。"""
    projected: dict[str, Any] = {}
    for field in LITE_FIELDS:
        if field not in item:
            continue
        value = item[field]
        if _is_empty(value) and field not in _ALWAYS_KEEP:
            continue
        projected[field] = value
    # 兜底：白名单字段在源数据里缺失时补中性值，保证形状稳定
    projected.setdefault("catalog_id", item.get("catalog_id", ""))
    projected.setdefault("session_id", item.get("session_id", ""))
    projected.setdefault("format", item.get("format", ""))
    return projected


def project_lite_many(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量投影，保持顺序。"""
    return [project_lite(item) for item in items]


def missing_lite_fields(item: dict[str, Any]) -> list[str]:
    """自测辅助：返回一条 lite 记录里缺失的白名单关键字段（用于断言）。"""
    required = ("catalog_id", "session_id", "format", "title", "mtime", "exists", "file_path")
    return [field for field in required if field not in item]
