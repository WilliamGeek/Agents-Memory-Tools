# Token 计数口径对齐 CC Switch（迁移说明）

> 目标：以 CC Switch 已验证的「供应商真实用量」口径替代本项目原有的内容体积估算，修正重复计费与大幅低估。
> 变更文件：`web_app.py`、`tools/test_token_usage.py`（新增）
> 版本：2026-11-13 · `TOKEN_CACHE_VERSION = 4`

---

## 1. 改造前实现梳理

### 1.1 数据结构

`compute_session_tokens(fmt, session_id, file_path, mtime, size_bytes, ...)` 产出：

| 字段 | 含义 |
|---|---|
| `tokens` | 对外主口径：有记录值 = 输入+输出；否则为估算内容体积 |
| `input_tokens` / `output_tokens` | 仅 recorded 时有效 |
| `content_tokens` | 内容体积（去重后一次算完），不受重复发送影响 |
| `usage_source` | `recorded` / `estimated` |
| `calls` | 请求次数（recorded 时） |

缓存：`token_cache.json`，key = `fmt:session_id`，签名 = `v{版本}:mtime:size`。

### 1.2 各平台实际路径

| 平台 | 原逻辑 | 结果 |
|---|---|---|
| Antigravity | `_antigravity_recorded_usage`：解析 step protobuf 字段 5→9→(2,3,9) | recorded，准确 |
| Claude Code | `_claude_recorded_usage`：逐行累加 `message.usage` | **同一 message.id 多行重复累加** |
| WorkBuddy | 不走 recorded，按 JSONL 文本逐条 `estimate_text_tokens` | **忽略 `providerData.rawUsage`，严重低估** |
| Trae | 提问缓存 + tiktoken 估算 | estimated（正文加密，无记录值可用） |

### 1.3 发现的两个确定性缺陷

1. **Claude 重复计费**
   Claude Code 流式写盘时，同一条回复会落多行，每行都带同一份 `usage`。
   实测样本：逐行相加 `2,982,798`，按 `message.id` 去重后 `1,588,718`，**虚高 88%**。

2. **WorkBuddy 严重低估**
   旧逻辑完全忽略 `providerData.rawUsage`，只按文本体积估算。
   实测样本：估算 `765,892`，真实记录值 `120,034,317`，**低估约 157 倍**。
   原因：计费按「每次请求的完整上下文」累计，而文本体积只量了一次内容。

---

## 2. CC Switch 的计数方案（迁移来源）

源码：`src-tauri/src/services/session_usage_workbuddy.rs`、`session_usage.rs`

核心规则：

1. 一次模型请求的 `providerData.rawUsage` 记在该请求的**最后一个事件**上，事件 `id` 即请求 id；
2. `prompt_tokens` 为 OpenAI 口径，**已包含缓存命中**（`prompt_cache_hit_tokens + prompt_cache_miss_tokens == prompt_tokens`）；
3. `completion_tokens` 已包含思考 token（`completion_tokens_details.reasoning_tokens` 单独可取）；
4. 入库时按 `session_usage_dedup(request_id)` 永久回执去重；
5. 子代理目录 `<sessionId>/subagents/*.jsonl` 的请求计入父会话；
6. Claude 侧按 `message.id` 去重（`assistant_message_id`），缓存读写与输入分开存储。

---

## 3. 迁移方案与代码映射

| CC Switch 规则 | 本项目实现 |
|---|---|
| WorkBuddy `rawUsage` 逐请求采集 | 新增 `_workbuddy_recorded_usage()` |
| 事件 id 去重 | 以 `rec["id"]` 为 key 的字典去重，取总量最大的一条 |
| `prompt_tokens` 含缓存 | `input = prompt_tokens`（不重复加 cache） |
| 思考 token | `completion_tokens_details.reasoning_tokens` → `thoughts_tokens` |
| rawUsage 缺失回退 | 退回 agents SDK `usage.inputTokens/outputTokens`，按 `messageId` 去重 |
| Claude `message.id` 去重 | **不采用**：用户要求「真实值低于旧值时保留旧值」，Claude 维持逐行累计 |
| 无 id 记录 | 保持逐行累加，绝不丢数据 |
| 口径变更失效旧缓存 | `TOKEN_CACHE_VERSION` 3 → 4 |

**未迁移项**：CC Switch 的成本（USD）计算、缓存读写单价拆分、请求耗时估算。
本项目只展示 token，不做计费，因此不需要；`calls` 字段保留用于核对请求数。

---

## 4. 验证

### 4.1 单元测试（`tools/test_token_usage.py`，9/9 PASS）

| 用例 | 断言 |
|---|---|
| Claude 同 id 三行 | `calls=1`，`input=420`，`output=40` |
| Claude 不同 id | 正常累加 |
| Claude 无 id | 逐行累加（不丢数据） |
| WorkBuddy 同请求两行 | `calls=1`，`input=1000`，`output=50`，`thoughts=12` |
| WorkBuddy 多请求 | 正常累加 |
| WorkBuddy SDK 回退 | `input=300`，`output=30`，`thoughts=4` |
| 无用量字段 | 返回 `None`，回落估算 |
| tiktoken 基础 | 空串 0，中英文 > 0 |

### 4.2 真实会话对照

| 会话 | 旧口径 | 当前口径 | 结论 |
|---|---|---|---|
| Claude `bcc8d7fc…` | 2,982,798 | **2,982,798** | 维持旧值（用户决策：去重后变小，不回退） |
| WorkBuddy `fb0e2221…` | 765,892（内容估算） | **120,034,317**（493 次请求真实累计） | 修正 157 倍低估 |

### 4.3 回归门禁

```
tools/qa_regression.py            63/63 PASS
tools/selftest_services.py       107/107 PASS
tools/contract_baseline.py       15/15 PASS（接口结构只增不删）
```

### 4.4 用量来源分布（改造后）

```
antigravity  recorded 138 / estimated 3
claude       recorded   5 / estimated 79（多数旧会话本身无 usage 字段）
workbuddy    recorded 100 / estimated 9（无 rawUsage 的旧文件才估算）
trae         recorded   0 / estimated 43（正文加密，无记录值）
```

---

## 5. 性能影响

- 首次构建（冷缓存）：约 24s（WorkBuddy 16MB 级文件需要两遍扫描：真实用量 + 内容体积）
- 二次构建（缓存命中）：`X-Query-Ms` ≈ 10ms，页面总耗时 0.07s
- 缓存签名已升级为 `v3`，旧值自动失效，不会混用两套口径

---

## 6. 残余限制

1. **Trae 无真实用量**：正文在 SQLCipher 加密库，`state.vscdb` 只有提问缓存，只能估算。
2. **Claude 保留重复计数**：按用户决策不做 `message.id` 去重，同一请求多行会重复累计（实测样本去重后会从 2,982,798 降至 1,588,718）。如需精确值，把 `_claude_recorded_usage` 换回按 id 取最大的实现即可。
3. **Claude 旧会话无 usage**：2025 年前的记录不含 usage 字段，仍走估算。
4. **子代理会话**：本项目把 `subagents/*.jsonl` 作为独立会话索引，未并入父会话汇总（与 CC Switch 的父会话汇总口径不同，如需合并需单独改会话拓扑，不影响单会话计数准确性）。
5. **不做成本换算**：`tokens` 是唯一口径，不引入美元计价，避免汇率与价格表维护成本。
