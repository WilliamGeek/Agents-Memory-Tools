# 会话档案：c9243851（Antigravity Cascade 全量梳理）

> 梳理时间：2026-11-16
> 归档对象：`C:\Users\HP\.gemini\antigravity\conversations\c9243851-6d53-42cf-9089-2c77c2b9d16c.db`
> 关联项目：`F:\Agent会话记忆管理与迁移`（Agents Memory Tools）
> 本文只做事实梳理，不改动任何源文件

---

## 〇、读取范围与 Agent 拓扑

### 0.1 直接读取的源文件

| 对象 | 路径 | 规模 | 说明 |
|---|---|---|---|
| 目标会话库 | `...\.gemini\antigravity\conversations\c9243851-….db` | 32,440,320 B | 明文 SQLite，`steps` 表 1460 条 |
| 会话全量日志 | `...\antigravity\brain\c9243851-….system_generated\logs\transcript_full.jsonl` | 1460 行 | 每步一条 JSON，含 `type` / `content` / `tool_calls` |
| 会话精简日志 | 同目录 `transcript.jsonl` | — | 仅结论性消息 |
| 过程产物 | `...\brain\c9243851-…\` | 4 份 Markdown | `memory_tools_refactor_roadmap.md`、`root_cause_analysis_3_platforms.md`、`subagent_branch_diff_report.md`、`fix_report_3_platforms.md` |
| 临时脚本 | `...\brain\c9243851-…\scratch\` | 若干 | 豆包 IndexedDB / LevelDB / Snappy 探针脚本 |
| 母会话 | `C:\Users\HP\.workbuddy\projects\d-WorkBuddy Date-2026-11-11-01-52-35\e6c0319e-5543-40c8-9b27-22698e9acc76.jsonl` | 7.7 MB | 本会话第 1 条需求指定的上游上下文 |
| 母会话子 Agent | 同上目录 `\subagents\agent-*.jsonl` | 6 个 | `131cabfc`、`279a7f43`、`4cd48270`、`4d5a5be3`、`57c9ccf1`、`a569b130`，各自带 `tool-results\` |

### 0.2 轨迹元数据

- `trajectory_id` = `64ef43af-546c-415e-80d7-c9908638349a`
- `cascade_id` = `c9243851-6d53-42cf-9089-2c77c2b9d16c`（与文件名一致）
- `trajectory_type` = `4`（CLI cascade；新版 IDE 会写 22，本库仍为 4）
- `source` = `22`
- `parent_references` 两条：`ef017a69-ba60-42e1-a541-f2bea094198c`、`892fae6a-7f78-437f-8fd4-b5375f71a2be`，二者 `cascade_id` 同为本 cascade
- `executor_metadata` 6 行（每轮用户请求一条执行上下文，含 `As IDE` 等字段）

### 0.3 递归核对结论

1. 全目录 200+ 个 `.db` 逐一比对 `trajectory_meta` 的 `cascade_id` / `trajectory_id`，**只有本文件命中**；`ef017a69` 与 `892fae6a` 不作为独立库存在，它们是同一 cascade 内的轨迹引用，不构成可单独打开的会话文件。
2. 因此本会话的"子 Agent 源文件"实际分布在两处：`brain\c9243851-…`（本会话自身的过程产物）与母会话目录 `subagents\`（6 个子 Agent 轨迹）。
3. 母会话不是 Antigravity 库，而是 WorkBuddy 的 JSONL 轨迹；本会话是它的**下游执行分支**，不是同一份数据。

### 0.4 步骤构成（`steps` 表统计）

| step_type | 数量 | 含义 |
|---|---|---|
| `GENERIC` | 729 | 工具结果回填 |
| `PLANNER_RESPONSE` | 665 | 模型侧输出（含工具调用） |
| `SYSTEM_MESSAGE` | 50 | 系统/上下文注入 |
| `USER_INPUT` | 8 | 用户输入（6 条不同需求，末条重复 3 次） |
| `CHECKPOINT` | 4 | 检查点 |
| `ERROR_MESSAGE` | 4 | 失败步骤 |

时间跨度：`2026-11-12 09:12:40` → `2026-11-15 18:53:58`（本地 UTC+8）。

---

## 一、整体背景与初始目标

### 1.1 项目定位

Agents Memory Tools 是跨智能体的会话记忆工作台：

- 后端：纯 Python `ThreadingHTTPServer`，单端口 **18922**，同时托管前端静态产物与 REST API；
- 前端：Next.js 15 + React 19 + Tailwind + SWR + Zustand，`output: 'export'` 静态导出到 `frontend/out`；
- 解析引擎：`session-migrate 0.11.0`（装在项目 `.venv` 内），读取各平台会话库；
- 索引：SQLite FTS5 全文检索 + 快照缓存 + 稳定 ETag；
- 分层约束：`services/` 单向依赖，不得 import `web_app.py`。

### 1.2 本会话的初始目标（第 1 条需求）

用户给出一条母会话 JSONL 路径，要求：**先完整读取该母会话的工作内容与所引用的母会话文件，理解 Memory Tools 重构开发进展、项目情况与整体需求，锚定方向后继续重构开发，使其足够完善。**

也就是说，本会话的起点不是新需求，而是**接手一份进行中的重构**：先做上下文还原（读母会话 + 读项目），再继续推进。

### 1.3 目标在执行中的实际漂移

| 阶段 | 重心 |
|---|---|
| R1 | 重构主体：单端口静态化、剥离旧版内嵌 UI、契约回归 |
| R2–R3 | 子会话（subagent）分支的 UI 与交互对齐历史版本 |
| R4 | 三个平台（新版 Antigravity IDE / Trae / 豆包）会话加载失败的系统性修复 |
| R5 | 版式向 WorkBuddy、Antigravity 看齐，补齐索引缺失与详情缺失 |
| R6 | 收缩范围：明确放弃 Trae，只把豆包适配做完 |

最终落点：从"重构完善"收敛为"多平台会话可读 + 版式统一"，并以豆包接入收尾。

---

## 二、需求明细（按提出节点）

| 编号 | 节点（step / UTC / 本地） | 原始需求要点 |
|---|---|---|
| **R1** | step 0 / `2026-11-12 01:12:40Z` / 09:12 | 给出母会话 JSONL 绝对路径；要求先读取该会话工作与所引用的母会话文件，掌握重构进展、项目情况与整体需求，锚定方向后继续重构开发并做到足够完善 |
| **R2** | step 516 / `02:28:20Z` / 10:28 | 带 `/grill-me`、`/browser`：①回溯历史版本中子会话"打开分支"功能的实现逻辑、样式规范、交互效果；②按四个维度对比当前与历史差异（入口触发与展示、卡片点击跳转、子会话详情页布局与控件尺寸间距、控件压缩与布局异常）；③输出差异对比报告，明确列出问题（点名的症状是"子会话卡片点击后详情页与普通会话不一致、控件被压缩"）；④报告确认后严格对齐历史版本重构；⑤全场景测试，要求体验与历史版本完全一致 |
| **R3** | step 876 / `03:44:17Z` / 11:44 | 带 `/browser`："请检查并修复上述问题"（承接 R2 的测试发现，要求实际浏览器验证后修掉） |
| **R4** | step 1102 / `2026-11-14 16:38:13Z` / 11-15 00:38 | 系统性排查并修复**新版 Antigravity IDE、Trae、豆包**三平台会话无法在 Memory tools 正常加载。四条硬性要求：①根因定位（覆盖 API 版本变更、前后端格式不兼容、异步时序冲突、权限校验、平台专属适配缺失、缓存异常等，输出根因文档）；②全平台兼容修复（历史存量 + 新建会话均可加载、完整展示、可访问，且不破坏既有功能）；③全场景验证（多类型、多量级、冷/热启动，指标为加载成功率 100%、耗时符合预期、无回归）；④标准化修复说明文档（根因、改动范围、验证结果） |
| **R5** | step 1349 / `2026-11-15 02:41:39Z` / 10:41 | 带 `/goal`、`/grill-me`：确认 WorkBuddy 与 Antigravity 已修好、格式与读取稳定性良好，**后续其他平台版式要向其对齐**；先检查用户截图中仍存在的问题、判断哪些可修，再依次修复并验证"无会话文件索引缺失、无会话详细内容缺失" |
| **R6** | step 1395 / `09:43:16Z`、`09:45:20Z`、`09:59:34Z` / 17:43–17:59 | 带 `/grill-me`："不求你做 trae 了，把豆包的适配做好就行，能完成吗？"（同文重复 3 次，属重试/重发，不是三个新需求） |

**需求边界变化需明确记录**：R6 把 Trae 从交付范围内**显式移除**；R4 曾要求三平台全通过，R5 已把 Trae 19/19 修到可用，R6 之后不再追加 Trae 工作。

---

## 三、每一步需求对应的改动与交付

### 3.1 R1 → 重构主体（commit `97e6eed`，2026-11-12 10:09）

| 项 | 内容 |
|---|---|
| 交付 | `refactor: 完成单端口静态化与全量契约回归，剥离旧版内嵌UI并优化视觉质感`；标签 `v0.5.0-单端口架构与全量契约回归`、`v0.3.0-高密度工作台与跨会话全文检索` |
| 改动实质 | 后端从"多端口 + 内嵌旧 UI"收敛为**单端口 18922**统一托管静态产物与 API；剥离旧版内嵌页面；建立契约基线（15 项）；前端视觉质感调整 |
| 验证 | 15 项契约回归全绿（该节点自带的门禁结论） |

### 3.2 R2 → 子会话分支重构（commit `c8b9c9b`，11:16）

| 项 | 内容 |
|---|---|
| 交付 | `feat(subagent): 严格对齐历史版本重构子会话双层抽屉、详情页父子面包屑无缝跳转与元数据补全`；标签 `v0.5.1-子会话双层抽屉与父子拓扑无缝跳转` |
| 改动实质 | 子会话详情改为**双层抽屉**；父子面包屑支持无缝跳转；补全子会话元数据；子代理会话不再单独成卡，归拢进父卡片 |
| 证据文档 | `brain\…\subagent_branch_diff_report.md`（历史版本 vs 当前版本的差异对比与问题清单） |

### 3.3 R3 → 子会话卡片收尾（commit `08ccdf7`，12:28）

| 项 | 内容 |
|---|---|
| 交付 | `fix(subagent): 优化子会话卡片标题优先与单一查看按钮，恢复子会话真实用户指令并移除无关提示` |
| 改动实质 | 卡片标题改为"用户真实指令优先"；收敛为单一查看按钮（消除控件压缩与重复入口）；移除无关提示文案 |

### 3.4 R4 → 三平台加载修复（未提交，工作区改动）

| 平台 | 根因 | 改动 |
|---|---|---|
| 新版 Antigravity IDE | `session_migrate/formats/antigravity.py` 默认安全上限为单库 256 MB、单步 64 MB；本地 3 个 364 MB 长会话（`a18f6791`、`87bb0bf9`、`8cdf7c22`）及 86–96 MB 的 `step_type=132` 载荷触发限流 | `_install_antigravity_limits_compat()`：读取路径把 `MAX_NATIVE_BYTES` 提到 1024 MB、`MAX_PROTO_VALUE_BYTES`/`MAX_TEXT_BYTES` 提到 512 MB |
| Trae | 2026-10-12 `project_domain_v2` 迁移后正文进 SQLCipher 库 `ModularData\ai-agent\database.db`；新会话元数据与提问留在 `state.vscdb` 的 `memento/icube-ai-agent-storage` 与 `…-input-history`，但代码未读这两类键，且把无 `.jsonl` 正文、体积 < 1024 B 的记录直接丢弃 | `get_trae_sessions()` 补读两键 + 24 位 ObjectId 补时间；`get_trae_session_messages()` 增 `input_history_db` 分支；详情用 `notice` 如实说明正文在加密库 |
| 豆包 | 前后端都无 `doubao` 适配 | 新增 `_doubao_clean_prompt_title()`、`get_doubao_sessions()`、`get_doubao_session_messages()`，覆盖 agent_mode 轨迹 / coding 快照 / chats 产物；接入 `collect_all_sessions()`、`/api/status`、`_detail_probe()`（`db_` 前缀）、`_detail_load()`、`/api/migrate` |
| 前端 | 平台未注册 | `types/session.ts` 增 `'doubao'`；`lib/platform.ts` 增 `doubao: { label: '豆包', short: 'DB', color: '#2563eb' }`；`Toolbar.tsx` 筛选栏增 `doubao` |
| 文档 | — | `root_cause_analysis_3_platforms.md`、`fix_report_3_platforms.md` |

### 3.5 R5 → 版式对齐与缺口补齐（未提交，工作区改动）

| 平台 | 改动 |
|---|---|
| Claude Code | 新增 `_clean_claude_title_candidate()`，在 `extract_claude_title_and_date()` 中剥离 `<local-command-caveat>`、`<ide_opened_file>`、`<ide_selection>`、`<bash-input>`、`<bash-stdout>`、`<command-name>` 等包裹，改取第一条真实提问作标题；`sanitize_session_events()` 补 `<bash-input>`→`tool_call`(Bash)、`<bash-stdout>`/`<bash-stderr>`→`tool_result`、其余标签剥离 |
| Trae | 历史 `.jsonl` 的 `actions` 拆成标准 `kind="tool_call"`（`tool_name="trae_action"`），与 WorkBuddy/Antigravity 的"指令→行动→回答"版式一致；过滤只有 `state.vscdb` 元数据的空壳卡片；工作区会话统一命名 `Trae 工作区提问历史 (<workspace>) · <N> 条` |
| 豆包 | 清理 agent_mode 用户消息里的本地技能长路径链接 `[Skill](<C:\...\SKILL.md>)`；对"仅 4 字段 trajectory""仅 1 条提问""只有产物文件"的不完整会话补 `notice` |

### 3.6 R6 → 豆包收尾（未提交，工作区改动）

| 项 | 内容 |
|---|---|
| 新增解析 | 实现纯 Python **Snappy 解压**与 **LevelDB（`.ldb`/`.log`）+ V8 wire format** 解析，从 `Default\IndexedDB\chrome_doubao-chat_0.indexeddb.leveldb` 提取会话标题、`session_id`、时间戳与缓存文本块 |
| 追加会话 | 由 IndexedDB 新增 **15 条** 会话（原先 4 条来自 agent_mode / coding / chats） |
| 相关函数 | `_doubao_read_varint`、`_doubao_snappy_decompress`、`_doubao_iter_idb_blobs`、`_doubao_extract_idb_sessions` |

### 3.7 工作区改动规模（截至本次梳理）

`git diff --stat HEAD`：11 个文件，**+1576 / −87**，其中 `web_app.py` `+1090`、`docs/refactor/contract-baseline.json` `+470`、`SessionDetailModal.tsx` 71 行改动。HEAD 仍停在 `3d17cde`（v0.5.4），R4–R6 全部改动**未提交**。

---

## 四、已完成部分的验证结果与状态

### 4.1 R4 完成时的验证（2026-11-14）

| 项 | 结果 |
|---|---|
| `/api/status` | 冷启动 659.5 ms / 热启动 586.6 ms |
| `/api/sessions?format=all` | 冷 1012.4 ms / 热 51.8 ms，426 条（antigravity 158、claude 84、codex 4、doubao 4、trae 66、workbuddy 110） |
| Antigravity 详情 | 抽测 13/13 `200 OK`；3 个 364 MB 会话分别 1317.9 / 1708.3 / 1682.7 ms |
| Trae 详情 | 66/66 `200 OK`（31 条历史 `.jsonl` + 35 条迁移后工作区会话） |
| 豆包详情 | 4/4 `200 OK`，16.4–29.8 ms |
| `qa_regression.py` | 63/63 PASS |
| `selftest_services.py` | 107/107 PASS |
| `contract_baseline.py --check` | 15/16 OK；`sessions_all` 因 `sessions[0]` 是 Antigravity 会话、缺 Trae 专属 5 字段（`account`/`all_files`/`mode`/`model`/`workspace`） |

### 4.2 R5 完成时的验证（2026-11-15 04:10Z）

| 项 | 结果 |
|---|---|
| 总会话 | 386（antigravity 165、claude 84、codex 4、workbuddy 110、trae 19、doubao 4），`format=all` 1087.0 ms |
| Claude Code | 84/84 无 XML 标签标题残留；`bf98f3af` 事件分布 `tool_call 3 / tool_result 3 / message 24 / notice 6` |
| Trae | 19/19 `200 OK` 且事件非空，空壳卡片 0；其中 15 个历史会话已拆出 `tool_call` |
| 豆包 | 4/4 `200 OK` |
| Antigravity | 3 个 364 MB 会话全部 `200 OK`（1315.1–1934.4 ms） |
| 回归 | `qa_regression.py` 63/63；`selftest_services.py` 107/107 |

### 4.3 R6 完成时的验证（2026-11-15 10:53Z）

| 项 | 结果 |
|---|---|
| 豆包会话 | **19/19** 全部加载通过：agent_mode 2、coding_snapshot 1、chat_workspace 1、indexeddb 15 |
| 回归 | `qa_regression.py` 63/63（总计 401 条会话）；`selftest_services.py` 107/107 |

### 4.4 本次复核的实测（2026-11-16，本机现况）

| 项 | 实测 |
|---|---|
| 服务 | `http://127.0.0.1:18922` 在线 |
| `/api/status` | `total_sessions` 416；`format_counts`：antigravity 166、claude 84、codex 9、workbuddy 115、trae 21、doubao 21 |
| `/api/sessions?format=all` | 411 条（antigravity 166、claude 84、codex 4、doubao 21、trae 21、workbuddy 115） |
| Git | HEAD `3d17cde`；11 个文件已修改、未提交（含 `tools/dbkey/` 等未跟踪目录） |

> 说明：`/api/status` 的 416 与 `/api/sessions` 的 411 是两套口径（前者含未通过列表过滤的原始计数），不是数据丢失；豆包已从 19 条增长到 21 条（新增会话写入），说明适配链路在持续工作。

---

## 五、尚未解决的遗留问题、已知缺陷与待处理事项

| # | 问题 | 影响 | 现状 |
|---|---|---|---|
| P1 | R4–R6 的全部改动**未提交**（11 文件 +1576/−87） | 一旦回退或工作区被覆盖即丢失 | 待确认后提交（建议标签 `v0.5.5-豆包接入与三平台对齐`） |
| P2 | Trae 会话正文不可读 | 详情只有提问 + `notice` | 正文在 SQLCipher 库 `ModularData\ai-agent\database.db`（733 MB）。**已推翻旧因**：库确实被 `harness.dll` 在 PID 15188 中以活跃写入态打开，明文页 1 可在内存读到，但 32 字节 AES 密钥在全部 15 个 Trae 进程的可读内存中均不存在（详见第七部分 7.1） |
| P3 | 豆包**普通"最近"聊天正文不可读** | 只有元数据，没有对话内容 | **已定位到真因（本轮修正）**：`messages.db` 已成功解密且 schema 完整（38 表 / 99 对象），但**全部 0 行**，`im.db` 亦为 1 页空库——正文本地根本没落盘，不是加密挡着；详见第七部分 |
| P4 | 2 个 Antigravity 会话详情为空 | 无法查看正文 | 源库 `steps=0`，数据本身为空，代码侧无解 |
| P5 | 豆包 agent_mode 轨迹无思考链 | 详情缺"思考"段 | 落盘仅 `content`/`role`/`tool_call_id`/`tool_calls` 四字段 |
| P6 | 部分豆包工作区会话内容极薄 | 详情近乎空 | `Doubao\chats\2026-11-14\new-chat-1` 仅产物文件；`38446883108715522` 仅 1 条提问 |
| P7 | `contract_baseline` 长期 15/16 | 门禁有一项常红 | `sessions_all` 首条平台漂移导致字段缺；属基线口径问题，非功能缺陷 |
| P8 | Claude Token 逐行累计虚高 | 统计偏高约 88% | **用户明确要求保留旧口径**，不可"顺手修复" |
| P9 | Trae 无真实 Token 用量 | 只能估算 | 加密库未解（同 P2）；已用 Trae 自写的明文记忆层（`memory\*.jsonl`）作降级替代，见 7.1 |
| P10 | `v0.5.2` 标签指向 `24e45c1`，不在 main | 按标签回退会脱离主线 | 该提交在 `backup/session-changes-20261112`；主线等价内容见 `358c15f` |
| P11 | 工作区曾被外部进程整批还原到 HEAD | 提交可能空转 | 提交前必须 `git status` + `git diff` 复核 |

---

## 六、后续待完成的工作项与关键注意事项

### 6.1 待办（按优先级）

1. **提交并归档 R4–R6**：复核 diff → `git add`（11 文件 + `tools/dbkey/`）→ 提交 → 打中文标签（建议 `v0.5.5-豆包接入与三平台对齐`）。这是当前最大的风险点。
2. **豆包普通聊天正文**：需要突破 `messages.db` / `im.db` 的 SQLCipher（见 `tools/dbkey/README.md` 的现状与技术结论）。
3. **Trae 正文**：同样卡在 SQLCipher；若恢复该目标，走同一套密钥路径而不是再试导出命令。
4. **契约基线 16/16**：把 `sessions_all` 的首条断言改为"按 format 取样"而非"取 `sessions[0]`"，消除常红项。
5. **清理归档**：确认不再需要后，处理 `archive/*` 标签与 `backup/session-changes-20261112` 分支。

### 6.2 关键注意事项（踩坑清单）

1. **单端口**：只允许 18922；3000 端口是旧 Next 开发服务，停止脚本只杀 18922。
2. **VBS 必须纯 ASCII**：WSH 按 ANSI 解析，中文注释会破坏语法。
3. **改后端必须重启**：`web_app.py` 无热重载；前端改动需重新 `npm run build`。
4. **兼容层是 monkey-patch**：不改 `.venv` 内 `session_migrate` 源码；升级依赖后必须重验 `trajectory_type=22` 与子会话 root 两个补丁。
5. **`TOKEN_CACHE_VERSION` 是口径开关**：任何 Token 逻辑变更必须 +1，否则旧缓存会让改动看起来没生效。
6. **Claude 逐行累计是用户决策**：不要改成按 `message.id` 去重。
7. **数据源只读**：`.db` / `.jsonl` / `state.vscdb` 一律只读。
8. **提交前复核 diff**：本项目出现过外部进程整批还原工作区的情况。
9. **改后门禁**：`qa_regression.py`、`selftest_services.py`、`contract_baseline.py`、`test_token_usage.py` 必须全绿才可声称完成。
10. **分层约束**：`services/*` 不得 import `web_app.py`。

---

## 附录：本会话与项目其它会话的关系

- 本会话（`c9243851`）是 **WorkBuddy 母会话 `e6c0319e`** 的下游执行分支，母会话带 6 个子 Agent 轨迹；
- 项目另一条并行的 Antigravity 会话（`35cd8f87`）覆盖 N1–N14（含 Token 口径、回退与恢复、Trae 证据链），其结论已固化在 `docs/handoff-20261114.md`；
- 本会话覆盖的是 handoff 文档之后的 R4–R6（三平台修复 + 豆包接入），因此**两份文档合起来才是完整项目史**：handoff 到 2026-11-14，本文到 2026-11-15。

---

## 第七部分：豆包 / Trae 加密库读取的最新进展（本文件写定后补齐）

会话内（step 1394、step 1457）曾给出"不绕过客户端访问控制、加密库无法读取"的结论。本轮在用户明确授权（自有资产、自有机器）后继续推进，结果推翻了该结论：

- **豆包已解开**：从 `Doubao.exe`（PID 6780）只读内存中找到"同一页的密文+明文"配对，用链式 AES-CBC 判别器在 86.53M 候选、29 秒内定位到 32 字节密钥 `3b9cb6b2a66e7ce0f4d8bfd708b31b27899e61cea6db28b02b4d81f45e7af351`，整页复校 4048/4048 一致。加密形态为 SQLCipher + AES-256-CBC、页 4096、保留区 80、页尾 16 字节明文 IV、第 1 页前 16 字节为 salt。
- **`messages.db` 已能解密并解析**：产物 `tools/dbkey/out/messages_plain.db` 与源等长 450,560 B，`sqlite_master` 返回 99 个对象、38 张表结构完整（`messages` 表 110 个字段）。
- **但 `messages.db` 是空壳**：38 张表全部 0 行，`im.db` 亦为 1 页空库。因此"豆包普通会话正文读不到"的真实原因是**本地未落盘**，而非加密阻挡；正文只以缓存在 IndexedDB（已接入 15 条）与工作区 `.sessions` 中存在。
- **未解部分**：`settings.db`(705 页) / `cookie_store.db`(7 页) 等用同密钥解出为乱码，判定为**每库独立密钥**，需各自再做一次内存提取；Trae `database.db`(733 MB) 未解，Trae 当前未运行，且其密钥体系与豆包无关。

技术档案与工具见 `tools/dbkey/README.md`。

### 7.1 本轮补充（2026-11-16 晚，Trae 处于打开并活跃写入态）

**前提已满足，但 Trae 库仍未解开。**

1. 打开库的模块是 `D:\Trae CN\resources\app\modules\ai-agent\harness.dll`（263.77 MB，Rust + SQLCipher，含 `PRAGMA key = `、`cipher_page_size`、`aes-256-cbc`/`chacha20` 与 `harness\storage-db\src\connection\pool.rs`），不再是此前认定的 `libckg.dll`（ckg 模块当前未被任何进程加载）。
2. 唯一持有者是 `Trae CN.exe` PID 15188（`basil.mojom.NativeExtensionService`、`--service-sandbox-type=none`），psutil `open_files` 实证其同时持有 `database.db` 与 `database.db-shm`。
3. 库处于活跃写入：17:45 checkpoint 后首页尾 IV 变为 `48efd776328ebbf73cbd777ddbf2aa9d`，WAL 由 41,232 B 涨到 257.5 KB。
4. 严格三重校验（magic + 4096 + 178,958 页）在 PID 15188 命中 25+ 份明文首页（`0x0267bcdea270`、`0x0267bcdeb480` 等）；旧的 `trae_locate.py` 地址是 JSON 误报，已弃用。
5. 判据与管线已用已知密钥自检靶证明无误报、无假阴性（`_selftest.db` + `keyhunt9.py` 命中 4 处）。
6. 之后穷举 V1–V5 五种布局、IV 偏移 4016/4032/4080、keylen 16/24/32、stride=1、无熵过滤、PID 15188 私有堆 40 MB 与映射区 74 MB、全部 15 个 Trae 进程（单进程最大 389–690 MB）、588 条口令 × 6 组 KDF × 2 种前驱、`ICUBE_MACHINE_ID` / `CKG_APP_ID` / `ICUBE_CODEMAIN_SESSION` / `ICUBE_AI_AGENT_SHUTDOWN_TOKEN` / `trae-jwt-token` —— **全部零命中**。

**结论**：Trae 的 AES 密钥不以明文驻留可读内存（疑为交付 SQLCipher 后立即零化），因此"抓 dump 扫密码"这条路径在本机对它无效。要突破只剩侵入式手段（在 `PRAGMA key` 处挂钩/下断）或从页缓存按 b-tree 结构部分拼装；按用户"不建议做的不做"的要求，本轮不推进。

**降级交付（已落地，不依赖解密）**：Trae 自行把每轮对话的 `intent / actions / outcome / learned` 明文写入 `C:\Users\HP\.trae-cn\memory\projects\<项目>\<日期>\session_memory_<sessionId>.jsonl`（另有 `topics.md`、`project_memory.md`、`user_profile.md`）。已全量导出为 **`docs/trae-memory-export.md`**（104 条、34 份会话记忆文件），可作为正文不可读时的替代成果，也是后续若接入产品代码的最小可用数据源。