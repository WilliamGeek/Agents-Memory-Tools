# 交接文档：本地会话记忆取证（Trae 已接入 / Codex 已补索引 / 豆包云端已打通）

- 文档版本：2026-11-17 16:30（本机时间，UTC+8）
- 适用对象：接手本任务的 Agent（无需回溯此前对话，按本文即可继续）
- 项目根：`F:\Agent会话记忆管理与迁移`
- 取证工具目录：`F:\Agent会话记忆管理与迁移\tools\dbkey`
- 当前结论一句话：**Trae 的 `database.db` 已完整解密、正文已导出并已接入 Memory Tools；Codex 已完成 FTS 正文索引；豆包完整正文已通过本机 Cookie 调云端只读接口拉全 365 个会话（`tools/doubao_sync.py` + `cache/doubao_cloud/`），列表/详情/FTS/增量同步/热更新全部验证通过；18922 服务运行正常。**

---

## 1. 任务背景与初始目标

### 1.1 项目是什么

`F:\Agent会话记忆管理与迁移` 是一个本地「会话记忆」工具集（下称 Memory Tools），主体是单文件 `web_app.py`（约 26 万字节）加 `services/`、`frontend/`，默认监听 18922 端口。它把本机上多个 AI 客户端的会话读取出来、统一列表展示、看详情、全文检索（FTS5），并支持迁移/导出。

已支持的来源（按 `get_*_sessions()` 分）：Antigravity、Claude Code、Codex、WorkBuddy、**Trae**、**Doubao**。

### 1.2 本轮任务的初始目标（两条线）

1. **主线 A（早期已交付）**：完整读取 Antigravity 会话库 `C:\Users\HP\.gemini\antigravity\conversations\c9243851-6d53-42cf-9089-2c77c2b9d16c.db`（32,440,320 B，明文 SQLite，`steps` 1,460 条），并递归找出母会话与子 Agent 的源文件，按六个维度整理成文。产物 `docs\session-archive-c9243851.md`。
2. **主线 B/C（本轮主攻）**：把豆包（Doubao）与 Trae 的本地加密库解开，取出**会话正文**。用户明确授权自有资产、自有机器，允许内存 dump、调试器挂钩、多试 offset；同时给了一条硬约束：**「不建议做的不做」**（不碰 CUDA、不啃没有明文页的库），且**明令禁止 GUI 自动化**（此前用桌面控制导致其系统会话被切换、豆包等应用登出，被迫重启）。

### 1.3 本轮收尾目标（本次交接的直接起因）

- 把 **Trae 的会话全部解完**，并**接入 Agents Memory Tools**（列表、详情、检索都要能用）。
- 对**豆包**围绕「`im.db` 的 WAL」与「持库进程 PID 7492」做**深度调研**，把能验证的都验证掉。
- 把全部上下文打包成一份**结构化交接文档**（即本文），供后续 Agent 无缝接手。

---

## 2. 用户需求时间线（按提出节点）

| # | 提出节点 | 用户原话 / 需求 | 关键约束与背景 |
|---|---|---|---|
| 1 | 任务开始 | 完整读取 `c9243851….db`，递归查找子/母 Agent 的会话源文件，按 6 维度整理，反复自检 | 要求「清晰准确、无遗漏、无歧义」 |
| 2 | 同一轮 | 尝试完成豆包与 Trae 的数据库读取；提到可抓 dump 扫密码、多试 offset、必要时 CUDA；可用 `F:\skills\reverse-engineer-anything`、`F:\skills\leanrea` | 「这本来就是我的资产」 |
| 3 | 后续轮 | 「我现在打开了 trae，把剩下的做完吧，**不建议做的不做**」 | 划出边界：不碰 CUDA、不做无收益的库 |
| 4 | 后续轮 | 「继续」 | — |
| 5 | 后续轮 | 「现在退出控制电脑返回我的原本桌面」 | 指桌面控制会话 |
| 6 | 后续轮 | 「之前你给我打开了一个虚拟电脑是吗」 | 对 CU 机制的疑问 |
| 7 | 后续轮 | 「为什么授权后系统变成『断开连接（与远程电脑）』，已登录的豆包等账号都没了，我不得已重启」 | **事故**：CU 在 Windows 以独立会话实现，激活 main 会把控制台会话切后台，会话级凭据失效 |
| 8 | 后续轮 | 「检查会话记忆库读取结果，继续完成没有完成的任务」 | 回到取证主线 |
| 9 | 后续轮 | 「豆包完成得怎样，你具体是如何完成的」 | 要求交代方法 |
| 10 | 后续轮 | **「用侵入式挂钩的方式努力尝试对 trae 和豆包的会话记忆的正文获取」** | 明确点名调试器/断点路线 |
| 11 | 后续轮 | 「我已在 trae 里发送会话」「好了」 | 提供触发重连的时机 |
| 12 | 后续轮 | 「接下来可以怎么做，需要我帮助就提前说」 | — |
| 13 | 后续轮 | 「ok 你开始吧」 | 正式开工本轮 |
| 14 | 后续轮 | 「看来豆包的记忆是存在了云端是吧」 | 由此触发对 WAL 的复核，纠正了「豆包库是空壳」的错误结论 |
| 15 | **本轮** | **「把 trae 的会话解完并接入 Agents Memory Tools；对豆包围绕最后的 WAL 和 PID 7492 深度调研、验证足够多信息，然后把所有内容打包成结构化交接总结文档（含 6 个模块）」** | 交付形态：可直接接手的文档 |
| 16 | 2026-11-17 | **「把 Codex 平台的会话索引也部署上去吧」** | 补 Codex 的 FTS 正文索引；要求搜索/详情可用 |
| 17 | 2026-11-17 | 截图标注**「平台多了会难以显示，你看如何处理」** | 平台筛选条 UI；最终明确改为**单行横向滚动 + 鼠标滚轮移动条目**，不要换行 |
| 18 | 2026-11-17 | 「再检查一下还有没有什么问题……这份工作交接文档还有没有什么要改的」 | 本次交接复核与文档更新 |

---

## 3. 已完成的改动、实现与交付物

### 3.1 Trae：从「拿不到密钥」到「整库明文」

#### 3.1.1 关键突破：截获到的是**原始密钥**，不是口令

此前长期假设 `PRAGMA key = '<口令>'`，穷举了 1,295 条候选口令 × 8 组 KDF 全部为零。真实抓到的是：

```
x'3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773'
```

`x'…'` 内 64 个 hex = 32 字节密钥本体，**SQLCipher 原始密钥（raw key）写法，完全跳过 PBKDF2，salt 不参与派生**。这一条同时解释了「口令穷举全零」与「32 字节裸密钥扫内存全零」两个此前的反常现象。

#### 3.1.2 取到密钥的方法（可复现）

工具：`tools\dbkey\fast_attach.py`（参数：秒数；环境变量 `TRAE_DB`）

1. `psapi.EnumProcesses` 每 **5 ms** 扫 PID（**注意：`EnumProcesses` 在 psapi.dll，不在 kernel32**，写错会 `AttributeError`），抢在 harness 加载完成前 `DebugActiveProcess` 挂上；
2. 在 `harness.dll` 的 `PRAGMA key = ` 字面量挂 1 字节读写断点（`RVA 0xb620449`，运行时 `VA 0x7fff93460449`，基址 `0x7fff93460000`），覆盖 39 个线程；
3. 命中后撤断点、置 **TF 单步**；**每条单步异常里都必须重设 TF**（CPU 陷入时自动清零；不重设就只走一步——这是最后一个卡点）；
4. 单步期间除了读 `rcx` 指向的目标缓冲，还要把 **10 个通用寄存器（rax/rcx/rdx/rbx/rsp/rbp/rsi/rdi/r8/r9）**各读 300 字节扫一遍：Rust 的 `String` 会 realloc，成品串挂在别的寄存器上。本次在第 4,000 步、偏移 `0xb8` 处命中；
5. 触发时机：结束「持库的沙箱实用子进程」即可让 `Chromium` 自动重建连接（WAL 模式，杀子进程不损数据），**不必重启 IDE**。

相关调试器常量（x64，已实测）：`CONTEXT` 大小 1232、`ContextFlags@0x30 = 0x00100013`；`EFlags 0x44`、`Dr0 0x48`、`Dr6 0x68`、`Dr7 0x70`、`Rax 0x78`、`Rcx 0x80`、`Rdx 0x88`、`Rsp 0x98`、`Rip 0xF8`；1 字节读写断点 `Dr7 = 0x40001 | (0x3<<16)`；**`DEBUG_EVENT` 联合体在偏移 16**（按 12 解析会让异常码恒为 0）。

#### 3.1.3 页布局与验证（已确证）

| 项 | 值 |
|---|---|
| 第 1 页 | `[salt 16][密文 4000][IV 16 @4016][HMAC 64 @4032..4096]` |
| 其余页 | `[密文 4016][IV 16 @4016][HMAC 64 @4032..4096]` |
| reserve | 80（= IV16 + HMAC64），真实页数据 4016 字节 |
| 磁盘 salt | `81d071c4bc55cd26681ee72bfdce3bdf`（raw key 模式下只作文件标识） |
| IV 位置 | **4016**；4016/4032/4064/4080 四档只有 4016 解出 `page_size=4096` |
| 复校 | 解密首页与持库进程内存明文首页 `0x230195c57b0` **逐字节完全一致** |

#### 3.1.4 解密与导出

- `tools\dbkey\decrypt_trae.py`：8 进程并行，AES-256-ECB 分块 + 链式 XOR，逐页剥 IV；第 1 页补回 `SQLite format 3\0`，第 2 页起明文 4016 字节 + 尾部 80 字节补零。
  - 输入 `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db`，**733,925,376 B / 179,181 页**
  - 输出 `tools\dbkey\out\trae_database_plain.db`（同尺寸，`sqlite3` 可直接打开）
- `tools\dbkey\export_history.py`：导出 `tools\dbkey\out\trae_history_v2.jsonl`（**111,181,168 B**）与 `docs\trae-db-export.md`

内容规模（实测）：

| 指标 | 数值 |
|---|---|
| `history_v2` 记录 | 32,014 |
| 展开消息 | 57,877（user 1,794 / assistant 25,480 / tool 30,603） |
| 会话 | 93 |
| 正文字符 | 87,338,483 |
| 其它表 | `task` 1,476 / `project` 21 / `session_project` 85 / `local_artifact` 5 / `toolcall` 0 / `message_delivery` 0 / `im_conversation` 0 |

#### 3.1.5 接入 Memory Tools（本次改动，全部在 `web_app.py`）

新增/修改如下（按函数名定位，行号会漂移，勿按行号硬编码）：

1. **新增模块级常量与缓存**
   - `TRAE_PLAIN_DB = Path(r"F:\Agent会话记忆管理与迁移\tools\dbkey\out\trae_database_plain.db")`
   - `_TRAE_DB_CACHE = {"sig": "", "index": {}}`（按库文件 `(mtime,size)` 缓存聚合结果）
2. **新增 5 个工具函数**
   - `_trae_db_conn()`：只读打开（`file:...?mode=ro`，uri=True），库不存在返回 `None`
   - `_trae_flatten_messages(raw)`：把 `history_v2.messages` 的 `{"raw_messages":[{role,content:[...]}]}` 压成 `[(role, text)]`；`tool_use` 输入截断 500 字符、`tool_result` 截断 600 字符
   - `_trae_ts(epoch)`：epoch 秒 → UTC 字符串（与本文件其它 `started_at` 口径一致）
   - `_trae_db_index()`：按会话聚合 `records / msgs / chars / tokens / first / last / last_mtime / title`（title 取首条非 `<system-reminder>` 的用户消息首行）
   - `_trae_db_messages(sid)`：按会话取完整正文，产出事件 `{kind, role, text, timestamp, tool_name...}`；`tool` 角色输出为 `kind="tool_result"`，文本截断 1,200 字符
3. **`get_trae_sessions()` 增加「2.5 解密库合并」段**：把 DB 聚合结果并入 `sessions_map`，置 `has_db/db_records/db_tokens`，`records` 取消息数、`bytes` 取字符数、`started_at` 取最早时间
4. **跳过条件修正**：`if not has_jsonl and not has_ih and not has_db: continue`（此前只有 jsonl / input_history 两会来源，纯 DB 会话会被丢弃）
5. **标题优先级修正**：`if not has_jsonl and has_ih and not has_db:` 才用「Trae 工作区提问历史」占位标题，让 DB 里的真实首问成为标题
6. **Token 口径**：`has_db` 且 `db_tokens>0` 时直接用库里的 `token_usage` 汇总，覆盖估算值（`t_aux` 置 0）
7. **结果字段新增**：`has_db`、`db_records`、`db_tokens`
8. **`get_trae_session_messages()` 新增「0. 优先解密库」分支**：`if sid and (session_match.get("has_db") or _trae_db_index().get(sid))` → 直接返回 DB 正文；memory jsonl / state.vscdb 作为回退
9. **FTS 索引改造**
   - 主循环新增跳过：`if str(p_str).endswith("trae_database_plain.db"): continue`（同一物理库不能按文件路径重复索引）
   - 新增 **2b 段**：对每个 `has_db` 会话，用**合成索引键** `trae_db://<sid>` 单独建索引（`GLOBAL_FTS_MGR.index_session_turns`），`catalog_id` 用 `trae_<sid[:16]>`

### 3.2 豆包：围绕 WAL 与持库进程的深度调研（写作时 PID 7492，当前 22508）

#### 3.2.1 库与进程现状（实测）

> **进程已变化**：下面的库表与内存证据是 **2026-11-16 22:35** 的现场快照（当时 PID 7492）。**2026-11-17 12:15 复核** 时 PID 7492 已退出，豆包主进程变为 **PID 22508**（父 20968，启动 09:31:39），WAL 也已增长。旧的内存基址/VA 只对应 7492，不能在当前进程直接复用；挂接前先用 Toolhelp 重新取模块基址，并确认实际持库的是主进程还是其子进程。

库目录：`C:\Users\HP\AppData\Local\Doubao\User Data\sdk_storage\e4f7b54c6016831d50c70684aeaef4ff\`

| 库 | 主文件 | WAL（2026-11-16 22:35 快照） | WAL 帧数 | 说明 |
|---|---|---|---|---|
| `im.db` | 4,096 B（1 页） | **1,446,152 B** | **351**（其中 pgno=1 的 11 帧） | 正文在这里，未 checkpoint |
| `resource.db` | 4,096 B | 556,232 B | 135 | 同上 |
| `search_v2_5260_0000.db` | 4,096 B | 2,640,952 B | 641（页号从 3 起） | 同上 |
| `suite_drive_cypher.db` | 4,096 B | 111,272 B | 27 | 同上 |
| `settings.db` | 2,887,680 B（705 页） | 5,030,552 B | 1,221 | 已解开，`settings_fields` 1,796 行 |
| `messages.db` | 450,560 B（110 页） | 0 | 0 | 已解开，38 表全 0 行（真空） |
| `cookie_store.db` | 28,672 B（7 页） | 0 | 0 | 仅 cookie |
| `common.db`（`sdk_storage` 根） | 4,096 B | 3,823,392 B | 未拆 | 尚未分析，疑似 SDK 级共享库 |

**当前复核（2026-11-17 12:16，PID 22508）**：`im.db-wal` 1,491,472 B / **362 帧**（pgno=1 共 12 帧，salt `bbcaa2fa94bed157`）；`resource.db-wal` 597,432 B / 145 帧；`search_v2_5260_0000.db-wal` 2,813,992 B / 683 帧；`suite_drive_cypher.db-wal` 123,632 B / 30 帧；`common.db-wal` 3,868,712 B / 939 帧。页大小仍为 4096，WAL 头版本 3007000；结构判断不变，但 salt 已轮换，旧的“按 salt 扫内存”脚本必须重跑。

持库进程：写作时是 **PID 7492**（`F:\Doubao\app\Doubao.exe`，父进程 32944，客户端主进程）；当前复核为 **PID 22508**（父 20968），实际 SQLite 句柄可能在它的 Chromium 子进程中，挂接前先确认。杀掉主进程等于关闭豆包，等于中断当前会话。它同时持有上面所有库（`im/resource/search_v2/suite_drive/cookie_store`）。

#### 3.2.2 WAL 结构（已核验）

- WAL 头：magic `0x377f0682`、版本 `3007000`、page size 4096
- **pgno=1 的帧第 0..16 字节就是主库 salt**（写作时 `2da964e5600a7df44ef1b1e4057c7009`；当前已轮换为 `bbcaa2fa94bed157`），说明 WAL 里的第 1 页是含 salt 前缀的整页镜像
- 每页尾 16 字节逐页不同（`f7f31062…` / `458a9f7e…`），符合「每页独立 IV 存页尾」的 SQLCipher 布局
- 由「页尾 16 字节 = IV、其前 64 字节随机」推断（**推断，缺密钥尚未明文校验**）：Doubao 侧 reserve 同样是 80，排列与 Trae **相反**——
  - 第 1 页 `[salt16][密文4000][HMAC64 @4016..4080][IV16 @4080..4096]`
  - 其余页 `[密文4016][HMAC64 @4016..4080][IV16 @4080..4096]`

#### 3.2.3 代码层证据（静态扫描）

扫描 `F:\Doubao\app` 下 161 个二进制（1,347.2 MB）中的字符串：

| 字符串 | 命中位置（文件偏移） |
|---|---|
| `PRAGMA key` | `liblark.dll @0x883c950`（**唯一一处**） |
| `sqlcipher` | `Doubao.dll @0x11a4d6d1`、`liblark.dll @0x9306c00` |
| `cipher_migrate` | `Doubao.dll @0x11a4d3e5`、`liblark.dll @0x9306ce8` |
| `db-newkey` | `liblark.dll @0x859e768` |

`liblark.dll` 的 PE 信息与运行时地址：

- 文件 `F:\Doubao\app\liblark.dll`，**188,221,840 B**，`ImageBase 0x180000000`
- 段表：`.text RVA 0x1000/vsize 0x8518aaa`、`.rdata RVA 0x851a000/vsize 0x2858942`、`.data 0xad73000`、`.pdata 0xadab000`、`.reloc 0xb2e1000`
- `PRAGMA key` 文件偏移 `0x883c950` → **RVA `0x883d950`**（落在 `.rdata`）
- 运行时基址 `0x7fffd0560000` → **VA `0x7fffd8d9d950`**（这是 **PID 7492 当时**的值，与内存实扫命中地址吻合）；当前已重启为 PID 22508，基址会变，**RVA `0x883d950` 不变，挂接前必须用 Toolhelp 重新取基址**，不要直接复用旧 VA

在 **当时的 PID 7492** 全内存做 `PRAGMA\s*key` 正则扫描：**只命中 1 处，就是上面那个 DLL 字面量**，说明运行时拼好的 `PRAGMA key = "…"` 字符串**没有残留在内存**（被及时擦除）。当前 PID 22508 未重跑这项扫描，地址/基址需重新计算。

#### 3.2.4 已试过且失败的取密钥路径（不要再重跑）

| 尝试 | 结果 |
|---|---|
| 用 `messages.db` 密钥 `3b9cb6b2…f351` 解 `im.db` | 失败（四档 IV 全不通） |
| 用 `settings.db` 密钥 `3df0a9d4…a893` 解 `im.db` | 失败 |
| 用 `db-newkey-mark` 的 32 字节 `a8acce37…56d7fdca` 当**原始密钥** | 失败 |
| 以 `im.db` salt 为锚点、在内存 ±2048 字节邻近搜 32 字节密钥（4 字节步进、当时的 11 个 pg1 帧 × 2 种 ct 起点） | 仅命中 1 处 salt，附近无候选 |
| 主库首页作判别基准、全内存扫 32 字节窗口（8 字节步进） | 0 命中 |
| 扫 `sdk_storage\log` 下约 400–560 MB 的 SDK 日志（`PRAGMA key` / `sqlcipher` / `pbkdf2` / `hkdf` / `ATTACH`） | **全部 0 命中**；64 位 hex 只命中文件名 hash |
| 把 `db-newkey-mark` 当**口令**（原样 / 大写 / 带换行 / 带引号 / 当字节 / sha256 后）跑 5 组 KDF（sha256·256000、sha512·256000、sha1·64000、sha256·1、sha512·1） | 0 命中（`try_mark_pass.py`） |
| WAL 判别全内存扫（17 个豆包进程、13.3 GB / 3,404,135 块、4 字节步进） | 已**主动中止**：单块 4 字节步进要 3.3e9 次 AES 试算，耗时不可接受；且与「主库判别」等价，后者已零命中 |

#### 3.2.5 旁路：不受加密影响的明文层

- `C:\Users\HP\AppData\Local\Doubao\User Data\Profile 1\IndexedDB` = 8.1 MB / 41 文件，其中 `chrome_doubao-chat_0.indexeddb.leveldb` **4.37 MB** + `...indexeddb.blob` 336 KB（LevelDB，不加密，可离线解析）
- `Local Storage` 5.7 MB、`Cache` 51.5 MB、`Session Storage` 0.1 MB
- Memory Tools 里已有现成解析器：`_doubao_iter_idb_blobs()` / `_doubao_extract_idb_sessions()`（此前从这一层捞到 15 条缓存会话）

### 3.3 文档与工具产物清单

| 路径 | 内容 | 状态 |
|---|---|---|
| `docs\session-archive-c9243851.md` | Antigravity 会话六维度梳理（七部分 + 7.1） | 已交付 |
| `docs\trae-memory-export.md` | Trae 明文记忆层导出（104 条 / 34 文件） | 已交付 |
| `docs\trae-db-export.md` | Trae 解密库导出说明（含解密事实表、93 会话清单、角色分布） | 已交付 |
| `docs\handoff-trae-doubao-2026-11-16.md` | **本文** | 本轮新增 |
| `tools\dbkey\README.md` | 加密库技术档案（7.4 最终突破 / 7.5 豆包 WAL 修正） | 已更新 |
| `tools\dbkey\out\trae_database_plain.db` | Trae 明文库 733,925,376 B | 本轮新增 |
| `tools\dbkey\out\trae_history_v2.jsonl` | Trae 全量正文 111,181,168 B | 本轮新增 |
| `tools\dbkey\out\messages_plain.db` | 豆包 messages 解密库（38 表 0 行） | 既有 |
| `tools\dbkey\out\settings_plain.db` | 豆包 settings 解密库（**含 access_token，敏感**） | 既有 |

工具（均在 `tools\dbkey\`）：`fast_attach.py`（密钥截获，最终版）、`verify_rawkey.py`（原始密钥验证 IV@4016 并与内存明文比对）、`decrypt_trae.py`（整库解密）、`export_history.py`（导出 JSONL + MD）、`memscan.py`（`read_at(pid, addr, len)` 首参是 **pid**）、`hunt_imdb2.py`（salt 邻近搜）、`hunt_imdb3.py`（WAL 判别全内存扫）、`scan_doubao_bins.py`（二进制字符串扫）、`scan_doubao_logs.py`（日志扫）、`probe_7492.py`（进程/模块探针）、`lark_pe.py`（`liblark.dll` 段表与 RVA 换算）、`verify_wal_im.py`（WAL 结构核验）、`check_settings_keys.py`（settings 库找密钥）。

---

## 4. 验证结果与当前状态

### 4.1 Trae 接入：端到端验证通过（实测数据）

服务以 `MEMORY_TOOLS_PORT=18999` 做过隔离验证（未占用用户默认 18922），验证后已停止；下列数据以当前 **18922** 实测为准。当前服务进程为 `web_app.py`，本轮复核 PID **14120**（父进程 17212，PID 会随重启变化，以实际监听为准）。

| 验证项 | 命令 / 入口 | 结果 |
|---|---|---|
| 函数级：会话列表 | `get_trae_sessions()` | 会话 **95**（93 个来自解密库 + 2 个既有来源），首次调用 **4.87 s**（含 32k 行 JSON 解析，之后走缓存） |
| 函数级：取正文 | `get_trae_session_messages({"session_id": sid, "has_db": True})` | **7,370 事件 / 0.24 s** |
| 接口：`/api/status` | HTTP | `total=487`、`format_counts.trae=95`、`codex=4`、`doubao=23` |
| 接口：`/api/sessions?limit=600` | HTTP | `total=487`，分组：antigravity 166 / claude 84 / codex 4 / doubao 23 / **trae 95** / workbuddy 115 |
| 接口：`/api/session/detail?catalog_id=trae_6a8a61cf9172cf7d` | HTTP | `format=trae`、`events=12,298`（message 2,372 + tool_call 4,964 + tool_result 4,962）、117 轮、标题「2026-08-23 · Bio-Panorama 项目架构与开发」 |
| 接口：`/api/search/content?q=Bio-Panorama&limit=300` | HTTP | 命中 200 条，其中 **44 条来自 trae**（`cid=trae_6a8a61cf9172cf7d`） |
| FTS 落库 | `conversation_fts` 表 | trae 行 **15,221**（只索引人话正文，不含工具入参/输出）；trae 会话 **95**；`fts_file_meta` 中 `trae_db://` 键 **93** 个（全局元数据当前 495 行，含 1 条 0 轮 Doubao snapshot） |

> 说明：`/api/status` 与 `/api/sessions` 的总数已统一为 **487**（两者当前一致），不再有此前“差 5”的旧现象。

### 4.2 代码质量

- `web_app.py` 通过 `ast.parse` 语法检查
- 起服务、调四类接口、查 FTS 表，全部成功，无异常日志
- 旧来源（`session_memory_*.jsonl`、`state.vscdb`）仍作为回退路径保留，索引不可用时自动降级

### 4.3 豆包：已验证 / 未验证的边界

**已验证**
- 正文确实在 WAL（写作时 `im.db-wal` 351 帧 / 11 个 pg1 快照；2026-11-17 12:16 复核为 362 帧 / 12 个 pg1），不是「没有数据」
- WAL 头、页大小、pg1 含 salt、页尾逐页随机 IV 全部实测
- `liblark.dll` 是 SQLCipher 封装，含唯一 `PRAGMA key` 字面量；写作时 PID 7492 的运行时地址为 `0x7fffd8d9d950`（当前 PID 22508 需重取基址）
- 内存中无残留的完整 `PRAGMA key` 串；SDK 日志中无密钥痕迹
- 四类已知材料（messages 密钥 / settings 密钥 / db-newkey-mark 当原始密钥 / db-newkey-mark 当口令 × 5 KDF）对 `im.db` 均无效

**未验证（受密钥缺失阻断）**
- `im.db` 的 reserve 与 IV 排列只由字节分布推断，未用明文校验
- WAL 内页的真实内容（表结构、消息行数）未知（写作时 351 帧，当前 362 帧）
- `common.db`（当前 3,868,712 B WAL / 939 帧）用途未知

### 4.4 检索延迟优化（T0，2026-11-16 22:45）

**定位过程**：把 `search()` 拆成四段单独计时，发现每次检索末尾的 `get_stats()` 里
`SELECT count(*) FROM conversation_fts` 是 FTS5 全表扫描，实测 **60.6 ms**，
占端到端 65–72 ms 的 **85%**；而 `MATCH+ORDER BY rank+LIMIT 50` 仅 0.7–5.1 ms、
`snippet()` 仅 1.6–6.1 ms。

**改动**（`web_app.py` 的 `SessionFTSManager.get_stats`，仅此一处）：
计数改读 `conversation_fts_docsize`（FTS5 为每个文档维护一行，计数 O(1)，
实测 **0.01 ms**，与主表行数逐次核对一致；重建时 49,519 = 49,519，补 Codex 后为 49,562。
docsize 为空或不存在时回退主表 `count(*)`，行为不变。

| 指标 | 改前 | 改后 |
|---|---|---|
| 函数级「会话」 | 71.75 ms | **10.11 ms** |
| 函数级「记忆」 | 69.52 ms | **8.95 ms** |
| 函数级「Bio-Panorama」 | 65.29 ms | **4.63 ms** |
| HTTP `/api/search/content`（Bio-Panorama） | ~65–72 ms | **10.63 ms** |
| HTTP `/api/search/content`（会话） | ~65–72 ms | **11.42 ms** |
| 并发吞吐（4 线程 × 25 次混合查询） | 未测 | **265 QPS，0 错误** |

**口径**：`total_indexed_turns` 与 `total_indexed_files` 均不变（重建前后逐个核对）。

**重建后复测（49,519 轮 / 142.9 MiB；补 Codex 后为 49,562 轮 / 142.93 MiB）**：会话 9.64 ms、记忆 7.53 ms、Bio-Panorama 4.59 ms；
4 线程 **309 QPS，0 错误**。行数比初测多 30k 的原因见 §4.5：Trae 索引此前是**不完整**的，
重解析后按「每消息一行」补齐，同时剔除了工具入参/输出。

**索引现状（当前真实规模）**：FTS 库 **142.93 MiB（149,876,736 B）**、**49,562 轮**（trae 15,221 + codex 57 + 其它 34,284）、
**495** 个文件元数据（其中 1 条是 0 轮的 Doubao snapshot，不影响检索命中）。

**复现**：`python tools\bench_search.py`（不需要起服务）。

**硬件成本**：0。未新增内存/磁盘/GPU；约 143 MiB 索引在 OS 页缓存内即可。

### 4.5 四个界面问题的修复（2026-11-16 23:20，依据用户三张截图）

| # | 截图现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 点「查看」时同时出现两个会话标签 | `启动Memory Tools.cmd` 里的 `start http://127.0.0.1:18922` 与 `web_app.main()` 的 `webbrowser.open()` 各开一次；`后台静默启动Memory Tools.vbs` 同样 | 两个启动器统一给 Python 传 `--no-browser`，标签页只由启动器开一次（`STARTED_ENGINE` 条件判断已回退，否则服务已运行时启动器不会开窗） |
| 2 | Trae 标题是「Trae 会话 (ssh · 6aee0c53)」 | 标题取首条 user 文本首行，而首条文本是 `<system-reminder>` 注入块 → 取空 → 落到兜底名 | 新增 `_trae_title_from_text()`：前 3 个非空行拼接、去引号与 markdown、按句号或 48 字截断；**2026-11-17 追加**：改为优先读解密库 `fts_session_title.title`（Trae SOLO 任务列表用的官方标题，实测 95 个会话中 63 个有值），读取时折叠空白、超 80 字截断；优先级 = Trae 原生标题 > 首条用户输入 > 首条助手回复 > 上传文件名 |
| 3 | 用户指令里混着 `# MCP Server Instructions` 和 `<user_input>` 包裹 | 一个 user 消息含 4–6 个 text 块（若干 `system-reminder` + MCP 说明 + 真正的 `<user_input>`），旧解析把所有块直接拼接 | 新增 `_trae_clean_user_text()`：有 `<user_input>` 只取它；否则剥离 system-reminder / MCP / REQUIREMENT 注入；纯附件轮显示为「上传文件：…」 |
| 4 | 工具调用全部是「工具调用」，无名字无参数 | 旧解析只把 role=tool 记成 `tool_result` 且 `tool_name="trae_tool"`；assistant 的 `tool_calls` 被拼进正文 | 新增 `_trae_parse_messages()`：按 `tool_calls[].function_call` 拆出 `tool_call`（name + 入参）+ `tool_result`（按 call_id 回填名字）；输出剥离 `<shell_*>`/`<toolcall_result>` 外壳与 ``` 围栏 |

**实测**

- `trae_6aee0c6cf5956961`：首条用户消息只剩 `F:\tools\workflow-dag 和 F:\skills\dag 有何区别`；
  事件 53 = message 4 + tool_call 25 + tool_result 24
- `trae_6a8a61cf9172cf7d`：事件 12,298 = message 2,372 + tool_call 4,964 + tool_result 4,962（117 轮）
- 工具名实际回填：`Shell` / `Read` / `Write` / `Edit` / `Grep` / `LS` / `TodoWrite` / `DeleteFile`；
  前端 `toolMeta` 已有映射（`Shell` → 终端命令，`Read` → 查阅文件）
- 标题抽样：`F:\rea F:\rea-runtime 这两个文件是什么`、`请帮我在本地电脑中查找符合以下特征的交易数据下载工具…`
- 改用官方标题后抽样：`2026-11-16 · 分析安图生物中际旭创走势`、`2026-11-12 · Recover Lost Project Data`、
  `2026-11-06 · 解释 rea 和 rea-runtime 区别`（与 Trae SOLO 左侧任务列表一致，仍保留「日期 · 」前缀）
- FTS 按「只索引人话正文」重建：trae 15,221 行；tool_call 入参 JSON 与工具输出不再进索引

**注意**：FTS 的 `session_title` 存在每一行里，改标题逻辑后必须**重建** trae 索引才生效
（清 `catalog_id LIKE 'trae_%'` 与 `fts_file_meta.file_path LIKE 'trae_db://%'`，再跑 `_run_fts_sync_worker()`，约 44 s）。

### 4.6 首屏加载慢 + 偶发「全部 0 / 还没有收录任何会话」（2026-11-17 00:40）

**用户现象**：打开 `http://127.0.0.1:18922` 要等很久；偶发整页显示「全部 0 / 总收录 0 / 匹配 0 篇 / 0 B / 0 Tokens」+
「还没有收录任何会话」，但后端实际有 487 条。

**根因（两条独立问题叠加）**

| # | 现象 | 根因 | 实测 |
|---|---|---|---|
| 1 | 首屏慢 | `/api/status` 每次重新扫全部平台（`get_workbuddy_sessions` / `get_trae_sessions` / `get_doubao_sessions`），`/api/sessions` 冷启动还要另建一次快照 | 18922 上 `/api/status` **6455 ms**，热态也 1208–1224 ms；`/api/sessions` 冷 1483 ms（`X-Build-Ms 1390.88`）/ 热 35 ms |
| 2 | 偶发 0 条 | 前端 `useSWRInfinite` 没有错误分支：请求失败时 `pages` 为空、`isValidating=false`，`SessionGrid` 直接走空态；Toolbar 的 `status?.totalSessions || serverTotal || sessions.length` 也变 0 | 失败态与「真的没有会话」在 UI 上无法区分 |

**后端改动**

- `handle_get_status()` 不再逐格式扫盘，改为 `_get_snapshot_cache().get(allow_stale=True)` 复用列表快照的
  `items_full`，按 `format` 计数；`total_sessions = len(items_full)`（与 `/api/sessions` 的 `total` 同口径）。
- `main()` 绑定端口后起后台线程 `_warm_snapshot()` 预热快照；并删掉 `main()` 内原有的局部
  `import threading`（它会让 `threading` 变成局部变量，预热线程在其赋值前抛 `UnboundLocalError`，导致服务启动即崩）。
- `services/snapshot.py`：新增 `persist_path` / `_seed_from_disk()`（启动时 gzip 载入上次快照，`built_at` 记为载入时刻
  以免过期）/ `_persist()`（构建后 gzip 原子写盘）/ `_refresh_async()`（single-flight 后台重建）；
  `get(..., allow_stale=True)` 在指纹变化时**立即返回旧快照**（`X-Cache: stale`）并后台重建，不再阻塞首屏；
  `serve()` / 状态接口 / 预热线程均使用 `allow_stale=True`。
- `web_app.py`：快照落盘路径 `cache/sessions_snapshot.json.gz`。
- `_trae_db_index()` 增加跨进程磁盘缓存 `cache/trae_db_index.json`，按明文库 `(mtime,size)` 作 `sig`：
  32,014 行 `history_v2` 全量解析 6.4 s → 命中缓存 **90 ms**；明文库变化时自动重建并覆盖。
- `_trae_tidy_tool_output()` 增加纯文本快路径（无 `<`、无 ```、非 `[` 开头直接返回），并把错误判断从
  一次正则 search 换成小写子串判断，减少 3 万条工具输出的正则开销。

**前端改动（`frontend/src/app/page.tsx` / `components/layout/Toolbar.tsx`）**

- `useSWRInfinite` 解构 `error: listError`，新增 `listFailed = Boolean(listError) && sessions.length === 0`；
  失败且无数据时渲染「会话列表加载失败」卡片 + 错误文案 + 「重新加载」按钮（调 `refreshAll`），不再进空态；
  已有数据时失败则保留旧数据，不闪空。
- `statusError` 时显示「统计信息加载失败，正在自动重试」；两个 SWR 都加
  `shouldRetryOnError: true, errorRetryInterval: 3000, errorRetryCount: 3`。
- 统计失败时 Toolbar 计数显示 `—`、右侧显示「统计加载中…」（新增 `countsPending`），不再闪一串 0。
- 平台 chips 补上 `Codex`：166+84+115+95+23+4 = 487，与「全部」一致（此前 4 条 Codex 只算进总数、不可筛选）。

**实测（18922，Windows 本机，浏览器为 Browser Use 真实页面）**

| 场景 | 结果 |
|---|---|
| 无任何落盘缓存的首启 | 首次成功请求 **13.5 s**（`X-Build-Ms 12951.38`）——这就是用户感知的「加载很久」 |
| 有落盘缓存的重启 | `/api/sessions?limit=60&fields=lite` 首次 **94 ms**、`/api/status` **45 ms**、再次 31 ms（`X-Cache hit`） |
| 页面导航计时 | `responseEnd 86 ms` / `DOMContentLoaded 161 ms` / `load 214 ms` / `First Paint = FCP = 164 ms` |
| 前端渲染 | 全部 487；Antigravity 166 / Claude 84 / WorkBuddy 115 / Trae 95 / 豆包 23 / Codex 4；Trae 官方标题正常 |
| 详情弹窗 | `Recover Lost Project Data` 打开正常：1363 条事件、23 轮；用户指令已清洗，无 MCP 注入 |
| 故障态（18923 仅静态页、无 API） | 显示「会话列表加载失败 / HTTP 404 / 重新加载」，计数显示「全部 —」，**不再显示「还没有收录任何会话」** |
| stale 单元验证 | 指纹变化后 `get(allow_stale=True)` **1 ms** 返回旧快照（`stale`），后台重建完成后转 `hit`；新实例载入 seed **0 ms** |
| 缓存生效后的重建 | 新进程 `collect_all_sessions` **1.59 s**（trae 90 ms / doubao 495 ms / workbuddy 483 ms，其余为 antigravity+claude） |

**注意**

- 代码更新后的**第一次**启动仍要完整构建一次（约 13 s，在预热线程里跑）并写出 seed；从第二次启动起首屏即为
  百毫秒级。`cache/sessions_snapshot.json.gz` 与 `cache/trae_db_index.json` 都在项目 `cache/` 下，删掉即回到冷启动。
- `/api/status` 改为快照口径后，历史上目录口径的 `total_sessions=492`、`codex=9` 已统一为 **487 / 4**（与列表一致）；下游脚本若按旧值断言需同步。
- 前端改动必须 `npm run build` 重新导出到 `frontend/out` 才生效；构建时若 `out` 被浏览器/静态服务占用会报
  `EBUSY rmdir 'frontend/out'`，先关占用进程或临时改名再构建。
- 重启命令：`cd F:\Agent会话记忆管理与迁移; .\.venv\Scripts\python.exe web_app.py --no-browser`。

---

### 4.7 Codex FTS 接入（2026-11-17）

**代码改动**（`web_app.py` 的 `extract_dialogue_turns_for_fts()`）：

- 把 `codex` 加入 `{"antigravity", "claude", "codex"}` 分支，使用 `AgentFormat.CODEX` 和 `load_session(path, agent_format)`；
- 只把 `role=user` / `role=assistant` 的 `message` 事件写入 FTS；
  `tool_result`、`opaque`、`context` 不进入索引，避免工具输出淹没搜索结果；
- Codex 的 user 消息按 `kind == "message"` 作为轮边界，assistant 消息归入当前用户轮，逻辑与 Claude / Antigravity 一致。

**索引结果**：

| 会话 | 索引轮次 |
|---|---:|
| `01a1d82c-1470-7983-becf-ec323cc3ba72`（Slack / OpenMAIC） | 28 |
| `01a1d5a4-e589-7e52-8fdf-7430aa348ae7`（回应问候） | 17 |
| `01a1cf0e-7f57-7211-883a-0623cee6ab22`（将三个模型接入 Codex） | 11 |
| `01a1cf1a-1068-7cd0-8308-fabc3a42468e`（你好） | 1 |

合计 **57 轮 / 4 个会话**；当前 FTS 总规模为 **49,562 轮**（其中 Codex 57 行），
`indexed_files` 当前为 **495**（这 4 条 Codex 的 `fts_file_meta` 原本已存在，只是 `indexed_turns=0`；另 1 条为 0 轮 Doubao snapshot）。

**搜索验证（当前 18922）**：

| 查询 | 结果 |
|---|---|
| `Slack` | 30 条结果中 6 条来自 Codex |
| `AgentRouter Bridge` | 30 条结果中 2 条来自 Codex |
| `gpt-6.1-sol` | 30 条结果中 1 条来自 Codex |

详情验证：`/api/session/detail?catalog_id=bdffe6443fa54201` 返回 **466 events / 5 turns**；
`/api/sessions?format=codex` 返回 **4 条**；`/api/status` 中 `codex=4`。

**刷新同步**：`handle_catalog_refresh()` 在目录刷新完成后调用 `trigger_fts_sync()`，
异步补齐新会话的 FTS 索引，避免以后新增 Codex 会话必须重启服务。

**已知边界**：Codex 工具结果不入 FTS，这是与其它平台一致的降噪策略，不是缺失。
如果历史 `fts_file_meta` 已记录 mtime/size 但 `indexed_turns=0`，增量同步会跳过该文件；
本轮用 `F:\Agent会话记忆管理与迁移\.tmp\_rebuild_codex_fts.py` 强制重建过这 4 条。

### 4.8 平台筛选条：单行滚轮横向滚动（2026-11-17 10:03）

**用户现象**：新增 Codex 后，顶部平台 chip 在右侧被裁切，只剩「C…」；用户明确要求改成
**单行横向滚动，鼠标停在平台筛选位置滚动滚轮即可移动条目，不要换行**。

**最终实现**（`frontend/src/components/layout/Toolbar.tsx`）：

- chip 容器恢复单行：`flex items-center gap-1 overflow-x-auto no-scrollbar overscroll-x-contain flex-1 min-w-0`；
- 新增 `chipsRef`，用原生 `wheel` 监听（`{passive:false}`）把纵向 `deltaY` 转成 `scrollLeft`；
  触控板横向滑动仍交给浏览器原生滚动；没有溢出时直接返回，不拦截页面滚动；
- 不再使用 `flex-wrap`，平台再多也不会换行；滚动条隐藏，保留单行工具栏高度。

**构建与实测**：

- `npm run build` 成功，`frontend/out/index.html` 17,832 B，时间 `2026-11-17 10:03:17`；
- Browser Use 真实页面（967×883）验证：全部 487 / Antigravity 166 / Claude Code 84 / WorkBuddy 115 /
  Trae 95 / 豆包 23 / Codex 4 七个入口全部可见，Codex 不再是半个「C」；
- 点击 `Codex 4` 能正常筛出 4 条 Codex 会话，再点「全部」恢复 487 条；
- 强制把筛选区缩到 420px 做溢出测试：`clientWidth=420`、`scrollWidth=695`，
  向下滚轮 `deltaY=120` 后 `scrollLeft` 从 0 变为 120，确认滚轮横向移动生效。

**注意**：这是纯前端静态改动，`frontend/out` 更新后浏览器刷新即可；不需要重启 Python 服务。

### 4.9 检索弹窗：会话 / 消息分组（2026-11-17 14:48）

**用户需求**：按截图把“全文检索”改名为“检索”，删掉弹窗里的“跨会话对话内容检索”“已索引 49,562 轮历史对话”“支持跨平台、跨会话的中文全文检索”，并把结果按“会话”和“消息”分开；消息结果要带会话详情里的分类标签。

**实现**（`frontend/src/components/search/GlobalSearchModal.tsx`、`layout/Header.tsx`）：

- 顶部按钮文案改为“检索”，tooltip 改为“跨会话检索会话标题与消息内容”；弹窗 header 只保留“检索”，不再显示索引轮数副标题；
- 新增 `全部 / 会话 / 消息` 三个切换；`全部` 先显示“会话”组，再显示“消息”组；
- 会话组同时聚合两类结果：`/api/sessions?q=` 的标题/路径命中，以及 FTS 消息命中按 `catalog_id` 聚合出的会话；后者显示“匹配 N 条消息”，点击跳到首条命中轮次；
- 消息结果保留平台、轮次、时间、标题和 snippet，分类标签按 `role/kind` 映射：用户指令 / 回复 / 行动 / 思考；当前 FTS 只索引 user/assistant 正文，所以实际最常见的是“用户指令”和“回复”。

**验证**：

- `FTS5`：会话 7、消息 28，两组正常分开展示；
- `Recover`：会话 1、消息 32；点击会话卡可打开会话详情；
- 弹窗空状态显示“结果会按‘会话’和‘消息’分开显示”；`Esc` 可关闭；
- `npm run build` 成功，`frontend/out/index.html` 17,835 B，时间 `2026-11-17 14:48:14`；静态产物刷新即生效。

**状态口径提醒**：本次验证时页面显示 `全部 488`、`Trae 96`（Trae 侧新增了一条会话）；上文的 487 / Trae 95 是此前快照，不冲突。若要以当前数为准，重新跑 `/api/status` 即可。

### 4.10 Trae「最近活跃」排序修复（2026-11-17 17:18）

**用户现象**：Trae 筛选 + “最近活跃”排序时，真正最新的会话（2026-11-17 13:33，和“创建时间”最新的是同一条）沉在列表底部；顶部反而是 11-06 的旧会话。

**根因**：

1. `get_trae_sessions()` 里 `mtime = max(s["mtime"], agg["last_mtime"])`，而 `s["mtime"]` 被解密库文件的 mtime 抬高；同一 `trae_database_plain.db` 下所有会话拿到同一个文件时间。
2. `collect_all_sessions()` 又在拼装列表时无条件执行
   `t["mtime"] = t_path.stat().st_mtime`，把会话级时间覆盖成解密库文件 mtime。于是 96 条 Trae 的排序键几乎全等，顺序退化为枚举顺序。

**修复**：

- `get_trae_sessions()` 的 DB 段改为**优先使用会话自己的 `last_mtime`**，只有没有会话级时间时才回退到文件 mtime；
- `collect_all_sessions()` 只在 `t["mtime"] <= 0` 时才用文件 mtime，不再覆盖 Trae 的会话级时间；
- 对于没有解密库正文、也没有 `session_memory` 的 state.vscdb 会话（例如“Trae 工作区提问历史”），使用会话自己的 `started_at` 作为排序时间，避免同目录 state.vscdb 的文件时间把所有旧条目抬高。

**验证**：

- `/api/sessions?format=trae&sort_by=mtime&order=desc` 首条为 `trae_6afbdb305dc02999`，标题“完成蓝屏事故取证…”，`started_at=2026-11-17 13:33:19`；
- 页面实际刷新并点 `Trae 96` 后，首屏第一张卡就是该会话，后续按活跃时间递减；
- `Recover Lost Project Data` 因最后活跃时间为 `2026-11-14 17:06` 排在 `2026-11-12` 创建的其他卡之前，这是“最近活跃”而非“创建时间”的预期结果。

**当前口径**：`/api/status` 为 `total 851`（antigravity 166 / codex 4 / claude 84 / workbuddy 115 / trae 96 / doubao 386）。这是重启后重新扫描的现场数据；§4.9 里的 488 是更早快照。

**运维备注**：本次重启时 `dialogue_fts.sqlite3-wal` 被安全软件/残留句柄锁住，`SessionFTSManager` 自动切到同目录的 `dialogue_fts.recovered.sqlite3` 副本继续启动，FTS 检索仍正常（`FTS5` 查询 35 ms）。原始库和 WAL 未删除；锁释放后可回切或合并。

---

## 5. 遗留问题、已知缺陷与待处理事项

### 5.1 阻塞项

1. **`im.db` 密钥未取得** → 豆包正文仍不可读。已知三条路（见 §6.1）都未执行完。
2. **`resource.db` / `search_v2_5260_0000.db` / `suite_drive_cypher.db` / `common.db` 的密钥同样未取得**，且每个库独立。

### 5.2 已修正的错误结论（务必不要再引用旧说法）

| 旧说法 | 现状 |
|---|---|
| 「豆包本地库是空壳，没有正文」 | **错**。主文件只有 1 页，但写作时 WAL 里有 351 帧真实数据（当前 362 帧） |
| 「Trae 密钥不可从内存读到」 | **错**。以 `x'…'` 原始密钥形式存在于内存，且已截获 |
| 「Trae 页 IV 在 4080」 | **错**。Trae 的 IV 在 **4016**；豆包才在 4080（推断） |
| 「穷举 1,295 条口令即可解 Trae」 | **无效**。不是口令，不走 PBKDF2 |

### 5.3 接入侧的已知缺陷

1. **静态快照依赖**：`web_app.py` 读的是 `out\trae_database_plain.db`。Trae 仍在写库，**明文库不会自动更新**；要看到新会话必须重跑 `decrypt_trae.py`（`_trae_db_index()` 的缓存靠文件 mtime 失效，但前提是文件被重新生成）。
2. **首次列表慢**：冷启动第一次 `get_trae_sessions()` 要解析 32k 行 JSON（实测 4.87 s），之后走内存缓存。
3. **文本截断**：工具入参与输出各截 **6,000 字符**（`_trae_parse_messages()` / `_trae_tidy_tool_output()`）；如需完整输出，改这两处的 `[:6000]`。
4. **FTS 合成键**：`trae_db://<sid>` 不是真实路径，任何依赖「文件存在性」的下游逻辑（如导出、迁移）若直接拿 `file_path` 去 `stat`，会落到 734 MB 的数据库文件上——目前导出走 `get_trae_session_messages`，已验证可用，但**新增功能时须避开直接 stat**。
5. **`/api/status` 与 `/api/sessions` 总数差 5**：已随快照口径统一，当前两者均为 **487**，旧现象不再复现。
6. **Codex 索引边界**：只索引 `user` / `assistant` 正文，`tool_result` / `opaque` / `context` 不入 FTS；这是降噪策略，不是缺失。
7. **Codex 历史 meta 已存在但 0 轮**：增量同步会按 mtime/size 跳过，需用强制重建脚本补索引；新增 Codex 会话通常可由目录刷新后的 `trigger_fts_sync()` 处理。
8. **catalog 有 3 条 Claude missing**：`08950805-24f3-4cc6-b74f-1d02fe70f9c9`、`3a8919b1-0d95-4ff1-95c1-619431b0714c`、`fa9be28f-26b3-4b8c-9642-8ffd7c03f67c`；文件未删除、也不在删除清单，当前列表总数 487 已排除它们。若要恢复，先核对源文件是否被移动或删除。
9. **FTS 元数据多 1 条 0 轮 Doubao snapshot**：`fts_file_meta=495`，其中 `C:\Users\HP\AppData\Local\Doubao\User Data\coding\snapshot\...\091e97b8....json` 的 `indexed_turns=0`；不影响检索命中，但 `indexed_files` 统计会多 1，若要严格按“有效索引文件”统计需在同步器里排除无正文的 snapshot JSON。

### 5.4 敏感性处置（尚未与用户确认）

- `out\settings_plain.db` 内含 `access_token`（JWT）、设备与账号标识，**仅本地存在，未外发**。若后续要把该库纳入 Memory Tools 或导出，必须先脱敏（建议：只保留 `settings_fields` 中的非凭据键，或对 `access_token` 做列级剔除）。
- `tools\dbkey\_env15188.txt`（Trae 进程 6,050 条环境变量，含机器码）、`_trae_pass.txt`（Trae 原始密钥）、`_fa_out.txt`（命中日志）同理，勿外发。

### 5.5 删除审核线（尚未执行）

`docs\deletion-review-2026-11-17.md` / `.csv` 已列出待审核清单，当前**没有执行任何删除**：

- **A 类 44 条**：Trae 14、Antigravity 2、Claude 26、Codex 1 个会话（4 个文件副本）、WorkBuddy 1；
  这些源数据没有可恢复的助手正文，建议删除；
- **B 类 2 条**：Trae 工作区输入历史合成条目，不建议删源，只能在 Memory Tools 展示/索引层隐藏；
- 其余 418 条有助手正文，不在删除范围；豆包 23 条尚未接入，也未纳入。
- **执行限制**：Trae 14 条位于 733,925,376 B 的共享加密库，当前没有 SQLCipher 写入驱动；
  直接删 `database.db` 会毁掉同一库里的其他 79 条正常会话。B 2 条共享 `state.vscdb`，删源会丢工作区输入历史。
- 用户要求**先审核清单再删除**，且删除必须“完全删除不要有残留”；未得到明确批准前不得执行。

---

## 6. 后续工作项与关键注意事项

### 6.1 豆包正文：三条可选路径（按风险从低到高）

#### 路径 A：换用 `db-newkey-mark` 当**口令**再试（零风险，最先做）

此前只把它当「32 字节原始密钥」测过。它也可能是 SQLCipher 4 的**口令**（64 个 hex 字符的字符串）。用 `im.db` WAL 里最新 pg1 帧做判别，跑常见 KDF：

- `sha256 / 256000`、`sha512 / 256000`、`sha1 / 64000`、`sha256 / 1`
- 判别式：`AES256-ECB_dec(ct[16:32]) XOR IV(4080..4096) == b"SQLite format 3\0"`

若命中，按 §3.2.2 的布局解整库，再合并 WAL（参考 `tools\dbkey\merge_wal.py` 的帧合并逻辑）。

#### 路径 B：静态还原密钥派生（中等成本，需逆向）

- 用 REA（`F:\skills\reverse-engineer-anything`，或已装的 Ghidra/IDA）打开 `F:\Doubao\app\liblark.dll`，定位引用 `.rdata:0x883d950`（`PRAGMA key` 字面量）的函数；
- 依据 `db-newkey`（`0x859e768`）、`cipher_migrate`（`0x9306ce8`）、`sqlcipher`（`0x9306c00`）三处字符串的邻近引用，找密钥装载/迁移逻辑；
- 目标：搞清楚密钥是「文件读取」「DPAPI 解密」还是「由 access_token / 机器码派生」。若为文件，直接读；若为 DPAPI，用同用户上下文解。

> 本机无 `git` 命令（PATH 里没有），逆向工具请先确认可用性，不要假设 `npx` 一定在线。

#### 路径 C：挂钩 `liblark.dll` 抓 `PRAGMA key`（收益最高，但**有风险**）

- 断点地址：`liblark.dll` **RVA `0x883d950`**；PID 7492 当时的基址 `0x7fffd0560000` + RVA = `0x7fffd8d9d950`。当前已重启为 PID 22508，**基址变了，必须用 Toolhelp 快照重新取基址**，不要硬编码旧 VA。
- 方法完全照抄 `tools\dbkey\fast_attach.py`（挂接 + 1 字节读写断点 + TF 单步 + **每步重设 TF** + 10 寄存器扫描）
- **风险**：当前豆包主进程是 **PID 22508（原 7492 已退出）**，挂钩期间所有线程被冻结；若 harness 出错会导致客户端假死（等于中断用户当前会话）。必须：
  1. 只在用户明确同意的时间窗内做；
  2. 失败/超时立即 `DebugActiveProcessStop` 干净脱离；
  3. 不要在挂钩期间杀进程；
  4. 优先等**自然重连**（用户执行一次豆包内搜索 → `search_v2` 新建连接 → 同一处 `PRAGMA key` 必然再执行），不要主动杀当前主进程。

### 6.2 Trae 侧收尾（低风险）

1. **交叉校验** `docs\trae-memory-export.md`（明文记忆层 104 条 / 34 文件）与解密库 93 会话的时间、话题是否对得上；两者是不同层（记忆摘要 vs 完整对话），条数本就不等，只需说明差异来源。
2. **刷新机制**：若要长期可用，建议把 `decrypt_trae.py` 做成「检测 `database.db` mtime 变化 → 增量重解」的任务（当前是手工）。
3. **导出功能验证**：`/api/session/migrate` 对 `trae_db://` 合成键的兼容性尚未端到端跑过一次（列表/详情/搜索已验证）。

### 6.3 行为红线（用户已明确要求）

1. **禁止 GUI 自动化**：不得使用 `computer_use_tool` / `switch_desktop("main")`。上次执行导致用户系统会话被切到后台、豆包等应用登出、被迫重启。本轮全程只用调试器挂接与只读内存。
2. **不碰 CUDA**：用户明确「不建议做的不做」。本任务瓶颈在取密钥，不在算力。
3. **不啃没有明文页的库**：没有可验证判据的库不要盲试。
4. **不动豆包主进程**（写作时 PID 7492，当前 PID **22508**）：见 §6.1 路径 C。
5. **不重启 Trae 主进程**：会改变 `harness.dll` 运行时基址，已记录的 `0x7fff93460449` 需要重新计算（基址变了，RVA 不变）。
6. **敏感数据不外发**：见 §5.4。
7. **进程操作必须先过门禁**：任何 `Stop-Process` / `taskkill` 前后都要跑 `tools\safe_process_ops.ps1`（Baseline + Preview），禁止对 `csrss` / `wininit` / `services` / `lsass` / `smss` / `svchost` / `dwm` / `explorer` 等出手；详见 §7.3。

### 6.4 关键常量速查

```
Trae
  库      C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db
  密钥    3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773   (x'…' 原始密钥)
  salt    81d071c4bc55cd26681ee72bfdce3bdf
  布局    [salt16][ct][IV@4016][HMAC 4032..4096]，reserve 80
  明文库  F:\Agent会话记忆管理与迁移\tools\dbkey\out\trae_database_plain.db

Trae harness.dll
  文件    D:\Trae CN\resources\app\modules\ai-agent\harness.dll（263.77 MB，ImageBase 0x180000000）
  字面量  PRAGMA key =  RVA 0xb620449（本轮运行时 VA 0x7fff93460449，基址 0x7fff93460000）

豆包
  库目录  C:\Users\HP\AppData\Local\Doubao\User Data\sdk_storage\e4f7b54c6016831d50c70684aeaef4ff
  持库    当前 PID 22508（父 20968，2026-11-17 09:31:39 启动）；写作时 PID 7492（父 32944，已退出）
  im.db   写作时 salt 2da964e5600a7df44ef1b1e4057c7009，WAL 351 帧 / 11 个 pg1；
          当前 salt bbcaa2fa94bed157，WAL 1,491,472 B / 362 帧 / 12 个 pg1
  已知钥  messages 3b9cb6b2a66e7ce0f4d8bfd708b31b27899e61cea6db28b02b4d81f45e7af351
          settings 3df0a9d48e75fa6fcd609eb5c41f5e0c6fcd46795213c33c6644a13b2517a893
          db-newkey-mark a8acce378382de8165cb2764797698f0f4ed93ce2dcb939afb6eeafb56d7fdca（性质未定）
  封装库  F:\Doubao\app\liblark.dll（188,221,840 B，ImageBase 0x180000000）
          PRAGMA key 字面量 RVA 0x883d950；写作时 PID 7492 基址 0x7fffd0560000 → VA 0x7fffd8d9d950（当前 PID 22508 需重新取基址）
  布局    [salt16][ct4000][HMAC 4016..4080][IV 4080..4096]（推断，待明文校验）
```

### 6.5 复现命令（PowerShell）

```powershell
# 1) 解 Trae 整库（约 1 分钟，8 进程）
cd "F:\Agent会话记忆管理与迁移\tools\dbkey"
python decrypt_trae.py

# 2) 重新导出正文（生成 out\trae_history_v2.jsonl 与 docs\trae-db-export.md）
python export_history.py

# 3) 验证原始密钥与页布局（需 Trae 正在运行才有内存明文可比）
python verify_rawkey.py 3605f6691095a993f03d5009c918352ef5be31ae31e8f000212b81ff058da773

# 4) 起 Memory Tools 验证接入（另开端口，不干扰默认 18922）
cd "F:\Agent会话记忆管理与迁移"
$env:MEMORY_TOOLS_PORT="18999"; .\.venv\Scripts\python.exe web_app.py --no-browser
# 另开一个窗口：
# Invoke-WebRequest "http://127.0.0.1:18999/api/status" -UseBasicParsing
# Invoke-WebRequest "http://127.0.0.1:18999/api/session/detail?catalog_id=trae_6a8a61cf9172cf7d" -UseBasicParsing

# 5) Codex FTS 验证（当前 18922）
# Invoke-WebRequest "http://127.0.0.1:18922/api/sessions?format=codex" -UseBasicParsing
# Invoke-WebRequest "http://127.0.0.1:18922/api/session/detail?catalog_id=bdffe6443fa54201" -UseBasicParsing
# Invoke-WebRequest "http://127.0.0.1:18922/api/search/content?q=Slack&limit=30" -UseBasicParsing
```

### 6.6 交付验收清单（接手方按此逐项确认）

- [ ] `tools\dbkey\out\trae_database_plain.db` 存在且 733,925,376 B，`sqlite3` 能查 `history_v2` 32,014 行
- [ ] `tools\dbkey\out\trae_history_v2.jsonl` 111,181,168 B，可逐行 JSON 解析
- [ ] `web_app.py` 里 `_trae_db_index` / `_trae_db_messages` / `TRAE_PLAIN_DB` 存在，`get_trae_sessions()` 含「2.5」段
- [ ] `/api/sessions` 返回 trae 95 条，`/api/session/detail` 对一个 `trae_` 开头的 `catalog_id` 能出 7k 级事件
- [ ] `/api/search/content?q=Bio-Panorama` 能返回 `session_format=trae` 的命中
- [ ] `/api/status` 返回 487，`format_counts` = Antigravity 166 / Claude 84 / Codex 4 / WorkBuddy 115 / Trae 95 / 豆包 23（合计 487）
- [ ] `/api/sessions?format=codex` 返回 4 条；`/api/session/detail?catalog_id=bdffe6443fa54201` 返回 466 events / 5 turns
- [ ] `conversation_fts` 中 `session_format='codex'` 为 57 行；全库 `count=49,562`、`conversation_fts_docsize=49,562`、`fts_file_meta=495`（含 1 条 0 轮 Doubao snapshot）
- [ ] 平台筛选条为单行横向滚动：在溢出宽度下滚轮能让 `scrollLeft` 增加；Codex 可点击筛选
- [ ] `docs\deletion-review-2026-11-17.md` / `.csv` 的 A 44 + B 2 仍为未执行状态
- [ ] `tools\dbkey\README.md` 7.4 / 7.5 历史事实与 **§8 2026-11-17 复核补记**一致（PID 22508 / WAL 362 帧）
- [ ] 豆包 `im.db` 仍未解开（若接手方已解开，需回填 §3.2.2 的布局为「已验证」并更新 §5.3）

---

## 7. 2026-11-17 蓝屏事故与恢复核查

### 7.1 事故时间线（实测）

| 时间 | 事件 | 证据 |
|---|---|---|
| 12:47:33 | Trae `NetworkService` 崩溃 | `Crashpad\reports\block_2026.11.17-12.47.33(NetworkService.6142).dmp`（1,470,368 B，写入时间 12:47:34） |
| 12:47 之后 | 系统蓝屏 **CRITICAL_PROCESS_DIED (0xEF)** | `C:\Windows\Minidump\111726-21656-01.dmp`（6,448,334 B，PAGEDU64，v15.26100）；WER `Kernel_ef_...` 报告 |
| 13:29:04 | 重启 | `Win32_OperatingSystem.LastBootUpTime` |
| 13:29:30 | 记录 BugCheck 1001 | p1=p3=`0xffffe48dabec6140`、p2=p4=0 |
| 13:40:56 | Trae 渲染进程再次崩溃 | `main.log`：`CodeWindow: renderer process gone (reason: crashed, code: -36863)` |
| 13:44:12 | Trae 自动重建窗口 | 新日志目录 `20261117T134413`，当前 16 个 Trae 进程 |

> **更正 EventLog 的 12:25:26**：6008 里的「上一次关闭时间」是最后一次正常落盘时间，不是崩溃时刻；Crashpad 在 12:47:34 仍写入，说明蓝屏发生在 12:47 之后。

### 7.2 根因线索与边界

- dump 内字符串以 `wificloudstore.dll`（ASCII 576 / UTF16 285）、`wlansvc.dll`（255 / 124）、`networkicon.dll`（106）为主，另有 `microsoft.windows.shell.sys`、`vmswitch.sys`、`wintun.sys`、`lxss.sys/lxcore.sys` 等；**指向 WLAN AutoConfig 服务栈**。
- 0xEF 表示「关键系统进程死亡」；dump 能证明死亡现场与 WLAN 栈相关，但**不能唯一归因**（也可能是驱动/安全软件写入内存导致）。
- 与本项目的关系：事故前后本轮只执行了文件读取、Python 解析、`Get-CimInstance`/`Get-WinEvent` 等只读操作，**未执行任何 `Stop-Process` / `taskkill` / `DebugActiveProcess`**；无证据表明是本项目命令直接杀进程。
- Trae 13:40 的渲染进程崩溃属应用层（无 WER Error、无 TDR/Display 事件），与 12:47 蓝屏不是同一事件。

### 7.3 恢复核查（13:33–13:50，全部通过）

- 关键进程：`csrss` 2 / `wininit` 1 / `services` 1 / `lsass` 1 / `smss` 1 / `winlogon` 1 / `svchost` 94 / `explorer` 1 / `dwm` 1。
- 磁盘：SK hynix SSD / Lenovo LD01 / USB 均 `Healthy`；C 盘剩余 12.8 GB / 164.6 GB。
- `tools\dbkey\out\trae_database_plain.db` 733,925,376 B，`integrity_check=ok`，67 表，`history_v2` 32,014 行。
- `out\trae_history_v2.jsonl` 111,181,168 B，32,014 行，解析 0 坏行。
- FTS：`C:\Users\HP\.local\state\session-migrate\dialogue_fts.sqlite3` 149,876,736 B，`integrity_check=ok`，49,562 行 / `docsize` 49,562 / `fts_file_meta` 495（codex 57）。
- `catalog.sqlite3` `integrity_check=ok`（262 sessions）；`settings_plain.db` + WAL 合并副本 `integrity_check=ok`（`settings_fields` 1,796）。
- 豆包 WAL 结构：`im` 362 帧 / `resource` 145 / `search_v2` 684 / `suite_drive` 30 / `settings` 1,221 / `common` 939，页大小 4096，头版本 3007000。
- **结论：未发现需要修复的数据损坏**。`F:\Agent会话记忆管理与迁移\dialogue_fts.sqlite3` 是 0 字节历史误建文件，真实 FTS 在 `.local\state`，未删除。

### 7.4 新增进程操作门禁

`tools\safe_process_ops.ps1`（Baseline / Preview / Stop 三档）：

- 受保护名单：`System/Registry/Memory Compression/smss/csrss/wininit/services/lsass/winlogon/svchost/dwm/explorer/fontdrvhost/spoolsv/MsMpEng/...`；
- `Session 0`、当前 Shell 祖先链、父进程为 `services.exe/wininit.exe/csrss.exe/smss.exe` 的目标一律拒绝；
- `Doubao.exe` / `Trae CN.exe` / `web_app.py` 属业务进程，需 `-AllowAppTarget` 才进入终止流程；
- 默认 `Preview` 只打印，`Stop` 才执行，全部写入 `logs\process_ops.log`。

自检结果：`Baseline` exit 0；`Preview -Id <svchost>` 拒绝 exit 2；`Preview -Id <python>` 仅预览 exit 0。

### 7.5 豆包密钥：本轮静态新进展（2026-11-17 下午，未解开仍阻塞）

**新增证据（全部来自 `liblark.dll` / 明文配置，未挂钩）**

| 项 | 内容 |
|---|---|
| 换钥模块 | `lark-biz-upgrade\src\rekey.rs`：`db-newkey-mark` / `rekey-wip` / `rekey-done` / `apply done dir: ` |
| 密钥模块 | `lark-share\src\db\encryption_key\native.rs`：`use db key: kind=legacy` / `kind=new`、`app secret not init`、`app secret not found`、`device_factor`、`get device_factor from file/cache`、`device factor file not exists, use device id`、`save device_factor failed` |
| 初始化校验 | `lark-share\src\db\init_key_check\native.rs`：`init_key_changed`、`last_init_key_encode`、`this_init_key_encode`、`use_new_key` |
| 密钥落点 | `PRAGMA key = ` 字面量 RVA `0x883d950`；构造函数 RVA `0x2185a80`（VA `0x182185a80`，1828 B），在 VA `0x182185b45` 处 `lea r9, "PRAGMA key = "` 后 `format!` 拼接 |
| 密钥形态 | 同模块出现 `x"` 与 `'` 两个格式片段 → 即 `PRAGMA key = "x'<hex>'"`（SQLCipher raw key，待运行时确认） |
| 设备身份 | `User Data\Local State → aha.device`：`device_id=1141719210406352`、`install_id=1518893134049498`、`pc_uuid=FA0C9F07-0BD8-ED11-8C91-7C4D8FB7F7B0`、`pc_serial=ACE4_2E00_3A1D_B892_2EE4_AC00_0000_0001.`、`mac=0A:00:27:00:00:0F` |
| device_factor | 全盘不存在该文件 → 按代码走「use device id」回退 |

**本轮新增失败尝试（勿重跑）**

- 32 个设备派生候选（sha256 / sha256×2 / md5×2 / 补零 / 补空格 / 字段组合）→ `im.db` WAL pg1 四档 IV 全不通；
- 14 组口令 × PBKDF2（sha512·256000、sha256·256000、sha1·64000、sha512·1、sha256·1）→ 全不通；
- `db-newkey-mark` 当 raw key（四档 IV）与当口令（5 组 KDF）→ 复测仍失败；
- 豆包 `sdk_storage\log\monitor\pending\*.dmp` 共 36 个文件全部 0 字节，无法从崩溃转储取内存残留。

**结论与下一步**

- app secret 由 `device_factor`（缺失时回退 device id）参与派生，或由宿主经 FFI 注入；静态推导尚未闭环。
- 唯一稳妥路径仍是运行时挂钩，且**必须先有用户授权窗口**：
  1. 主目标：`liblark.dll` 的 `PRAGMA key` 字面量（RVA `0x883d950`），用 Toolhelp 重取基址；
  2. 备选（更稳）：`codec_set_pass_key`（字符串 `codec_set_pass_key: db=%p nDb=%d for_ctx=%d` 的引用函数）入口，直接抓 key 参数；
  3. 挂钩期间冻结目标线程，失败/超时立即 `DebugActiveProcessStop`，不杀进程。
- 当前豆包**未运行**（13:33 复核无 Doubao 进程），挂钩需先由用户启动并保持登录。

### 7.6 运行时挂钩实测（2026-11-17 14:00–14:35）

| 尝试 | 目标 | 结果 |
|---|---|---|
| 字面量断点（4 分钟窗） | `PRAGMA key = ` RVA `0x883d950`，PID 21236 | 0 命中（`dst=None`） |
| 字面量断点（15 分钟窗） | 同上；期间用户执行搜索 + 发消息 | 0 命中 |
| 页解密断点（3 分钟 + 10 分钟窗） | `sqlcipher_page_cipher` RVA `0x8136e50`（`liblark` 基址 `0x7ffa6fcc0000` → VA `0x7ffa77df6e50`） | 0 命中；62 线程布点成功 |

- 函数校验：运行时入口字节与文件一致（`48895c2410…`），无热补丁；`.pdata` 范围 `0x8136e50–0x8137156`，含 `pgno=%d, mode=%d, size=%d` 日志串；直接调用点 2 处（`0x814206b`、`0x81420fc`）。
- **关键证据**：14:20–14:33 用户浏览会话/搜索期间，`im.db-shm`、`search_v2_5260_0000.db-shm`、`settings.db-shm` 的 mtime 仍为 13:52–13:57（启动时），说明**本地库没有发生读写**，页面解密自然不发生；豆包聊天内容走内存/云端，本地 SQLCipher 主要在登录/同步阶段使用。
- 内存定位：PID 21236 可读内存 752 MB，`im.db` salt 仅 1 处（堆内，非页映射）；全内存 22 个 64hex 候选按 raw key + 5 组 PBKDF2 测试均不命中；salt ±8 KB 滑窗（1 字节步进）无命中。
- 附带发现：结束调试器进程时，豆包后端工具进程（`backend.mojom.Service`）自行退出并被 Chromium 重建（PID 21236 → 14980），主进程与登录态不受影响、WAL 完好；这证明「重启后端」是可恢复操作。
- **下一步（需用户授权）**：让后端工具进程重启一次，同时用 `fast_attach.py` 的新进程模式在 `liblark.dll` 加载瞬间挂 `PRAGMA key = ` 字面量，捕捉启动期的建连密钥。命令：
  ```powershell
  $env:FA_TARGET_EXE="Doubao.exe"; $env:FA_TARGET_MODULE="liblark.dll"; $env:FA_LITERAL_RVA="0x883d950"
  $env:FA_WINDOW="120"; $env:FA_FOUND_FILE="_doubao_pragma.txt"
  python fast_attach.py 300
  ```
  随后由门禁脚本 `-AllowAppTarget` 结束后端进程（非主进程），等待新进程自动重建并命中。

### 7.7 结论修正：当前豆包聊天走**明文 IndexedDB**，加密库未被 UI 使用

- 实测证据（2026-11-17 14:52–14:58，用户执行打开会话/搜索/发消息）：
  - `Profile 1\IndexedDB\chrome_doubao-chat_0.indexeddb.leveldb\000918.log` **14:57:49 仍在写入**，`000919.ldb` 14:57:43 生成；
  - 同期 `im.db-shm` / `settings.db-shm` / `search_v2_...-shm` 的 mtime 仍停在 **13:52–13:57**（应用启动时），之后再无读写。
- 后端工具进程被重启三次（21236 → 33880 → 21516），均由 Chromium 自动重建、主进程与登录态不受影响；每次新进程都**没有打开** `im.db`，页解密函数 `sqlcipher_page_cipher` 也从未被调用。
- 用现成解析器 `_doubao_iter_idb_blobs` / `_doubao_extract_idb_sessions` 解析明文层：**8,988 个值 / 18.5 MB**，提取到 **20 个会话标题**，例如：
  - `38454148418383362` 会话文件读取与整理及工具数据库读取任务
  - `38454331341682434` 股票投资方法论研究与应用
  - `38454078978586370` 功能测试与修改
  - `38454088512036098` 生科联赛时间
  - `38454138949668098` 熟茶叶蛋能否过夜
- IndexedDB 结构：`conversation-list-data-overall-v2`（会话元数据）、`mainTaskDataMap`（任务状态，单条约 200 KB）、少量 `text_block` / `content_block` / `message_id`（24 个 blob）。
- **判断**：`im.db` 更像 Lark SDK 的旧 IM 同步库（WAL 最后写入 11-13 / 13:52），不是当前豆包聊天的主存储；继续攻该库密钥对「聊天正文」收益很低。
- **建议**：豆包接入改为以明文 IndexedDB/LevelDB 为主源；现有 `get_doubao_sessions()` 已能读该层，可扩展把 20 个会话标题与 `mainTaskDataMap` 中的缓存消息并入列表/详情/检索。本轮已把结果落到 `.tmp\doubao_idb_sessions.json`。

### 7.8 IndexedDB 自定义序列化格式（已逆向，可复用）

**编码**：`[varint 字段名长度][字段名][类型字节][值]`，无分隔符；对象内字段连续排列。

| 类型字节 | 含义 | 值编码 |
|---|---|---|
| `0x22` | UTF-8 字符串 | varint 长度 + 字节 |
| `0x63` | UTF-16LE 字符串 | varint 长度 + 字节 |
| `0x49` | 整数 | varint |
| `0x4e` | 浮点/时间戳 | 8 字节 LE double |
| `0x41` | 数组 | varint 元素数 + 元素 |
| `0x6f` | 对象 | 后接 `0x22`，再连续字段 |
| `0x46` / `0x54` | false / true | 无 |
| `0x5f` | null | 视上下文 |

**关键字段**：`conversation_id`、`local_message_id`、`message_from`（`"InputBox"` 或整数 0 表示用户）、`block_type`、`text_block` → `text`、`summary`、`is_finish`、`createTime`。

**已提取**（`.tmp\doubao_idb_messages.json`）：

- 有标题的会话 **20** 个；其中 `mainTaskDataMap` 里带正文的 **2** 个（共 4 条、302 字）：
  - `261647035677698` 豆包：`你能做些什么？` + 助手长回复（生信/实验方向整理）
  - `38454148418383362` 会话文件读取与整理及工具数据库读取任务：搜索弹窗改造的用户需求 + 助手首条回复
- **限制**：`mainTaskDataMap` 只保存**当前任务状态**（请求 + 本轮响应块），不是完整历史；完整会话在云端，本地 IndexedDB 只有最近一次任务与列表元数据。
- **下一步**：扩展 `get_doubao_sessions()`：把 20 个标题、`doubao_idb_messages.json` 中的正文并入豆包来源的列表/详情；角色判定需继续区分任务态里重复的请求文本（当前启发式会把助手回复误标为 `InputBox`）。

### 7.9 已接入 Memory Tools（2026-11-17 15:xx）

**新增模块** `services/doubao_idb.py`（可复用解析层）：

- `leveldb_dirs(User Data)`：匹配所有 `*/IndexedDB/chrome_doubao-chat_0.indexeddb.leveldb`（Default / Profile 1 …）；
- `snappy_decompress` / `read_varint` / `_iter_values`：LevelDB `.ldb` + `.log` 读取与 Snappy 解压；
- `load(User Data)`：按全部 LevelDB 文件的 `(mtime_ns,size)` 生成签名并缓存，**文件一变就重解析**；
- 返回 `{cid: {title, ts, messages:[{role,text}], dir}}`；角色规则：任务态**首条文本=user、其余合并=assistant**。

**web_app 改动**：

1. `get_doubao_sessions()`：不再只扫 `Default`，改为遍历所有 profile 的 IDB；同 `session_id` 与 Agent Mode / Coding Snapshot 冲突时，按**正文字节数**保留更丰富的一份；
2. `get_doubao_session_messages()`：新增 `source_kind == "indexeddb"` 分支，直接返回 user/assistant 事件，缺失时回退 `cached_msgs`；
3. `_sessions_fingerprint()`：纳入所有豆包 IDB 目录的文件签名 → 聊天过程中 LevelDB 写入即触发快照重建（**热更新**，无需重启服务）。

**实测**：

- `get_doubao_sessions()` 豆包会话 **42** 条（原 23），其中 IndexedDB 来源 **34** 条、带正文 **2** 条；
- `db_261647035677698`（标题「豆包」）详情 **2 events**：用户 `你能做些什么？` + 助手生信/实验长回复；
- 缓存：第二次 `doubao_idb.load()` **1.7 ms**；伪造 leveldb 文件 mtime 变化后签名改变（热更新用例通过）；
- 语法：`ast.parse` 通过。

### 7.10 豆包正文纳入 FTS（2026-11-17 15:2x）

**改动**（`web_app.py` 的 `_run_fts_sync_worker`）：

1. 通用文件循环里跳过 `source_kind == "indexeddb"`（一个目录承载多个会话，不能按路径索引）；
2. 新增 **2c 段**：`doubao_idb.load()` 取全部会话，按合成键 `doubao_idb://<cid>`、`catalog_id=db_<cid[:16]>` 建索引；`session_format="doubao"`，标题为空时回退 `豆包对话 (后 8 位)`；
3. 每个会话的 user / assistant 文本逐条写入，`turn_index` 按用户消息计数；
4. 同步末尾清理已消失会话的旧索引（`fts_file_meta` 中 `doubao_idb://%` 且不在当前集合的）；
5. 快照 builder 改为 `_build_snapshot_items()`：每次快照重建后自动 `trigger_fts_sync()`。豆包 IndexedDB 写入 → 指纹变化 → 快照重建 → 增量 FTS 同步，实现**检索热更新**（无需重启服务）。

**验证**：

- `conversation_fts`：豆包 **7 行 / 4 个会话**；全库 **49,524** 行（workbuddy 30,904 / trae 15,162 / antigravity 2,789 / claude 605 / codex 57 / doubao 7）；
- `/api/search/content?q=搜索` 命中 `db_3845414841838336`（标题「会话文件读取与整理及工具数据库读取任务」）；
- `/api/status`：doubao **42**；
- 说明：`你能做些什么` 这类逐字长短语在现有 CJK 分词下所有平台都 0 命中，不是豆包特例；短词（如「搜索」）可正常命中。
- Trae 行数由 15,221 → 15,162，是本次重扫后的正常漂移（源库仍在更新），不是丢失。

### 7.11 正文缺失与事件分类修正（2026-11-17 15:3x）

**实测结论**：42 个豆包会话中 **31 个只有标题、没有本地正文**——这些会话的 blob 里 `text_block` / `content_block` / `message_id` 均为 0，只有 `conversation-list-data-*` 元数据；完整对话保存在云端，本地不缓存。

**改动**：

1. `services/doubao_idb.py::_parse_tasks`：同时抽取文本块与 `file_operation_block -> file_name`，按字节位置排序；首条文本=用户，其余=助手，文件动作=`tool_call`（`tool_name="文件操作"`）；
2. `get_doubao_session_messages()`：`indexeddb` 分支透传 `kind`/`tool_name`；**无本地正文时返回一条明确提示**（“本地未缓存该会话正文…完整对话保存在云端”），不再空白；
3. 同 cid 与 Coding Snapshot 冲突时：**IDB 有真实对话就以 IDB 为准**（Coding Snapshot 只是产物摘要），不再按字节数比较。

**验证**：

- `db_3845414841838336`（会话文件读取与整理…）详情 **9 events**：1 条用户指令 + 1 条助手回复 + 7 条「文件操作」动作（`frontend/src/...`、`web_app.py`、`services/snapshot.py` 等）；
- 空会话 `db_3845028382378649` 详情返回 **1 条提示事件**，不再空白；
- FTS 只索引 `kind=="message"` 的人话正文，动作不进入检索，避免路径噪声。

### 7.12 豆包云端会话已打通并接入 Memory Tools（2026-11-17 15:40–16:10）

**结论**：豆包桌面端的完整正文确实在云端。用本机已登录的 Chromium Cookie 调用豆包自身的**只读**接口，已拉全 **365 个会话**（本地 IndexedDB 只有 38 个元数据），并接入 Memory Tools 的列表 / 详情 / FTS。

#### 7.12.1 接口（实测可用）

| 用途 | 方法 | 路径 | 参数 |
|---|---|---|---|
| 会话列表 | POST | `/samantha/im/conversation/list` | query: `conversation_types=3&cursor=<next_cursor>&batch_size=20`；body `{}` |
| 消息正文 | POST | `/alice/message/index_list` | body `{conversation_id, message_index_list, is_reverse:true}` |
| 会话元数据 | POST | `/samantha/im/conversation/basic_info` | body `{conversation_id}` |

公共 query 参数（缺一不可）：`aid=582478`、`real_aid=582478`、`device_platform=web`、`doubao_device_platform=desktop`、`pkg_type=release_version`、`version_code=20800`、`update_version_code=20800`、`pc_version=2.36.8`、`language=zh`、`region=CN`、`device_id=1141719210406352`、`web_platform=browser`、`samantha_web=1`、`use-olympus-account=1`。请求头 `Content-Type: application/json; charset=utf-8`，并携带豆包 Cookie。

**关键限制**：`index_list` 单次最多 **40** 个 index，超过返回 `710010202`；会话列表用 `next_cursor` 翻页，实测 19 页共 365 个。

#### 7.12.2 Cookie 解密（v10）

1. `User Data\Local State → os_crypt.encrypted_key` 是 DPAPI 包裹的 32 字节 AES-256-GCM 密钥（前缀 `DPAPI`）；
2. `User Data\<profile>\Network\Cookies` 的 `encrypted_value` 为 `v10`：`3 字节前缀 + 12 字节 nonce + 密文 + 16 字节 tag`；
3. 明文前 **32 字节是 host_key 指纹**（Chromium 127+），必须剥离后才是 Cookie 值；
4. 浏览器独占锁定 Cookie 库时，用 `Win32_ShadowCopy.Create('C:\\','ClientAccessible')` 卷影只读复制，读完立即 `Remove-CimInstance`；
5. 解密结果缓存到 `cache/doubao_cloud/.cookies.json`（TTL 6 小时，已在 `.gitignore` 中排除，严禁外发）。

#### 7.12.3 新增代码与产物

- `tools/doubao_sync.py`：同步器。`--full` 全量、`--only <cid>` 单会话、`--limit N`、`--concurrency N`、`--rebuild-manifest`（中断后用已落盘 JSON 重建清单）。
- `services/doubao_cloud.py`：按 `(文件数, 最新 mtime_ns, 总大小)` 签名做缓存的热加载层，供 web_app 消费。
- `cache/doubao_cloud/conversations/<cid>.json`：
  ```json
  {"cid":"...","title":"...","ts":1794...,"message_index":159,"message_cursor":1,
   "messages":[{"kind":"message|tool_call","role":"user|assistant","tool_name":"","text":"...","ts":1794...}]}
  ```
- `cache/doubao_cloud/manifest.json`：每个会话的 `message_index/message_cursor/update_time`，用于增量跳过。

#### 7.12.4 Memory Tools 接入点（web_app.py）

- `get_doubao_sessions()` 新增 **第 4 段**：先加载云端仓，`source_kind="cloud"`、`mode="chat_cloud"`；同 cid 已在云端时 IndexedDB 段直接跳过，避免重复。
- `get_doubao_session_messages()` 新增 `cloud` 分支：按事件 `ts` 生成时间戳，保留 `kind/role/tool_name`。
- FTS 新增 **2d 段**：合成键 `doubao_cloud://<cid>`，`catalog_id=db_<cid[:16]>`；主循环与 2c 均跳过云端覆盖的会话，避免 `index_session_turns` 按 catalog_id 删除已有行。
- 自动同步：首次构建快照时，若 `cache/doubao_cloud/.cookies.json` 存在且距 `manifest.synced_at` 超过 6 小时，后台增量同步一次；`POST /api/doubao/sync` 手动触发，`GET /api/doubao/sync/status` 查询进度。
- `_sessions_fingerprint()` 混入云端仓签名，同步写入后列表快照自动失效并触发 FTS。

#### 7.12.5 验证数据（实测）

- `/api/status`：`doubao=386`（云端 364 + 本地 IDB 18 + Agent 2 + 工作区 2；另有 1 个空会话「新对话」与 4 个被云端覆盖的 Coding 快照已自动合并去重）；`total_sessions=851`。
- 云端会话 `db_3845433416328806`（Java监听器实现方法）：详情 2 events，用户提问 + 完整 Java 长回答。
- 云端大体量会话 `38454148418383362`：**846 events**（27 user / 238 assistant / 581 tool_call），文件 255 KB。
- 慢会话 `db_1887008407828787`（电子词典）：**144 events**，详情与检索均可用。
- FTS：`doubao_cloud://` 364 条、`session_format='doubao'` 10,333 行；`q=同一个事件源可以绑定多个监听器`、`q=四六级考试频率` 均能命中对应云端正文。
- 热更新：touch 单个会话 JSON 后调用 `/api/catalog/refresh`，该会话的 `fts_file_meta.mtime` 与 144 turns 自动重建，无需重启服务。

#### 7.12.6 边界与注意事项

- 全程只读：不修改豆包任何数据，不做 GUI 自动化，不注入/挂钩豆包进程。
- Cookie 过期（约 30 天）后需重新读取；服务以非管理员运行时无法建卷影副本，只能沿用 6 小时缓存，缓存也失效时同步会失败并保留旧数据。
- 云端接口字段随版本可能变化；若 `latest_messagelist` / `index_list` 失效，优先从 `F:\Doubao\app\local_webcontents` 的 JS 包重新提取路径与参数。

---

## 附录 A：本轮踩坑与经验（避免重复劳动）

1. **`EnumProcesses` 在 `psapi.dll`**，`kernel32` 里没有；写错直接 `AttributeError`。
2. **`DEBUG_EVENT` 联合体偏移 16**（x64），按 12 解析会让异常码恒 0，硬件断点事件全部被当噪声丢弃。
3. **TF 单步必须逐条重设**：CPU 进入异常自动清 TF，不重设只走一步。
4. **不要只盯 `rcx`**：Rust `String` 会 realloc，成品串在别的寄存器（本次 `0xb8`）。
5. **不要只按文件大小判断库是否为空**：WAL 模式下主文件可能只有 1 页。
6. **`PRAGMA key` 有两种形态**：`"口令"`（走 PBKDF2）与 `x'64hex'`（原始密钥）。先分辨形态，再决定要不要穷举 KDF。
7. **`psapi.EnumProcessModulesEx` 对 Trae 进程返回 299**（不可用），要用 Toolhelp 快照或 `EnumProcesses`。
8. **`state.vscdb` / `input_history` 只能拿到提问残片**，Trae 的 assistant 正文只在 `history_v2` 里。

## 附录 B：当前环境事实

- 主机 `WILLIAM`（Windows，PowerShell；**PATH 里没有 `git`**）
- 项目 `F:\Agent会话记忆管理与迁移`，虚拟环境 `.venv`（Python 3.14.5，`F:\uv\python\cpython-3.14-windows-x86_64-none\python.exe`）
- Memory Tools 默认端口 18922，可用 `MEMORY_TOOLS_PORT` 覆盖
- Trae 版本 3.4.18（`ICUBE_VSCODE_VERSION=1.107.1`，构建 2026-11-10）
- 豆包 Lark SDK 版本 8.7.0（`settings.db.__lark_sdk_meta`）
