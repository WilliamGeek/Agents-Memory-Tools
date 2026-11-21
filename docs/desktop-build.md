# Agents Memory Tools · Tauri 2 桌面版构建与发布手册

> 工程副本：`F:\AgentsMemoryTools-Desktop`  
> 原项目 `F:\Agent会话记忆管理与迁移` 不作为构建输入被覆写；本手册中的所有命令都在副本中执行。

## 1. 目标与产物

本项目把原来的本地 Web 应用封装为 Windows 桌面程序：

- **壳**：Tauri 2（Rust + WebView2）
- **内核**：PyInstaller onefile 的 Python sidecar，提供本地 HTTP API 与静态前端
- **默认监听**：`127.0.0.1:18923`（与源码版的 `18922` 隔离，避免端口冲突）
- **不依赖外网服务**：会话读取、检索、索引都在本机完成

最终产物：

| 产物 | 位置 |
|---|---|
| 应用 exe | `src-tauri\target\release\agents-memory-tools-desktop.exe` |
| Sidecar | `dist\MemoryTools.exe` / `src-tauri\binaries\memory-tools-x86_64-pc-windows-msvc.exe` |
| NSIS 安装包 | `src-tauri\target\release\bundle\nsis\*-setup.exe` |
| 安装包套件 | `release\`（安装包、便携包、SHA256、说明） |

## 2. 前置环境

### 2.1 Python

```powershell
cd F:\AgentsMemoryTools-Desktop
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller pillow
```

当前副本已验证的 Python 版本为 3.13.x；PyInstaller 6.22.x。

### 2.2 Rust 与 MSVC

Rust：

```powershell
rustup show
# stable-x86_64-pc-windows-msvc
```

MSVC Build Tools 必须安装 **VC++ 工具链 + Windows SDK**。可从 Visual Studio Installer 安装 “使用 C++ 的桌面开发”，或：

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact `
  --accept-package-agreements --accept-source-agreements --silent `
  --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

构建命令必须在该环境中运行：

```powershell
$vc = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
cmd /c "call `"$vc`" && where link.exe"
```

### 2.3 Tauri CLI

```powershell
cargo install tauri-cli --version 2.12.5 --locked --force
cargo tauri --version
```

## 3. 构建顺序

### 3.1 先构建 sidecar

```powershell
cd F:\AgentsMemoryTools-Desktop
powershell -ExecutionPolicy Bypass -File .\scripts\build_sidecar.ps1
```

该脚本会：

1. 用 PyInstaller 构建 onefile、windowed 的 `dist\MemoryTools.exe`；
2. 将前端 `frontend\out`、`tools\doubao_sync.py`、`tools\dbkey\decrypt_trae.py` 打进包；
3. 复制为 Tauri 需要的 `src-tauri\binaries\memory-tools-x86_64-pc-windows-msvc.exe`。

sidecar 内置桌面父进程看门狗：Tauri 启动时注入 `MEMORY_TOOLS_PARENT_PID`，父进程退出后 sidecar 在约 2 秒内自行退出；源码运行不注入该变量，不启用看门狗，因此不会误杀源码版服务。

### 3.2 再构建 Tauri 外壳和 NSIS 安装包

推荐直接使用脚本，脚本会在 `vcvars64.bat` 之后补齐 Windows SDK 的
`INCLUDE` / `LIB`（本机 `vcvars64.bat` 曾漏加 SDK 路径）：

```powershell
cd F:\AgentsMemoryTools-Desktop
& .\scripts\build_taura.bat
```

如果只想验证 Rust 编译：

```powershell
cmd /c "call `"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat`" && cargo check"
```

### 3.3 一键发布

```powershell
cd F:\AgentsMemoryTools-Desktop
powershell -ExecutionPolicy Bypass -File .\scripts\build_release.ps1
```

脚本会生成 `release\` 下的安装包、便携包、校验和与说明文件。

## 4. 运行与数据目录

### 4.1 数据目录优先级

`runtime_paths.py` 的规则：

1. 环境变量 `MEMORY_TOOLS_DATA_DIR`（最高优先级）
2. 冻结运行：`%LOCALAPPDATA%\AgentsMemoryTools`
3. 源码运行：仓库根目录

发布版首次启动写入 `%LOCALAPPDATA%\AgentsMemoryTools`，在该目录下生成：

```text
cache\                会话索引快照、Trae 索引缓存、豆包云端缓存
exports\              导出文件
logs\                 运行日志
tools\dbkey\out\      Trae 解密库
```

**不要**把 `trae_database_plain.db`（约 747 MB）打进安装包；它是用户本机数据，不是应用资源。

### 4.2 环境变量

| 变量 | 用途 |
|---|---|
| `MEMORY_TOOLS_DATA_DIR` | 指定可写数据目录；验证/便携模式常用 |
| `TRAE_DB_PATH` | 指定 Trae 源 `database.db` |
| `TRAE_PLAIN_DB` | 指定解密输出 DB |
| `TRAE_DB_KEY` | 指定 Trae 解密密钥（不要提交到仓库） |

示例：用已准备好的测试数据目录启动桌面版（仅用于验证）：

```powershell
$env:MEMORY_TOOLS_DATA_DIR = "F:\AgentsMemoryTools-Desktop\.testdata"
.\src-tauri\target\release\agents-memory-tools-desktop.exe
```

### 4.3 首次运行的数据差异

源码版当前能看到约 800+ 条记录，是因为它已经累积了：

- `cache\doubao_cloud` 豆包云端缓存；
- `tools\dbkey\out\trae_database_plain.db` Trae 解密库；
- `cache\sessions_snapshot.json.gz` 会话快照。

全新桌面数据目录第一次启动通常只看到本机原始源文件中的记录（例如约 400 条），需要：

1. 在界面执行“同步豆包”；
2. 首次打开 Trae 会话时等待后台解密（约数十秒，747 MB 库）；
3. 如需完整复现源码版数据，可把旧目录的 `cache` 与解密库复制到新数据目录；不要复制到安装包资源目录。

## 5. 验证清单

### 5.1 Sidecar 冒烟

```powershell
$env:MEMORY_TOOLS_DATA_DIR = "F:\AgentsMemoryTools-Desktop\.testdata"
.\dist\MemoryTools.exe --no-browser --port 19022
```

另开终端：

```powershell
Invoke-WebRequest http://127.0.0.1:19022/api/status
Invoke-WebRequest "http://127.0.0.1:19022/api/sessions?format=trae&limit=3&fields=lite"
```

已验证的关键结果：

- `/api/status` → 200
- `/` 静态页 → 200，约 17 KB
- 带完整测试数据：`total=839`，`trae=96`，`doubao=374`，`codex=4`
- 第二个同参数侧车进程退出码 0（命名 mutex 单实例）
- 仅监听 `127.0.0.1`

### 5.2 Trae 解密

```powershell
$env:MEMORY_TOOLS_DATA_DIR = "F:\AgentsMemoryTools-Desktop\.testdata"
.\dist\MemoryTools.exe --helper trae-decrypt
```

验证点：

- 输出 `tools\dbkey\out\trae_database_plain.db`，大小约 747,278,336 字节；
- 用 SQLite 打开后 `history_v2` 有 3 万+ 行；
- 冻结侧车不再使用 `multiprocessing.Pool`，改为线程池 + AES-CBC；在测试机上 20 秒内完成。

### 5.3 桌面壳

1. 启动 `agents-memory-tools-desktop.exe`；
2. 窗口先显示“正在启动本地记忆服务”，随后进入 `127.0.0.1:18923`；
3. 检查平台筛选、会话列表、详情、检索、导出；
4. 关闭窗口后确认 sidecar 退出（任务管理器无 `memory-tools.exe` 残留、18923 无监听）；
5. 再次启动，确认单实例/端口复用行为符合预期。

2026-11-18 已完成的真实验证：

- `agents-memory-tools-desktop.exe` 启动后窗口存在，`/api/status` 可达；
- 关闭主窗口后 app 退出，`memory-tools.exe` 随父进程看门狗退出，`18923` 已无监听；
- NSIS 安装包静默安装到独立目录成功，安装后的程序可启动、可读测试数据（trae=96、doubao=374），关闭后端口清理正常；
- `uninstall.exe /S` 退出码 0，测试安装目录被完全删除；
- 便携 zip 解压后 `AgentsMemoryTools.exe` 可启动，关闭后端口同样清理正常。

2026-11-18 严格 GUI/功能复核（最新构建）：

- 完整测试数据 `/api/status` 为 `total=839`，各平台为 Antigravity 166、Claude Code 84、WorkBuddy 115、Trae 96、豆包 374、Codex 4；
- Tauri 原生窗口宽度约 1283 px 时，平台筛选条采用单行横向滚动；默认可见前四项，鼠标滚轮悬停在筛选条上向下滚动后完整露出 `Trae 96`、`豆包 374`、`Codex 4`，没有夹断或丢失按钮；
- 会话卡片右上角时间已改为优先使用 `mtime`，与默认“最近活跃”排序使用同一时间基准；Trae 列表按照 `mtime` 降序显示，卡片日期与排序一致；
- 全局检索 `FTS5`：`全部 43 / 会话 10 / 消息 33`，耗时约 33 ms，`全部/会话/消息` 分类标签可切换；
- 打开 Trae 长会话详情，`user_uploaded_files` 全文扫描 0 命中；用户指令后存在思考过程、行动、回复分组，单条用户指令对应单条回复；
- 最新发布包：安装包 `24,796,459` 字节，便携包 `25,788,874` 字节；上述安装/卸载/便携启动测试均针对该版本重新执行。

## 6. 已知限制

- Tauri 应用与源码版使用不同端口（18923 vs 18922），这是为了避免同时运行时的端口冲突；不是数据隔离。
- 首次启动不会自动复制旧版缓存；需要同步/解密或手工迁移缓存（见 4.3）。
- NSIS 安装包当前为 currentUser 安装，不写系统级目录；WebView2 由 Windows 11 自带或安装器下载引导。
- 未做代码签名，SmartScreen 可能提示“未知发布者”；正式分发前应购买证书并在 CI 中签名。
- 未接入自动更新；更新需要重新分发安装包。
- Trae 解密密钥来源与授权由使用者自行负责；不要把密钥提交到仓库、日志或安装包。

## 7. 回滚与卸载

- 卸载：Windows“应用和功能”中的 Agents Memory Tools，或 NSIS 安装目录的 `uninstall.exe`。
- 用户数据默认保留在 `%LOCALAPPDATA%\AgentsMemoryTools`；卸载不会删除该目录。需要彻底清理时手动删除该目录。
- 构建失败回滚：删除 `dist`、`build`、`src-tauri\target` 后重跑；不要删除原项目 `F:\Agent会话记忆管理与迁移`。
