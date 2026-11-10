# Memory Tools · 会话详情渲染重构 · 交接文档

> 生成时间：2026-11-07 13:05
> 仓库：`F:\Agent会话记忆管理与迁移`（origin: `git@github.com:WilliamGeek/Agents-Memory-Tools.git`，分支 `main`）
> 当前 HEAD：`9d3f3c1`，最新标签 `v0.2.2-子代理会话可读`，工作区 clean
> 本文目的：把「会话详情界面该长什么样」的调研、诉求、方案完整交接，供接手方直接实施

---

## 0. 一句话结论

**会话数据从未丢失，变的是呈现方式。** Antigravity 会话的原始事件数在初始版和当前版完全一致（同一会话 7,454 条），差异只有两处：

1. 当前版把连续的「思考 + 工具调用 + 工具结果」合并成一个「🔧 工具执行链」气泡（4,826 → 397 个气泡）；
2. 单条内容被硬截断（思考/调用 4,000 字、结果 6,000 字），该会话丢了 16.7% 的文本。

用户喜欢的是 **初始版 `806555c` 的逐条展示**，但也认可合并版对长会话更实用。所以最终要走「可切换的三档视图 + 按平台自适应默认值」，而不是二选一。

---

## 1. 项目速览

| 项 | 值 |
|---|---|
| 形态 | 单文件 Python HTTP 服务 + 内嵌 HTML/CSS/JS（`web_app.py`，约 7,200 行） |
| 启动 | `F:\Agent会话记忆管理与迁移\.venv\Scripts\python.exe web_app.py`，默认 `http://127.0.0.1:18922` |
| 前端 | 原生 JS，无框架；所有 UI 都在 `HTML_PAGE = """..."""` 三引号字符串里 |
| 依赖 | `session_migrate`（第三方解析库，装在 `.venv`）、`tiktoken` |
| 数据源 | Antigravity `.db`(protobuf) / Claude `.jsonl` / WorkBuddy `.jsonl` / Trae `state.vscdb`+加密库 |

**关键工程注意点（本机沙箱特有，会直接影响开发效率）**

- `HTML_PAGE` 是**普通三引号字符串**，JS 里写 `'\n'` 会被 Python 转成真实换行，导致前端 `Invalid or unexpected token` 整页白屏。必须写 `'\\n'`。改完前端务必校验一次语法（见 §9）。
- 后台启动的服务进程会在会话结束时被回收（`exit code 127/1`），不是崩溃。用 `启动Memory Tools.cmd` 启动更稳。
- 本机 curl 访问 localhost 需要 `--noproxy '*'`，否则走代理返回 502。
- 对 `F:` 盘的写操作优先用编辑器工具，Shell 原生 exe 偶发"写入虚拟化"。

---

## 2. 用户诉求（原话整理）

- 「我非常喜欢之前那把 Antigravity 的（逐条展示），但我也不得不承认工具链（合并）的适配性更高。」
- 希望方案**同时解决各平台兼容性**与**人性化显示/交互**，不是简单二选一。
- 想找回能「完整展示各种回复、工具调用和思考过程」的那个版本。

---

## 3. 现状：详情渲染链路

### 3.1 后端（几乎不用改）

| 位置 | 作用 |
|---|---|
| `web_app.py:2555` `handle_get_session_detail()` | 按 `catalog_id` 前缀分派：`wb_` / `trae_` / `ag_` / 其余走 Catalog |
| `web_app.py:1404` `sanitize_session_events()` | **只处理 `kind=message` 且 `role=user`** 的事件（把注入的环境信息降级为 `notice`），thinking / tool_call / tool_result 原样透传 → **不会丢事件** |
| 返回结构 | `{session_id, format, title, started_at, events_count, events[], notice}`，事件字段：`kind / role / timestamp / text / tool_name / tool_call_id / payload` |

`kind` 的取值：`message`、`thinking`、`tool_call`、`tool_result`、`notice`、`opaque`。

### 3.2 前端（改动集中在这里）

| 位置 | 作用 |
|---|---|
| `web_app.py:6180` `openChatModal(cid)` | 拉取 `/api/session/detail` 并渲染；注意它用 `allSessions.find(s => s.catalog_id === cid)` 取元数据，`cid` 必须来自列表 |
| `web_app.py:5938` `buildDisplayItems(events)` | **合并逻辑**：连续的 `thinking/tool_call/tool_result` → 一个 `{kind:'tool_group', items:[]}` |
| `web_app.py:5963` `renderToolGroup(items)` | 渲染「🔧 工具执行链」气泡：头部显示 `read_file → run_command ×3` 链式摘要 + 次数统计，展开后逐条 `<pre>` |
| `web_app.py:5957` `truncateBlock(text, limit)` | 硬截断，超限部分直接丢弃，只留一句"完整内容见原始会话文件" |
| `toggleAllBubbles(expand)` | 全部收起 / 全部展开（操作 `#chatStreamBody .collapsible`） |

### 3.3 初始版（`806555c`）的渲染

没有 `buildDisplayItems`，直接 `events.map(...)`，一个事件一个气泡：

```
message(user)      → 👤 用户指令 #N
message(assistant) → 🤖 助手回复（默认收起，带 extractAssistantSummary 摘要）
thinking           → 💭 思考过程（默认收起，正文全文，等宽字体，紫色）
tool_call/tool_result → 🔧 工具气泡（默认收起，正文全文，max-height 420px 可滚动）
opaque             → 不渲染（return ''）
```

**完整、无截断，但单会话会产生 4,826 个 DOM 气泡。**

---

## 4. Git 版本考古

仅有 7 次提交（其中 1 次游离）。`git log -S` 的判定证据：

```
buildDisplayItems      : da1556a
renderToolGroup        : da1556a
truncateBlock          : da1556a
sanitize_session_events: da1556a
toggleAllBubbles       : 806555c
```

| 版本 | 提交 | 时间 | 对详情页的影响 |
|---|---|---|---|
| 初始版 | `806555c` | 11-03 10:24 | **逐事件渲染，零截断** ← 用户偏好的那一版 |
| `v0.1.0-会话事件清洗层` | `da1556a` | 11-03 13:54 | **引入合并 + 截断 + 用户原始记录折叠**，详情渲染从此改变 |
| `v0.1.1-真实用量口径` | `463cc4e` | 11-03 14:04 | 无关（token 统计） |
| `v0.2.0-同源分叉识别` | `a5b8a8b` | 11-05 00:54 | 只动列表层（分叉标记、折叠副本、全部收起/展开按钮），详情未改 |
| `v0.2.1-空会话过滤` | `fbee396` | 11-07 11:43 | 无关（Trae 空壳过滤） |
| `v0.2.2-子代理会话可读` | `9d3f3c1` | 11-07 12:26 | 标题 + 子会话解析 + 数据源提示条，详情渲染未改 |
| 游离提交 | `409523b` | 11-05 01:16 | 纯 CSS 重构（SUI Mono 单色系统），已被 reset 撤销，不在任何分支 |

> 注意：项目在 2026-10-09 之前就存在（git init 前的版本不可追溯）。若用户记忆中的版本早于 `806555c`，只能从编辑器本地历史或备份里找。

---

## 5. 实测：两版差异（同一会话 `35cd8f87`）

为取得可信数据，曾把 `806555c` 单独部署到 18923 端口做同会话对照：

| 指标 | 初始版 `806555c` | 当前 `9d3f3c1` |
|---|---|---|
| 后端返回事件数 | 7,454 | 7,454（**完全一致**） |
| 渲染气泡总数 | **4,826** | 397 |
| 💭 思考 | **652 个独立气泡** | 0（并入 276 个工具链组） |
| 🔧 工具调用/结果 | **4,053 个独立气泡** | 276 组 |
| 🤖 助手回复 | 69 | 69 |
| 👤 用户指令 | 52 | 52 |
| 单条截断 | 无 | 思考/调用 4,000 字、结果 6,000 字 |
| 可见文本占比 | 100% | **83.3%**（丢约 35.8 万字，66 条结果被切） |

结论：**数据一致，只有呈现差异**；`sanitize_session_events` 没有丢 thinking/tool 事件。

---

## 6. 各平台事件语义差异（决定"不能全局统一"）

同机样本实测：

| 平台 | 样本事件构成 | 特征 | 适配建议 |
|---|---|---|---|
| Antigravity | 7,454：思考 652 / 调用 2,092 / 结果 1,961 / 消息 121 / opaque 2,628 | 事件最细，思考+工具占 63% | **逐条最有价值** |
| WorkBuddy | 1,527：思考 344 / 调用 497 / 结果 497 / 消息 166 / notice 23 | 工具 1:1 成对，思考量大 | 标准档（调用对成组） |
| Claude | 211：调用 33 / 结果 33 / 消息 63 / opaque 82 | **无独立 thinking**，工具严格成对 | 标准档即可，合并收益小 |
| Trae | 98：全部是 message | 无工具、无思考 | 紧凑档 |

---

## 7. 约束：以下既有能力不得破坏

1. **`sanitize_session_events`**：伪用户输入降级为 `notice`（带 `hidden_chars` / `raw_text`），详情页的「查看原始记录（含系统注入）」依赖它。
2. **子代理会话兼容**：`web_app.py:66` `_install_antigravity_child_session_compat()` 猴补了 `session_migrate._validate_trajectory_metadata`，让 `browser` 等子会话能被读取。**只放宽读取（`generated=False`），不要放宽写入**。
3. **标题解析链**：`web_app.py:836` `antigravity_parent_title()` 回溯父会话标题；`antigravity_first_user_text()` 取首条用户输入兜底。列表与详情必须保持同一口径。
4. **同源分叉**：`_mark_antigravity_lineage()` 给副本打标，列表层「折叠同源分叉」依赖 `is_lineage_branch` / `lineage_size`。
5. **数据源提示条**：`trae_encrypted_store_notice()` → `/api/sessions` 的 `notice` 字段 → 顶部 `.data-source-notice`；详情页对应 `.detail-notice`。
6. **已回滚但归档的实验**：`archive/v0.3.0-token-ledger`（请求账本去重）。用户明确要求回滚，**不要擅自恢复**；如需重做必须另开分支并说明数字会下降约 4.6%。
7. **用户指令跳转**：`user-bubble-anchor` + `data-user-idx` 是 Alt+↑/↓ 与「上一个/下一个」按钮的锚点，任何渲染重构都要保留这一层。

---

## 8. 讨论中的方案（待接手方实施/优化）

### 8.1 三档视图（全局开关，localStorage 记忆）

| 档位 | 渲染方式 | 典型气泡数（`35cd8f87`） |
|---|---|---|
| 紧凑 | 现状：连续工具+思考合成「工具执行链」 | 397 |
| 标准 | 工具调用与结果**成对成组**（`▶ 调用` + `◀ 结果` 一个气泡），思考独立成条 | ~1,300（预估） |
| 完整 | 每事件一个气泡，无合并、无截断 | **4,826** |

三档共用同一份 `events`，只切渲染分支；后端不动。

### 8.2 平台自适应默认

| 平台 | 默认档 | 理由 |
|---|---|---|
| Antigravity | **完整** | 事件最细，652 段思考值得逐条看 |
| WorkBuddy | 标准 | 工具 1:1 成对 |
| Claude | 标准 | 无 thinking，合并收益低 |
| Trae | 紧凑 | 全是消息 |

未知平台或缺少 `kind` 的平台自动降级到紧凑，避免白屏。

### 8.3 截断 → 渐进展开

废弃 `truncateBlock` 的硬丢弃，改为：默认显示前 2,000 字 + 「展开全文（还有 N 字）」按钮，点击渲染完整内容。
「全部展开」按钮操作时按需构建，避免一次性插入数万节点。

### 8.4 回合级懒渲染（性能解法）

以「用户指令」为边界把会话切成回合块：
- 默认只展开最后一个回合，其余显示一行摘要（`#3 · 用户指令前 40 字 · 87 条事件`）；
- 点击才构建该回合内部的 DOM。

节点数与会话总长解耦，不需要引入虚拟滚动那种重型方案。

### 8.5 交互补充

- 顶部筛选下拉：**只看回复 / 只看工具 / 只看思考**（按 `kind` 过滤）
- 完整档下 `opaque` 折叠成一条「原始记录 N 条」，不逐条展开（当前 2,628 条无语义记录）
- 保留每气泡的类型徽标与字数徽标；完整档徽标更细（区分 `▶ read_file` 与 `◀ result`）

---

## 9. 验收口径（可直接执行）

```bash
# 1. 语法自检（前端 JS 在 Python 字符串里，必须校验渲染后的产物）
curl -s --noproxy '*' http://127.0.0.1:18922/ > page.html
python -c "import re;h=open('page.html',encoding='utf-8').read();open('s.js','w',encoding='utf-8').write(re.findall(r'<script>(.*?)</script>',h,re.S)[0])"
node --check s.js
```

浏览器端（Playwright 或手工）用会话 `35cd8f87-6e4e-419f-aa24-a6466b69e711` 验证：

| 档位 | 期望气泡数 | 期望截断 |
|---|---|---|
| 完整 | **4,826**（user 52 / assistant 69 / thinking 652 / tool 4,053） | 0 |
| 标准 | ~1,300 | 0（渐进展开） |
| 紧凑 | 397 | 仅懒加载，不丢数据 |

其他必测项：

- `ag_7114c5e6-a7c7-4cde-8472-129544942abe`（browser 子会话）能打开，且带「子会话」提示条；
- `trae_6aee0c53f5956961` 能打开，显示数据源限制提示；
- Claude / WorkBuddy 各开一个会话，thinking 与工具对渲染正常；
- 列表排序、搜索、迁移、删除、Alt+↑/↓ 跳转不回归。

---

## 10. 未决问题

1. **默认档位**：建议"按平台自适应"（Antigravity=完整），用户尚未最终拍板。若倾向"统一某一档"，改 `8.2` 的映射表即可。
2. 完整档 4,826 个气泡下，浏览器搜索（`handleChatSearch` 基于 `mark.chat-highlight`）是否需要限流/防抖，实测后再定。
3. Trae 历史会话正文解析：当前基于 state.vscdb 与 memory 日志自适应提取用户指令流并呈现，后续若有新存储层格式按需扩充支持。

---

## 11. 常用命令

```bash
cd "F:\Agent会话记忆管理与迁移"

# 看某次提交的渲染实现
git show 806555c:web_app.py | sed -n '4866,4975p'

# 比对两个版本的差异
git diff 806555c da1556a -- web_app.py | grep -E "^[-+].*(bubble|renderToolGroup|truncate)"

# 起一个历史版本做对照（不污染工作区）
git worktree add "F:\mt-old" 806555c
```

---

## 12. 附：本轮已交付的其他修复（勿回退）

| 提交 | 内容 |
|---|---|
| `da1556a` | 跨平台会话事件清洗层（伪用户输入 → notice） |
| `463cc4e` | token 改用客户端记录的真实用量（Antigravity `steps.metadata` / Claude `message.usage`） |
| `a5b8a8b` | 同源分叉快照识别与 `/btw` 旁问标注 |
| `fbee396` | Trae 空壳会话过滤（75 → 31） |
| `9d3f3c1` | 子代理会话可读（root 校验放宽）+ 标题继承父会话 + 数据源限制提示条 |
