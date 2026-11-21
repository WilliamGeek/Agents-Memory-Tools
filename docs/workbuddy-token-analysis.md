# WorkBuddy Token 统计口径与子代理归集

日期：2026-11-21

## 结论

WorkBuddy 的 33.56 亿 Tokens 不是消息重复统计，也不是父子会话把同一批请求算了两遍，而是**累计 prompt（输入）Tokens 的供应商口径**：每次模型请求都会把当前完整上下文计入 `prompt_tokens`，其中绝大部分是缓存命中的重复上下文。WorkBuddy 的缓存命中率约 98.1%，所以卡片上的数字很大，但真正新增的输入并不多。

子代理是独立请求，确实会累加，但只占总量的 7.84%，不是 WorkBuddy 数值最高的主因；父子会话也没有共享请求 ID，不存在同一请求被两层重复计费。

## 三个口径

| 口径 | 含义 | WorkBuddy 数值 |
| --- | --- | ---: |
| 累计 Tokens | 每次请求的 `prompt_tokens + completion_tokens` 求和，含缓存命中 | 3,356,274,836 |
| 内容体积 `content_tokens` | 对会话里实际出现的消息/工具内容做一次去重估算，不受重复发送影响 | 21,959,433 |
| 有效总量 `fresh_tokens` | 缓存未命中输入 + 模型输出 | 74,286,426 |

拆开看：

- 输入：3,345,033,983
- 输出：10,753,876
- 缓存命中：3,281,501,433，占输入 98.1%
- 缓存未命中：63,532,550
- 模型请求：约 15,526 次

按累计口径，WorkBuddy 是全部平台里最高的；按内容体积，Antigravity 约 205.36M，WorkBuddy 只有约 21.96M；按有效总量，WorkBuddy 约 74.29M，仍低于 Antigravity 的 498.87M。差别来自口径，不是数据源错误。

## 子代理到底占多少

WorkBuddy 共有 115 个 jsonl 会话，其中 82 个顶层父会话、33 个子代理会话，分布在 8 个父会话下。子代理路径固定为：

```text
C:\Users\HP\.workbuddy\projects\<project>\<parent-sid>\subagents\agent-*.jsonl
```

子代理合计：

- 累计 Tokens：263,059,355，占 WorkBuddy 总量的 7.84%
- 内容体积：4,278,081，占 19.5%
- 有效总量：6,982,728，占总有效量的约 9.4%

对 33 组父子文件比较 `providerData.rawUsage` 的请求事件 `id`，**0 组存在共享 id**。也就是说，父子文件没有把同一批请求重复计费，子代理的 263M 是额外真实请求。

## 最大单会话为什么能到 5.3 亿

`转录组新论文质控 -> clean reads`：

- 累计 Tokens：531,639,377
- 内容体积：1,447,430
- 缓存命中：516,536,000（97.3%）
- 缓存未命中：14,156,997
- 输出：946,380
- 有效总量：15,103,377
- 记录：5,393 条；模型请求：1,745 次

这个会话只有约 1.45M 的内容，但进行了 1,745 次请求，每次请求都携带不断增长的完整上下文，所以累计 prompt 被放大。缓存命中让供应商计费变便宜，但不会让 `prompt_tokens` 统计变小。

## `<teammate-message>` 卡片是什么

那些标题以 `<teammate-message teammate_id="team-lead" summary="Initial t...` 开头的卡片，就是子代理会话，不是普通用户会话。子代理 jsonl 的第一条 `role=user` 记录是 team-lead 注入的 XML 派发消息，旧标题提取逻辑把整段 XML 当成了标题。

修复后：

- 通过 `subagents` 路径识别父子关系，子代理写 `is_child=True`、`parent_id`、`parent_title`、`agent_name`
- 父会话写 `children`、`children_count`
- 前端把子代理收进父卡片的“下属子代理会话”抽屉，不再单独占卡片
- 标题优先使用 `summary`，去掉 `Initial task assignment for ` 前缀，显示为 `子代理 · mvp-dev-expert-team-architect` 这类可读名称
- 普通任务仍使用任务正文首行

当前 WorkBuddy 顶层会话 82 个、子代理 33 个；API 列表的 `stats` 返回 `top_level_total=82`、`child_total=33`，头部“匹配”数按顶层会话计算，不再受前端分页影响。

## 展示层修正

- 卡片主数字标签改为“累计 Tokens”，不再让人误以为是内容体积
- tooltip 增加：
  - 缓存命中（重复上下文）
  - 缓存未命中（新输入）
  - 有效总量（未命中 + 输出）
  - 内容体积（去重）
- 快照增加 `SNAPSHOT_SCHEMA_VERSION=2`，旧快照缺字段时自动丢弃重建，避免升级后缓存字段为 null
- lite 字段白名单补入 `content_tokens`、`cache_read_tokens`、`cache_miss_tokens`、`fresh_tokens`

## 复现入口

```text
GET /api/sessions?format=workbuddy&sort_by=tokens&order=desc&limit=3
GET /api/session/children?catalog_id=wb_<session_id[:16]>
```

列表返回的 `stats` 包含 `tokens`、`bytes`、`top_level_total`、`child_total`；单会话包含 `tokens`、`content_tokens`、`cache_read_tokens`、`cache_miss_tokens`、`fresh_tokens`、`usage_source`、`children_count`。
