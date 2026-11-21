# 桌面端工作逻辑图：维护与测试入口

本目录是 `Agents Memory Tools` 桌面端的工作逻辑图源，不是手画稿。

- 规范源：`architecture.json`
- 交互看板：`..\WORKFLOW.html`
- Mermaid 同步版：`..\WORKFLOW.md`

## 修改与验证流程

```powershell
# 1. 先校验顶点引用、Spine 对齐、同列间距和跨列穿模
& "F:\skills\video-to-mindmap\.venv\Scripts\python.exe" "F:\skills\dag\scripts\cli.py" validate "F:\AgentsMemoryTools-Desktop\docs\dag\architecture.json"

# 2. 渲染单文件交互 HTML，并同步 Mermaid Markdown
& "F:\skills\video-to-mindmap\.venv\Scripts\python.exe" "F:\skills\dag\scripts\cli.py" render "F:\AgentsMemoryTools-Desktop\docs\dag\architecture.json" -o "F:\AgentsMemoryTools-Desktop\docs\WORKFLOW.html" --md "F:\AgentsMemoryTools-Desktop\docs\WORKFLOW.md"
```

修改节点时必须同步两样东西：`details.code_anchor` 指向真实文件/函数，`details.test_anchor` 给出可复现验证。只改图、不改锚点，下一次维护会把图重新写空。

## 测试实例化

图上的 `ACCEPT` 节点是验收入口，实际启动参数如下：

```powershell
$env:MEMORY_TOOLS_DATA_DIR = "F:\AgentsMemoryTools-Desktop\.testdata"
& "F:\AgentsMemoryTools-Desktop\src-tauri\target\release\agents-memory-tools-desktop.exe"
```

完整测试数据的期望值：

| 检查点 | 期望 |
| --- | --- |
| `/api/status` | `total=839` |
| 平台计数 | Antigravity 166、Claude Code 84、WorkBuddy 115、Trae 96、豆包 374、Codex 4 |
| 全局检索 `FTS5` | 全部 43、会话 10、消息 33 |
| 详情尾部 | `user_uploaded_files` 0 命中 |
| 安装包/便携包 | NSIS 安装/启动/卸载；zip 解压启动；关闭后 18923 释放 |

默认 `%LOCALAPPDATA%\AgentsMemoryTools` 首次约 476 条，属于预期差异：该目录没有迁移完整的豆包云端缓存和 Trae 解密库。不要把默认目录的 476 写成索引失败。

## 节点维护对照

| 节点 | 真实锚点 | 验证入口 |
| --- | --- | --- |
| `A_Tauri` | `src-tauri/src/main.rs` | 启动/关闭，检查 sidecar 生命周期 |
| `A_Paths` | `runtime_paths.py` | `MEMORY_TOOLS_DATA_DIR` 覆盖 |
| `G_Bind` / `X_Bind` | `web_app.py` 的 `main()`、`services/instance.py` | 第二实例、端口占用 |
| `A_HTTP` | `web_app.py` 的 `RequestHandler` | `/api/status`、304 |
| `A_Adapters` | `web_app.py` 的 `collect_all_sessions`、`get_trae_sessions`、`get_doubao_sessions` | 平台筛选与格式化计数 |
| `F_Async` | `_maybe_refresh_trae_plain`、`_maybe_autosync_doubao`、`tools/dbkey/decrypt_trae.py` | helper 与 `/api/doubao/sync/status` |
| `A_Snapshot` | `services/snapshot.py` | `X-Cache`、分页稳定 |
| `A_FTS` | `SessionFTSManager` | `/api/search/content` |
| `A_API` | `web_app.py` 路由、`services/detail.py` | `curl` / 304 / `turn_offset` |
| `A_UI` | `frontend/src/app/page.tsx`、`Toolbar.tsx`、`SessionCard.tsx` | 滚轮横向筛选、mtime 卡片日期 |
| `Deliver` / `A_Release` | `scripts/build_sidecar.ps1`、`scripts/build_release.ps1` | 安装/卸载/便携包/SHA256 |
