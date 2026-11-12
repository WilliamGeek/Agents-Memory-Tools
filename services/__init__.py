"""后端服务层（本轮 refactor 新增）。

设计原则
--------
1. **单向依赖**：`services/*` 绝不 import `web_app`。所有需要宿主能力的地方
   （建列表、解析会话、FTS）都以**回调注入**的方式传入，避免循环 import。
2. **零语义改动搬迁**：能原样搬的逻辑就原样搬，本层只负责「缓存 / 切片 / 裁剪」
   这类传输层职责。
3. **契约只增不减**：任何被裁掉的字段都必须在别处有替代入口（例如列表 lite
   砍掉 `children` 后有 `/api/session/children`）。
"""

__all__ = ["detail", "fields", "snapshot", "turns"]
