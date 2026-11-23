# 网页版与桌面版的偶联维护

## 目标

只维护一份代码，同时提供两种入口：

- 网页版：浏览器打开，使用 `启动网页版.cmd`
- 桌面版：`D:\Agents Memory Tools\agents-memory-tools-desktop.exe`

两份入口不应该再各自维护一套 `web_app.py` 或前端。当前唯一源码目录：

`D:\AgentsMemoryTools`

为了方便按原目录名访问，D 盘同时建立了一个目录联接（junction）：

`D:\Agent会话记忆管理与迁移` → `D:\AgentsMemoryTools`

它不是第二份源码；从这里修改文件，改的仍是同一套代码。

当前桌面版安装目录：

`D:\Agents Memory Tools`

## 运行方式

`启动网页版.cmd` 按以下顺序选择后台：

1. `127.0.0.1:18923` 已有桌面版后台：直接复用，网页版和桌面版是同一个进程、同一份数据。
2. 已安装桌面版但后台未运行：启动 `D:\Agents Memory Tools\memory-tools.exe --no-browser --port 18923`，再打开网页。
3. 没有安装桌面版：回退到 `D:\AgentsMemoryTools\web_app.py`，运行在 `18922`，并把 `MEMORY_TOOLS_DATA_DIR` 指向 `%LOCALAPPDATA%\AgentsMemoryTools`。

正常情况下，网页版不会另起一套数据库，功能模块与桌面版一致。

## 数据目录

两种入口共用：

`C:\Users\HP\AppData\Local\AgentsMemoryTools`

包括：

- `cache\doubao_cloud`：豆包云端会话缓存
- `cache\sessions_snapshot.json.gz`：会话列表快照
- `token_cache.json`：Token 统计缓存
- `exports`、`logs`、`tools\dbkey`

## 唯一源码与构建流程

当前源码目录带着 Git 历史，远端为：

`git@github.com:WilliamGeek/Agents-Memory-Tools.git`

修改代码后：

```powershell
cd D:\AgentsMemoryTools
git pull
powershell -ExecutionPolicy Bypass -File .\scripts\build_all.ps1
```

`build_all.ps1` 会：

1. 构建 PyInstaller sidecar
2. 构建 Tauri 外壳和 NSIS 安装包
3. 将安装包复制到 `release\`
4. 写入 `BUILD_INFO.json`（commit、web_app.py 哈希、sidecar 哈希、安装包哈希）

然后用新安装包覆盖安装 `D:\Agents Memory Tools`，或在确认没有桌面版进程后替换 sidecar。

## 对齐检查

```powershell
cd D:\AgentsMemoryTools
powershell -ExecutionPolicy Bypass -File .\scripts\verify_parity.ps1
```

检查内容：

- `src-tauri\binaries` 中构建出的 sidecar 与 D 盘安装版 sidecar 的 SHA256 是否一致
- `BUILD_INFO.json` 记录的 commit 与当前 Git HEAD 是否一致
- `18923` 桌面版与 `18922` 网页源码服务（如果正在运行）的会话总数、豆包会话数和最近活跃首条是否一致

## 不再维护的旧目录

`F:\Agent会话记忆管理与迁移` 是旧版网页源码快照，不再作为第二套维护源。它的核心兼容修复已经进入当前源码，但文件不是逐文件相同。

以后只改 `D:\AgentsMemoryTools`。旧目录可以作为归档保留，确认没有独有数据后再删除。
