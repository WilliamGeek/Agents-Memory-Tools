# 豆包「最近活跃 / 创建时间」排序修复记录（2026-11-21）

## 现象

同一 IndexedDB 文件下的多个豆包会话在“最近活跃”里显示同一时间，例如
`38448461787364866` 与 `38453438817435650` 都是 `2026-11-21 13:36`；
用户截图里两者同时显示 `13:32`，真正更旧的会话被错误抬到首屏。

## 根因

1. `services/doubao_idb.py` 的会话元数据解析原先用
   `update_time".([0-9]{10,13})`。豆包原始记录中字段名后是类型字节，
   常见为换行；正则 `.` 默认不匹配换行，导致大量会话 `ts=0`。
2. `web_app.get_doubao_sessions()` 随后用 `item.get("ts") or idb_mtime`，
   所有缺时间的 IndexedDB 会话共用了整个 LevelDB 文件的 `mtime`。
3. 云端同步只保存 `update_time`，`started_at` 与 `mtime` 都赋同一个值，
   导致“创建时间”和“最近活跃”几乎相同。

## 修复

- `services/doubao_idb.py`
  - 新增 `_seconds()` / `_meta_time()`，兼容换行类型字节、秒与毫秒；
  - `_parse_conversations()` 分别保存 `created_at`、`last_active`；
  - `_parse_task_meta()` 记录每个会话的任务态时间；
  - 当前打开会话只从主 `Default` profile 取，避免被 `Profile 1` 覆盖；
  - `load()` 合并会话和任务态时间。
- `web_app.py`
  - 云端条目使用 `created_at` / `last_active`，并合并同 cid 的 IDB 元数据；
  - IndexedDB 条目默认使用自身 `last_active`；
  - **只有 active 会话**才允许用 `idb_mtime` 提升 `last_active`。
- `tools/doubao_sync.py`
  - 规范化写入 `created_at` 与 `last_active`；
  - 无 `create_time` 时回退到首条消息时间；
  - manifest 同步保存这些字段。
- `services/snapshot.py`
  - `mtime` / `started_at` 排序在相同时间下追加 `records` 作为稳定 tie-break。

## 验证

以最终运行版 `127.0.0.1:18923` 为准：

```text
/api/sessions?format=doubao&sort_by=mtime&order=desc&limit=1000
目标 38453438817435650 名次：1
旧会话 38448461787364866 名次：229
第五人格会话 38454847167419394 名次：5

/api/sessions?format=doubao&sort_by=started_at&order=desc&limit=1000
目标 38453438817435650 名次：72
```

GUI 首屏（`docs/dag/../../.testdata/gui-final.png`）：
目标卡片显示 `2026-11-21 14:22`、45 步，排在首屏第一；
`D老师项目会话复盘与交接` 第二，`AstrBot_NapCat_配置审计` 第三。

## 边界

- “当前打开会话”只能由主 profile 的最后一个 `mainTaskDataMap` 推断；
  如果同时打开多个豆包窗口，无法从 LevelDB 稳定判定“哪个窗口最前”。
- 旧云端缓存若没有 `create_time` 且消息没有独立时间，创建时间只能回退到
  `update_time`；重新执行 `tools/doubao_sync.py --full` 可补首条消息时间。
- 切换“创建时间”时目标会明显下沉，这是预期行为；两个排序不再是同一口径。
