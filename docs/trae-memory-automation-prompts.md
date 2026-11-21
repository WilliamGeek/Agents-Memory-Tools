# 会话记忆自动化提示词体系（Engineering Prompt System）

> 适用项目：`F:\Agent会话记忆管理与迁移`（Agents Memory Tools）
> 目标：让智能体在**无人值守**的前提下完成「索引刷新 → 增量提取 → 摘要沉淀 → 冲突消解 → 一致性校验」闭环。
> 版本：v1.0 · 2026-11-13

---

## 0. 数据源可读性矩阵（先看这一节，避免设计错方向）

| 平台 | 本地可读内容 | 可提取字段 | 自动化可行性 |
|---|---|---|---|
| Antigravity | 会话库 SQLite（新版 `trajectory_type=22`） | 指令 / 思考 / 工具调用 / 回复 / 时间 / token | 全自动 |
| Claude Code | `*.jsonl` | 同上 | 全自动 |
| WorkBuddy | `*.jsonl` | 同上 | 全自动 |
| Trae CN | `state.vscdb` 提问缓存 + 加密库 `ModularData\ai-agent\database.db`（SQLCipher） | 仅用户提问、标题、时间、模型 | 仅提示词级；正文需解密后才能全自动 |
| 豆包 | IndexedDB 会话元数据（V8 序列化） | 会话 ID / 标题 / 时间 | 仅目录级，正文在云端，不纳入本体系 |

**硬约束**：本提示词体系不会、也不能伪造不可读平台的内容。遇到不可读平台时，流水线必须降级并在产物中标注 `source_unreadable=true`，而不是静默跳过。

---

## 1. 总体流程

```
[触发] → [刷新索引] → [增量识别] → [逐会话提取] → [归一化] → [摘要生成]
                                                              ↓
[归档产物] ← [校验] ← [冲突消解] ← [写入记忆文件] ← [去重]
```

对应项目内实际接口：

| 步骤 | 命令 / 接口 |
|---|---|
| 刷新索引 | `POST http://127.0.0.1:18922/api/catalog/refresh` |
| 会话列表 | `GET /api/sessions?limit=1000` |
| 详情 | `GET /api/session/detail?catalog_id=<id>&slim=1` |
| 会话内检索 | `GET /api/session/search?catalog_id=<id>&q=<kw>` |
| 全局检索 | `GET /api/search/content?q=<kw>&limit=50` |
| 状态 | `GET /api/status` |

---

## 2. 记忆触发条件（Trigger Contract）

满足**任意一条**即触发一轮记忆维护：

| 编号 | 条件 | 判定方式 |
|---|---|---|
| T1 | 定时触发 | 每日 09:00 / 21:00（Windows 计划任务或 Trae Schedule） |
| T2 | 索引指纹变化 | `/api/status` 的 `total_sessions` 或快照 `snapshot` 与本地上次记录不同 |
| T3 | 会话文件 mtime 前进 | 任一数据源最近修改时间 > 上次成功时间 |
| T4 | 手动触发 | 用户执行「记忆同步」指令 |
| T5 | 会话结束事件 | 检测到某会话 `mtime` 连续 10 分钟未变化且此前处于活跃 |

**防抖规则**：同一轮触发内，同一 `catalog_id` 只处理一次；失败重试上限 3 次，指数退避（5s/20s/60s）。

---

## 3. 提取规则（Extraction Rules）

### 3.1 统一事件模型

每条事件必须落成以下结构（与项目 `SessionEvent` 对齐）：

```json
{
  "kind": "message | thinking | tool_call | tool_result | opaque",
  "role": "user | assistant | system | tool",
  "timestamp": "ISO8601",
  "text": "正文",
  "tool_name": "仅在 tool_call / tool_result 出现",
  "payload": {},
  "event_index": 0
}
```

### 3.2 分平台规则

1. **Antigravity**：直接使用 `/api/session/detail` 返回的 `events`；`trajectory_type=22` 由后端兼容层处理，不得在前端二次过滤。
2. **Claude / WorkBuddy**：以 `*.jsonl` 行为单位解析，`role` 必须取自记录本身，禁止按奇偶推断。
3. **Trae**：
   - `message(role=user)` 来自 `state.vscdb` 的 `ai-chat.chatQueryCompletion.v1.<sid>`；
   - **没有 assistant 事件时必须写入 `notice`**，不得输出「空会话」；
   - 加密库正文不进入流水线，标记 `source_unreadable=true`；
   - 禁止尝试绕过加密（合规红线）。
4. **通用清洗**：剥离 ANSI、折叠连续空行、系统提示折叠到 `hidden_chars`、payload > 1500B 标注 `_omitted`。

### 3.3 摘要规则（防过拟合）

- 只提取**与项目决策相关**的事实：目标、约束、结论、待办、风险；
- 禁止把一次性吐槽、临时路径、无关偏好写进长期记忆；
- 每条摘要必须带来源：`{catalog_id, turn_index, event_index}`；
- 单条摘要 ≤ 200 字；单个会话摘要 ≤ 1200 字；
- 不复制大段代码，只保留「改了什么 + 为什么」。

---

## 4. 存储格式（Storage Contract）

### 4.1 索引层（已有，不改）

- `catalog.sqlite3`：根目录、会话元数据
- `dialogue_fts.sqlite3`：FTS5 全文索引（按 turn 存储）

### 4.2 记忆层（新增，按此结构落盘）

目录：`F:\Agent会话记忆管理与迁移\exports\memory\`

```
exports/memory/
  index.json                     # 全量记忆索引
  sessions/<catalog_id>.json     # 单会话记忆
  daily/YYYY-MM-DD.md            # 当日增量摘要
  conflicts.jsonl                # 冲突记录（只追加）
  runs/YYYYMMDD-HHMMSS.json      # 每轮执行报告
```

`index.json`：

```json
{
  "schema": "memory-index/v1",
  "updated_at": "2026-11-13T09:00:00+08:00",
  "last_snapshot": "abc123",
  "entries": [
    {
      "catalog_id": "ag_xxx",
      "format": "antigravity",
      "title": "会话标题",
      "started_at": "2026-11-12 12:34",
      "mtime": 1794486044.64,
      "content_hash": "sha256:...",
      "summary_path": "sessions/ag_xxx.json",
      "turns": 12,
      "tokens": 34567,
      "source_unreadable": false
    }
  ]
}
```

`sessions/<id>.json`：

```json
{
  "schema": "memory-session/v1",
  "catalog_id": "ag_xxx",
  "format": "antigravity",
  "title": "...",
  "started_at": "...",
  "content_hash": "sha256:...",
  "summary": "三段式：背景 / 结论 / 待办",
  "facts": [
    { "kind": "decision", "text": "...", "ref": { "turn": 3, "event": 41 } }
  ],
  "open_questions": ["..."],
  "notices": [],
  "source_unreadable": false
}
```

**不可变规则**：`content_hash` 一旦写入不得手改；内容变化必须走第 5 节冲突流程。

---

## 5. 冲突处理机制（Conflict Resolution）

| 冲突类型 | 判定 | 处理 |
|---|---|---|
| C1 内容更新 | 同 `catalog_id`，`mtime` 前进且 hash 变化 | 覆盖 `sessions/<id>.json`，旧版本追加到 `history/<id>/<hash>.json` |
| C2 时间倒流 | 新 `mtime` < 已存 `mtime` | 不覆盖，写入 `conflicts.jsonl`，标记 `reason=stale_source` |
| C3 标题漂移 | 同 id 标题不同 | 以最新 `started_at` 为准，旧标题记入 `aliases` |
| C4 摘要漂移 | 同一 turn 的新摘要与旧摘要冲突 | 保留两条，冲突双方都带 `ref`，交由下一轮人工/模型复核 |
| C5 源不可读 | `source_unreadable=true` | 保留旧记忆，不删除；写 `notices`，不参与删除判定 |
| C6 会话消失 | 数据源中已不存在该会话 | 不立即删除，标记 `missing_since`，连续 3 轮缺失才移入 `archived/` |
| C7 重复会话 | 同 `session_id` 多份分叉 | 以 `lineage_head` 为父，其余标 `is_lineage_branch`，只摘要父会话 |

冲突记录格式（`conflicts.jsonl`）：

```json
{"ts":"2026-11-13T09:00:00+08:00","catalog_id":"ag_xxx","type":"C2","detail":{"stored_mtime":1794486044,"new_mtime":1794400000},"action":"keep_old"}
```

---

## 6. 验证标准（Validation Gates）

一轮流水线只有全部通过才允许标记 `success`：

| 编号 | 断言 | 判定 |
|---|---|---|
| V1 | 索引接口可用 | `GET /api/status` 返回 200 且 `total_sessions > 0` |
| V2 | 抽样详情可用 | 随机 10 个会话详情 200，且 `events_count > 0`（源库本身为空的白名单除外） |
| V3 | 记忆产物完整 | `index.json` 条目数 == 本轮应处理会话数 |
| V4 | hash 一致 | 对每个 `sessions/<id>.json` 重算 hash 与 `index.json` 一致 |
| V5 | 引用可回溯 | 每条 `facts.ref` 能在详情里找到对应 `turn/event` |
| V6 | 无静默丢失 | 上轮存在、本轮消失的会话必须出现在 `conflicts.jsonl` 或 `archived/` |
| V7 | 不可读标记 | 所有 Trae 会话均带 `source_unreadable` 字段（值可为 false，但键必须在） |
| V8 | 回归门禁 | 项目自带脚本全绿：`tools/qa_regression.py` 63/63、`tools/selftest_services.py` 107/107、`tools/contract_baseline.py --check` 15/15 |

失败处理：任意一条失败 → 本轮标记 `failed`，写 `runs/<ts>.json` 的 `failed_gates`，**不回滚已写入的成功条目**，下一轮幂等重试。

---

## 7. 可直接复用的提示词模板

### 7.1 主控提示词（System / Orchestrator）

```text
你是「Agents Memory Tools」的记忆维护守护进程，只做增量维护，禁止重建全量。

硬性约束：
1. 只读数据源，不修改任何会话原始文件；不尝试解密加密库。
2. 不可读内容必须标注 source_unreadable=true，禁止编造摘要。
3. 同一 catalog_id 同一轮只处理一次；失败最多重试 3 次。
4. 任何删除动作必须先进入 conflicts.jsonl 并观察 3 轮。
5. 摘要只记录决策/约束/结论/待办/风险，禁止记录无关偏好与一次性信息。
6. 输出必须是合法 JSON，字段严格遵循 memory-index/v1 与 memory-session/v1。

执行顺序：
refresh → list → diff → extract → normalize → summarize → persist → validate → report
```

### 7.2 增量识别提示词

```text
对比 exports/memory/index.json 与 /api/sessions 返回值，输出新增/更新/消失三类清单：
- 新增：catalog_id 不在 index 中
- 更新：catalog_id 存在，且 mtime 前进或 content_hash 变化
- 消失：index 中存在，但数据源已不存在
输出格式：{"added":[],"updated":[],"missing":[]}
不得对 Trae 会话调用详情解析正文，只取标题/时间/提问缓存。
```

### 7.3 摘要提取提示词

```text
为会话 <catalog_id> 生成记忆，遵守：
- 三段式：背景（为什么做）/ 结论（做了什么、结果如何）/ 待办（未完成项）
- facts 每条 ≤ 200 字，必须带 ref（turn_index, event_index）
- 代码只写「文件 + 改动意图」，不粘贴实现
- 工具调用只归纳为动作类型（如「批量改名」「跑回归」），不逐条罗列
- 如果事件里没有 assistant 内容，summary 写「仅提问可读」，facts 为空
输出：memory-session/v1 JSON
```

### 7.4 冲突消解提示词

```text
读取 conflicts.jsonl 中未决条目，按类型处理：
C1 覆盖并归档旧版本；C2 保留旧版；C3 采用最新标题并记录别名；
C4 两条摘要都保留并标 contested；C5 不删除；C6 计时；C7 只保留 lineage_head。
每个动作输出一行 JSON：{"ts","catalog_id","type","action","reason"}
禁止在冲突未决时删除任何记忆文件。
```

### 7.5 校验提示词

```text
逐条执行 V1–V8，输出：
{"run_id":"...","passed":[],"failed":[],"failed_gates":[],"sample_checked":10}
任何 FAIL 都必须附证据（接口返回码/字段缺失/脚本输出尾部 20 行）。
全部 PASS 才允许把本轮 run 标记 success。
```

### 7.6 修复提示词（失败后）

```text
读取 runs/<ts>.json 的 failed_gates，只修复失败项：
- 接口类：等待 5s 重试，最多 3 次
- 产物类：只重写受影响文件，不动其他条目
- 校验类：输出差异并停止，等待人工确认
禁止通过放宽校验标准来「通过」。
```

---

## 8. 编排方式

### 8.1 Windows 计划任务（推荐）

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -File `"F:\Agent会话记忆管理与迁移\tools\memory_sync.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At 09:00
Register-ScheduledTask -TaskName "AgentsMemory-Sync" -Action $action -Trigger $trigger
```

`memory_sync.ps1` 的职责：调用 refresh → 运行主控提示词对应脚本 → 执行 V1–V8 → 写 `runs/`。

### 8.2 Trae Schedule

用 `Schedule` 工具创建每日任务，`message` 字段直接使用 7.1 主控提示词 + 7.2/7.3/7.5 的组合。

---

## 9. 已知限制（必须在报告中体现）

1. **Trae 正文不可读**：SQLCipher 加密，密钥运行时注入；除非做密钥捕获（高风险），否则只到提问级。
2. **豆包正文不落本地**：仅会话元数据，不纳入本体系。
3. **摘要漂移**：同一会话多次摘要可能表述不同，靠 C4 保留双方，不做自动裁决。
4. **FTS 与记忆层不同步风险**：以 `content_hash` 为准，FTS 只作为检索加速，不作为事实来源。
