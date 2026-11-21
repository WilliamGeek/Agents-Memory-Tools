# Agents Memory Tools · Tauri 2 shell

这是 Tauri 2 桌面外壳的骨架，**不是完整安装包**。当前机器没有 Rust/cargo，
因此没有在本机编译验证；Python 后端已经按 sidecar 约定改造完成。

## 结构

- `launcher/index.html`：桌面启动页；先启动 sidecar，轮询
  `http://127.0.0.1:18922/api/status`，就绪后跳转到真实工作台。
- `src-tauri/`：Rust 外壳。启动时用 `tauri-plugin-shell` 拉起 sidecar
  `memory-tools --no-browser`，并持有子进程句柄，窗口退出时 kill。
- `src-tauri/binaries/`：放置 `memory-tools-<target-triple>.exe`。
- `scripts/build_sidecar.ps1`：用 PyInstaller 生成 onefile sidecar，并复制到
  Tauri 的 externalBin 目录。

## 构建顺序

1. 构建前端：`cd frontend; pnpm build`（产物必须在 `frontend/out`）。
2. 构建 sidecar：`powershell -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1`
3. 安装 Rust 工具链后：
   `cargo install tauri-cli --version "^2"`
   `cd src-tauri; cargo tauri build`
   （项目当前没有前端 `package.json` 的 Tauri CLI 依赖，直接使用 cargo 子命令。）

## 后端约定（已实现）

- 资源目录：源码为仓库根；PyInstaller 冻结后为 `sys._MEIPASS`。
- 可写数据目录：`MEMORY_TOOLS_DATA_DIR` 优先；冻结默认
  `%LOCALAPPDATA%\AgentsMemoryTools`。
- sidecar 入口：`MemoryTools.exe --helper <doubao-sync|trae-decrypt>`；
  源码模式仍执行 `python tools/...py`。
- 服务只监听 `127.0.0.1:<port>`，使用命名 mutex 单实例；端口被其他程序占用时
  报错退出，不再 taskkill。
- Trae 解密默认 key 仍是当前机器提取的固定值；换用户/换机器必须通过
  `TRAE_DB_KEY` 覆盖，不能把固定 key 当作通用凭据。

## 当前未完成 / 风险

- 未安装 Rust，未编译 Tauri 外壳。
- 未构建 sidecar；未验证 PyInstaller onefile 的启动时长、SmartScreen/杀软表现。
- `frontend/out` 目前由 Python HTTP 服务托管；Tauri 启动页只做跳转，不复制一套
  Next.js 运行时。
- onefile 的 sidecar 可能被杀软误报；若要做企业分发，后续改用 onedir +
  Tauri resources，或给 exe 签名。
- 数据目录首次切换时，旧 `cache/` 不会自动迁移；需要一次性迁移或 UI 提示。
