# 会话删除审核清单（2026-11-17）

> 审核范围：Memory Tools 已接入的 Trae、Antigravity、Claude、Codex、WorkBuddy；**不含尚未接入的豆包**。
> 本清单只供审核，未执行任何删除。审核通过后再按第 6 节边界执行。

## 0. 结论

共清点 **487** 条会话（Trae 95、Antigravity 166、Claude 84、WorkBuddy 115、Codex 4、豆包 23 不计）。
确认 **44 条**在源数据中就没有任何助手正文，无法“格式化恢复”成 Antigravity / WorkBuddy 近期那种多事件形式；建议列入删除清单。
另有 **2 条 Trae 工作区提问历史**是共享 `state.vscdb` 的合成展示条目，**不建议删源**，只能从 Memory Tools 展示/索引中移除。
其余 418 条均有助手事件，不在删除范围。

## 1. 判定口径

- **不是**“文件大就有正文”：Antigravity 两条空壳分别为 3.0 MB、2.5 MB，但 `steps=0`，体积来自空闲页/元数据。
- **不是**“标题像早期就丢数据”：Trae 2026-05 共 18 条，其中 16 条有正常助手事件；缺失只发生在被取消/失败的具体会话。
- 判定为“无正文”必须同时满足：事件流无 `assistant`、底层消息表无助手正文、没有可替代的云/本地来源。

## 2. 修复可行性：为什么不能格式化恢复

### 2.1 Trae（14 条）

- `history_v2`：每个会话只有 `role=user` 的行；`server_history_info` 按 `conversation_id` 查也只有 `user` 角色（字符数 3.7k–11.9k，全是注入上下文）。
- `chat_turn.turn_status`：全部为 `canceled` 或 `failed`；`chat_message_general` 对应 assistant `message_id` 的 `content` 长度全为 0。
- `chat_message_task`：基本是 `{}`；仅 `6a1ed68b…`（2423 B）与 `6af56d56…`（1348 B）有 `plan_item`，内容是 `reasoning_content`/`finish`，**不是模型正文**。
- 结论：请求被取消/失败、模型没有产出，不是迁移或解析丢数据。没有可供“格式化”的助手消息。

### 2.2 Antigravity（2 条）

- 两条库均 `steps=0`，只有 `trajectory_meta`（`trajectory_type=4`）、`trajectory_metadata_blob`（633 B / 2523 B）、`parent_references`。
- 父引用指向的父会话库（`b30ee3de…`、`9ac48d5e…`、`92108c1b…`）在 conversations 目录中不存在；无其他库反向引用这两条。
- 结论：孤立的子轨迹空壳，没有可恢复的会话步骤。

### 2.3 Claude / Codex / WorkBuddy（28 条）

- Claude 26 条：JSONL 只有 `system`、`user`、`attachment`、`permission-mode`、`file-history-snapshot`、`last-prompt` 等，**没有 `assistant` 类型事件**；其中多条是 `/status`、`/model`、`cd` 等本地命令会话或未获回复的“你好”测试。
- Codex 1 条：只有 `developer`/`user`，无 `assistant`。
- WorkBuddy 1 条：只有 1 条 `user`，无 `assistant`。
- 结论：没有助手正文可恢复；但都是独立文件，删除边界清晰。

## 3. A. 建议删除：44 条

### 3.1 Trae（14 条，共享加密库）

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `6a154edb3ede02e15be919fa` | 2026-05-26 · 请在本地文件系统的D:\\VS Code Creation目录下创建一个名为Label_Stud… | 2026-05-26 07:42 | 1 | 260 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 2 | `6a155800d0910ac82b89e01e` | 2026-05-26 · 请在本地文件系统的D:\\VS Code Creation目录下创建一个名为Label_Stud… | 2026-05-26 08:23 | 1 | 260 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 3 | `6a1ed64bd06f67392fde1387` | 2026-06-02 · 查看并解析 https://quant-assistant.com/ 这个项目，看看能否尝试在本… | 2026-06-02 13:11 | 1 | 53 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 4 | `6a1ed68bd06f67392fde1397` | 2026-06-02 · 查看并解析 https://quant-assistant.com/ 这个项目，看看能否尝试在本… | 2026-06-02 13:12 | 1 | 64 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 5 | `6a27f1be51651399edbe3235` | 2026-06-09 · 针对位于本地路径"F:\\Git\\WebAI2API"的LLM逆向工程项目（该项目源自 htt… | 2026-06-09 14:55 | 1 | 275 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 6 | `6a28295a51651399edbe3810` | 2026-06-09 · 针对位于本地路径"F:\\Git\\WebAI2API"的LLM逆向工程项目（该项目源自 htt… | 2026-06-09 14:56 | 1 | 304 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 7 | `6a729dec9c1f2636a78ea450` | 2026-08-05 · 读取并了解我本地的F:\Git\WebAI2API 这个项目 | 2026-08-05 02:20 | 1 | 30 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 8 | `6a72b0be9c1f2636a78ea61b` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 03:50 | 2 | 400 | 733925376 | assistant=0；chat_turn=canceled×1 / failed×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 9 | `6a72b3359c1f2636a78ea63f` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 03:51 | 5 | 1045 | 733925376 | assistant=0；chat_turn=canceled×1 / failed×4；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 10 | `6a72b3cb9c1f2636a78ea67c` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 03:57 | 2 | 418 | 733925376 | assistant=0；chat_turn=failed×2；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 11 | `6a72c4599c1f2636a78ea701` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 05:04 | 1 | 209 | 733925376 | assistant=0；chat_turn=canceled×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 12 | `6a72c4dc9c1f2636a78ea70b` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 05:06 | 3 | 627 | 733925376 | assistant=0；chat_turn=canceled×2 / failed×2；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 13 | `6a72c6cf8c0da518f91d81c9` | 2026-08-05 · https://github.com/rosemarycox5334-debug/AlphaMa… | 2026-08-05 05:15 | 3 | 627 | 733925376 | assistant=0；chat_turn=canceled×2 / failed×1；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db` |
| 14 | `6af56d56c45c74fabe26580a` | 2026-11-12 · 测试任务 | 2026-11-12 07:40 | 4 | 8 | 733925376 | assistant=0；chat_turn=failed×4；chat_message_general 助手 content 长度=0 | `C:\Users\HP\AppData\Roaming\Trae CN\ModularData\ai-agent\database.db；memento=C:\Users\HP\AppData\Roaming\Trae CN\User\workspaceStorage\ba0d38c09fdf6c4fb4260089a0f62e5c\state.vscdb` |

> 注意：这 14 条不是 14 个独立文件。它们的行分布在 733,925,376 B 的 `database.db` 中，同一库还承载其他 79 条正常会话；**不能删整库**。
> `6af56d56…` 还在 `C:\Users\HP\AppData\Roaming\Trae CN\User\workspaceStorage\ba0d38c09fdf6c4fb4260089a0f62e5c\state.vscdb` 的 memento 列表中，删除时必须一并移除该列表项。

### 3.2 Antigravity（2 条，独立 .db）

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `a3eacf19-a19c-4625-b1a7-09d992e6fe35` | 2026-10-16 · 会话_a3eacf19 | 2026-10-16 12:23 | 0 | 0 | 2609152 | steps=0；trajectory_metadata_blob=2523B；父引用 92108c1b 对应的父库不存在；catalog status=corrupt | `C:\Users\HP\.gemini\antigravity\conversations\a3eacf19-a19c-4625-b1a7-09d992e6fe35.db` |
| 2 | `59acfccc-0b0b-42ea-88b5-987800ed15f1` | 2026-10-27 · Optimize Agent Session UI | 2026-10-27 15:58 | 0 | 0 | 3145728 | steps=0；trajectory_metadata_blob=633B；父引用 b30ee3de / 9ac48d5e 对应的父库不存在；catalog status=corrupt | `C:\Users\HP\.gemini\antigravity\conversations\59acfccc-0b0b-42ea-88b5-987800ed15f1.db` |

### 3.3 Claude（26 条，独立 .jsonl）

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `92b35ee2-dc27-4cea-9815-e3a270f358f7` | 2026-04-25 · 你好 | 2026-04-25 15:21 | 17 | 11510 | 11510 | assistant=0；17 行；类型 {'permission-mode': 2, 'system': 11, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\92b35ee2-dc27-4cea-9815-e3a270f358f7.jsonl` |
| 2 | `ef2ecccd-dd97-40d1-8b45-a6ec4c781a29` | 2026-04-25 · 你好 | 2026-04-25 16:43 | 18 | 12537 | 12537 | assistant=0；18 行；类型 {'permission-mode': 2, 'system': 11, 'file-history-snapshot': 1, 'user': 1, 'attachment': 2, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\ef2ecccd-dd97-40d1-8b45-a6ec4c781a29.jsonl` |
| 3 | `0da015a4-aa92-440e-977a-0f0741b0ae1a` | 2026-04-26 · 你好 | 2026-04-26 09:15 | 13 | 8157 | 8157 | assistant=0；13 行；类型 {'permission-mode': 2, 'system': 7, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\0da015a4-aa92-440e-977a-0f0741b0ae1a.jsonl` |
| 4 | `61f087f1-5415-45f5-a156-f7fa2479af2b` | 2026-04-26 · 你好 | 2026-04-26 09:16 | 18 | 11054 | 11054 | assistant=0；18 行；类型 {'permission-mode': 2, 'system': 10, 'file-history-snapshot': 2, 'user': 2, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\61f087f1-5415-45f5-a156-f7fa2479af2b.jsonl` |
| 5 | `9cbc513f-9c4b-491e-a127-52216a4732b7` | 2026-04-26 · 你好 | 2026-04-26 09:17 | 16 | 10855 | 10855 | assistant=0；16 行；类型 {'permission-mode': 1, 'system': 10, 'file-history-snapshot': 2, 'user': 2, 'attachment': 1} | `C:\Users\HP\.claude\projects\G----\9cbc513f-9c4b-491e-a127-52216a4732b7.jsonl` |
| 6 | `b813c058-c7f0-4163-830b-b918b4a2c7c9` | 2026-04-26 · 你好 | 2026-04-26 09:25 | 12 | 7815 | 7815 | assistant=0；12 行；类型 {'permission-mode': 2, 'system': 6, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\b813c058-c7f0-4163-830b-b918b4a2c7c9.jsonl` |
| 7 | `e5da58ec-8a41-4ac3-9f33-36b41cbb6f9f` | 2026-04-26 · 你好 | 2026-04-26 09:26 | 11 | 7165 | 7165 | assistant=0；11 行；类型 {'permission-mode': 2, 'system': 5, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\e5da58ec-8a41-4ac3-9f33-36b41cbb6f9f.jsonl` |
| 8 | `3d4e09eb-07f6-4468-a710-d3d7fe63d707` | 2026-04-26 · 你好 | 2026-04-26 09:44 | 13 | 8462 | 8462 | assistant=0；13 行；类型 {'permission-mode': 2, 'system': 7, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\3d4e09eb-07f6-4468-a710-d3d7fe63d707.jsonl` |
| 9 | `6eb715d1-59cd-4b14-b218-33734687083b` | 2026-04-26 · 你好 | 2026-04-26 10:18 | 12 | 7816 | 7816 | assistant=0；12 行；类型 {'permission-mode': 2, 'system': 6, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\6eb715d1-59cd-4b14-b218-33734687083b.jsonl` |
| 10 | `e2b80b0b-6545-4f58-9282-728bcc0f2289` | 2026-04-26 · 你好‘ | 2026-04-26 10:21 | 10 | 6524 | 6524 | assistant=0；10 行；类型 {'permission-mode': 2, 'system': 4, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----\e2b80b0b-6545-4f58-9282-728bcc0f2289.jsonl` |
| 11 | `4a7cc2e9-6f47-425c-b25f-60fc1223f2f9` | 2026-04-26 · 好 | 2026-04-26 10:29 | 14 | 10207 | 10207 | assistant=0；14 行；类型 {'permission-mode': 1, 'system': 10, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1} | `C:\Users\HP\.claude\projects\G----\4a7cc2e9-6f47-425c-b25f-60fc1223f2f9.jsonl` |
| 12 | `3d960cd1-aa10-4726-87d3-6b73044a27a7` | 2026-04-26 · 你好 | 2026-04-26 11:25 | 25 | 13794 | 13794 | assistant=0；25 行；类型 {'permission-mode': 2, 'file-history-snapshot': 5, 'user': 8, 'attachment': 1, 'queue-operation': 2, 'system': 6, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\3d960cd1-aa10-4726-87d3-6b73044a27a7.jsonl` |
| 13 | `fcc3db47-9e6e-45f5-aabc-8da240aa567d` | 2026-04-26 · 你好 | 2026-04-26 16:14 | 24 | 15602 | 15602 | assistant=0；24 行；类型 {'permission-mode': 1, 'system': 14, 'file-history-snapshot': 3, 'user': 5, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\fcc3db47-9e6e-45f5-aabc-8da240aa567d.jsonl` |
| 14 | `ab1cf448-7dfd-4e53-970d-72945278c7ff` | 2026-04-26 · 你好 | 2026-04-26 16:17 | 9 | 7034 | 7034 | assistant=0；9 行；类型 {'permission-mode': 1, 'system': 5, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\ab1cf448-7dfd-4e53-970d-72945278c7ff.jsonl` |
| 15 | `51789f71-73e6-48ac-a6d3-10118ed3b167` | 2026-04-26 · 你好d | 2026-04-26 16:46 | 14 | 9397 | 9397 | assistant=0；14 行；类型 {'permission-mode': 1, 'system': 6, 'file-history-snapshot': 2, 'user': 4, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\51789f71-73e6-48ac-a6d3-10118ed3b167.jsonl` |
| 16 | `5995dd11-a050-4692-905c-e493455e40e8` | 2026-04-26 · 斜杠命令：/model | 2026-04-26 16:58 | 5 | 2055 | 2055 | assistant=0；5 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 3} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\5995dd11-a050-4692-905c-e493455e40e8.jsonl` |
| 17 | `08c1c302-db91-42ad-94d8-04b9282004c5` | 2026-04-26 · 你好 | 2026-04-26 17:56 | 10 | 7694 | 7694 | assistant=0；10 行；类型 {'permission-mode': 1, 'system': 6, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\08c1c302-db91-42ad-94d8-04b9282004c5.jsonl` |
| 18 | `37087c9b-eb2b-4c1d-9040-e3c53a3ae5ea` | 2026-04-26 · 你好 | 2026-04-26 19:52 | 7 | 5850 | 5850 | assistant=0；7 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 1, 'attachment': 2, 'system': 2} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\37087c9b-eb2b-4c1d-9040-e3c53a3ae5ea.jsonl` |
| 19 | `861fe039-0017-422f-920b-2150612787b6` | 2026-04-26 · 你 | 2026-04-26 20:04 | 11 | 8043 | 8043 | assistant=0；11 行；类型 {'permission-mode': 1, 'file-history-snapshot': 2, 'user': 2, 'attachment': 1, 'system': 5} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\861fe039-0017-422f-920b-2150612787b6.jsonl` |
| 20 | `58b27b9d-5cc5-4ab5-bee6-a1a3953c2e91` | 2026-04-26 · nihoa | 2026-04-26 20:20 | 6 | 5060 | 5060 | assistant=0；6 行；类型 {'permission-mode': 1, 'system': 2, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\58b27b9d-5cc5-4ab5-bee6-a1a3953c2e91.jsonl` |
| 21 | `b792c01e-36ed-4e7b-8d0c-8a4b4b64bbf5` | 2026-04-26 · 你好 | 2026-04-26 23:15 | 4 | 3744 | 3744 | assistant=0；4 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 1, 'attachment': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\b792c01e-36ed-4e7b-8d0c-8a4b4b64bbf5.jsonl` |
| 22 | `b72c04fa-58a5-4220-b04c-09ac59eccd19` | 2026-04-27 · 斜杠命令：/effort | 2026-04-27 00:28 | 5 | 2142 | 2142 | assistant=0；5 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 3} | `C:\Users\HP\.claude\projects\C--Users-HP--claude-code-router\b72c04fa-58a5-4220-b04c-09ac59eccd19.jsonl` |
| 23 | `a56fba2f-9a4e-4b4e-aef1-858d03b64999` | 2026-04-27 · 斜杠命令：/effort | 2026-04-27 01:33 | 5 | 2097 | 2097 | assistant=0；5 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 3} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\a56fba2f-9a4e-4b4e-aef1-858d03b64999.jsonl` |
| 24 | `bcd965d4-224a-4881-b699-002c07141bee` | 2026-04-27 · 你好 | 2026-04-27 12:20 | 16 | 10149 | 10149 | assistant=0；16 行；类型 {'permission-mode': 2, 'file-history-snapshot': 2, 'user': 4, 'attachment': 1, 'system': 6, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\G----------------\bcd965d4-224a-4881-b699-002c07141bee.jsonl` |
| 25 | `534d6028-e6fd-4e66-826b-7b773e5c2745` | 2026-05-09 · 命令：cd D:\VS Code Creation\R语言深度学习实验作业 | 2026-05-09 16:30 | 11 | 4001 | 4001 | assistant=0；11 行；类型 {'permission-mode': 2, 'file-history-snapshot': 2, 'user': 6, 'last-prompt': 1} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\534d6028-e6fd-4e66-826b-7b773e5c2745.jsonl` |
| 26 | `a336a2a4-c5ae-4eef-aba9-b8b5f7d534ab` | 2026-05-10 · 斜杠命令：/model | 2026-05-10 10:37 | 5 | 2072 | 2072 | assistant=0；5 行；类型 {'permission-mode': 1, 'file-history-snapshot': 1, 'user': 3} | `C:\Users\HP\.claude\projects\d--VS-Code-Creation\a336a2a4-c5ae-4eef-aba9-b8b5f7d534ab.jsonl` |

### 3.4 Codex（1 条会话，4 个文件副本）

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `01a1cf1a-1068-7cd0-8308-fabc3a42468e` | 2026-11-12 · 你好 | 2026-11-12 17:40 | 16 | 61633 | 61633 | assistant=0；16 行；类型 {'developer': 2, 'user': 2} | `C:\Users\HP\.codex\sessions\2026\11\12\rollout-2026-11-12T17-40-11-01a1cf1a-1068-7cd0-8308-fabc3a42468e_01a1cf21-09eb-7502-b702-596f2ffd6af4.jsonl` |

> 这条在 catalog 中有 **4 个文件副本**，必须全部删除才算无残留：
> `C:\Users\HP\.codex\sessions\2026\11\12\rollout-2026-11-12T17-32-34-01a1cf1a-1068-7cd0-8308-fabc3a42468e.jsonl`；
> `C:\Users\HP\.codex\sessions\2026\11\12\rollout-2026-11-12T17-40-11-01a1cf1a-1068-7cd0-8308-fabc3a42468e_01a1cf21-09eb-7502-b702-596f2ffd6af4.jsonl`；
> `F:\Codex\sessions\2026\11\12\rollout-2026-11-12T17-32-34-01a1cf1a-1068-7cd0-8308-fabc3a42468e.jsonl`；
> `F:\Codex\sessions\2026\11\12\rollout-2026-11-12T17-40-11-01a1cf1a-1068-7cd0-8308-fabc3a42468e_01a1cf21-09eb-7502-b702-596f2ffd6af4.jsonl`。
> 两个文件内容不同（17-32-34 为 60,534 B，17-40-11 为 61,633 B），但都只有 developer/user、没有 assistant；因此整组都是空壳。

### 3.5 WorkBuddy（1 条，独立 .jsonl）

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `9c507081-5f07-447a-9b6d-7d2131b00aec` | 2026-10-29 · 用 video-to-mindmap 技能生成 Opus 拆解视频思维导图 | 2026-10-29 18:46 | 5 | 12339 | 12339 | assistant=0；5 行；类型 {'user': 1} | `C:\Users\HP\.workbuddy\projects\d-WorkBuddy Date-2026-10-29-18-46-16\9c507081-5f07-447a-9b6d-7d2131b00aec.jsonl` |

## 4. B. 不建议删除：2 条 Trae 工作区提问历史

| # | 会话 ID | 标题 | 时间 | 记录 | 内容字节 | 源文件字节 | 证据 | 源文件 |
|---|---|---|---|---|---|---|---|---|
| 1 | `ws_38c6af59119361a7` | 2026-08-25 · Trae 工作区提问历史 (ws_38c6a) · 1 条 | 2026-08-25 12:00 | 1 | 1609 | 28672 | 合成条目：1 条工作区提问；源为共享 state.vscdb 的 icube-ai-agent-storage-input-history | `C:\Users\HP\AppData\Roaming\Trae CN\User\workspaceStorage\38c6af59119361a775fda84764981d5d\state.vscdb` |
| 2 | `6af138b73c031baea7f9a9a4` | 2026-11-09 · Trae 工作区提问历史 (.ssh) · 89 条 | 2026-11-09 03:06 | 89 | 38104 | 335872 | 合成条目：89 条工作区提问；无助手正文，但属于输入历史快照；源为共享 state.vscdb 的 icube-ai-agent-storage-input-history | `C:\Users\HP\AppData\Roaming\Trae CN\User\workspaceStorage\ba0d38c09fdf6c4fb4260089a0f62e5c\state.vscdb` |

这两条不是真实会话，而是 Memory Tools 从共享 `state.vscdb` 的 `icube-ai-agent-storage-input-history` 合成的“工作区提问历史”条目。
删掉源键会同时删除该工作区的输入历史，可能影响 Trae 自身的输入框历史；建议只在 Memory Tools 中隐藏/清索引，不动 `state.vscdb`。

## 5. 明确排除

- **6 条极短但有助手正文的 Trae 会话**：`6a2abc2a…`（你好/14 B）、`6a729e5b…`（777 B）、`6a72ca8e…`（423 B）、`6a8d0721…`（146 B）、`6aefdbe4…`（720 B）、`6a72dae0…`（4337 B）——都有真实助手内容，不列入。
- **WorkBuddy 的失败会话**：如 `8a1af3a6…` 有 `assistant` 角色，但正文是“所有候选都失败: …”错误说明；属于真实错误回复，不是空壳，不列入。
- **豆包 23 条**：尚未接入，按要求不纳入本轮删除。

## 6. 删除执行边界（审核通过后）

1. **Claude / Codex / WorkBuddy / Antigravity**：可删除各自独立会话文件；同时清 catalog 行与 FTS 中对应 `session_id` 的索引。
2. **Trae 14 条**：源是共享加密库，当前环境没有 `sqlcipher` CLI，也没有 `pysqlcipher3`/`sqlcipher3` 驱动，无法安全地按 session 写回加密库。可选：
   - **推荐**：先做逻辑删除（从 Memory Tools 列表/搜索/快照排除，并清 FTS）——界面无残留，但加密库物理行仍在，重新解密会再次出现；
   - **彻底物理删除**：需要引入 SQLCipher 写入能力（或对整库解密→改明文→按原参数重加密），并先停 Trae，风险高，需单独授权；
   - **不要**直接删 `database.db`，会连带删除其他 79 条正常会话。
3. **Trae 2 条工作区历史**：只移除展示/索引，不删 `state.vscdb`。
4. **catalog / FTS**：Claude/Codex/Antigravity 有 catalog 行；Trae 无 catalog 行，但有 93 个 `trae_db://` FTS 索引键。删除后要清 `conversation_fts` 对应 `session_id` 与 `fts_file_meta` 对应键。
5. **快照**：删除后清 `cache/sessions_snapshot.json.gz` 或重启服务，确保列表不再出现。

## 7. 删除后的验收

- `GET /api/status`：总数应从 487 降到 443（若 44 条全部删除）；豆包 23 条不变。
- `GET /api/search/content?q=<被删会话标题>`：0 命中。
- Trae FTS：`SELECT COUNT(*) FROM conversation_fts WHERE session_id IN (...)` 为 0；`fts_file_meta` 中 `trae_db://<sid>` 为 0。
- Antigravity/Claude/Codex/WorkBuddy：源文件不存在、catalog 无对应行、详情接口 404。
- Trae 加密库物理行若未删，必须明确告知“仅逻辑删除”，不能宣称“无残留”。

## 8. 证据与复现

- 全平台清点：`.tmp\all_sessions_inventory.json`（487 条，format/title/records/bytes）。
- Trae 清点：`.tmp\trae_inventory.json`（95 条，events/in_db/jsonl/input_history）。
- Trae 交叉核验：`.tmp\_trae_missing_confirm.py`（`server_history_info`、`chat_message_general`、`chat_message_task`）。
- Antigravity：`.tmp\_ag_probe.py`、`.tmp\_ag_blob_probe.py`、`.tmp\_ag_parent_check.py`。
- 原始助手事件审计：`.tmp\_raw_assistant_audit.py` → `.tmp\raw_assistant_audit.json`。
- 本清单 CSV：`docs\deletion-review-2026-11-17.csv`（含完整源路径，可直接筛选/核对）。
