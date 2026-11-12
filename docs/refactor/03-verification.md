# 本轮改造独立回归验证报告

| 项 | 值 |
|---|---|
| 验证人 | QA 工程师 严过关（software-qa-engineer，独立于实现方） |
| 验证对象 | 后端 `http://127.0.0.1:18922`（改造后版本，进程未重启）；前端 `frontend/` |
| 基线来源 | `docs/refactor/baseline.json`（改造前实测）＋ `_s.json` / `_big.json`（改造前响应快照） |
| 契约基线 | `docs/refactor/contract-baseline.json`（captured_at `2026-11-12T01:48:55`，早于代码改动时间） |
| 新增测试资产 | `tools/qa_regression.py`（只读回归脚本，不触碰业务代码） |
| 报告时间 | 2026-11-12 |
| 环境约束 | 本机 `curl` 一律加 `--noproxy '*'`；`tools/*.py` 的 `DEFAULT_BASE` 是 `18923`，**必须显式传 `--base 18922`** |

---

## 1. 结论表

### 1.1 必测项（16 项）

| 分组 | 必测项 | 结果 | 一句话结论 |
|---|---|---|---|
| A 向后兼容 | A1 `/api/sessions` 不传参字段只增不减、`count` 语义不变 | **PASS** | 行字段逐一相同，顶层新增 6 个键，`count == len(sessions)` 两侧成立 |
| | A2 旧单页 `/` 仍返回 200 且含 `sessionsGrid` | **PASS** | 200 / 248,586 B / `sessionsGrid` ×3 |
| | A3 `contract_baseline.py --check` | **PASS** | 15/15 接口结构兼容 |
| | A4 自检护栏 `--mutate-drop file_path` 必须非 0 | **PASS** | 退出码 1，3/15 报「字段缺失」——护栏确实会变红 |
| B 性能 | B5 列表 `limit=60&fields=lite` ≤50 KB | **PASS** | 34,545 B（预算的 67.5%） |
| | B6 详情 `turn_limit=8` ≤400 KB | **PASS** | 355,415 B（预算的 86.8%） |
| | B7 详情二次请求（LRU 命中）≤250 ms | **PASS** | avg 30.7 ms / p95 31.4 ms |
| | B8 `If-None-Match` 二次请求必须 304 且 body=0 | **PASS** | 304 / 0 B / 20.7 ms |
| C 功能 | C9 分页翻页无重复无遗漏、末页 `has_more=false` | **PASS** | 7 页 364 条，重复 0，`[60,60,60,60,60,60,4]` |
| | C10 分片 `turns` / `turn_index` 可拼成完整 12 轮 | **PASS**（见 §5.2 口径修正） | 1–8 + 9–12 严格拼接；默认预算下顺序推进亦覆盖 1–12 |
| | C11 `events_total_raw=6635` 而 `events_shipped≈396`，无 `opaque` | **PASS** | 6635 → 396；响应体内 `"opaque"` 字面量为 0 |
| | C12 详情内检索命中 5 条且全属该 catalog_id | **PASS** | `count=5`，5 个命中轮次正文均含 `git` |
| | C13 `/api/session/children?catalog_id=b20148aa815d4fbd` 返回 3 个 | **PASS** | `children_count=3`，3 条互不重复 |
| | C14 边界参数不得 500 | **PASS**（Round 2 修复后） | Round 1 曾 FAIL：非法 `catalog_id` 走 `/api/session/search` 返回 500；Engineer 修复 `web_app.py:3315` 后复测 **404**，其余 15 个边界用例一直通过 |
| D 前端 | D15 `npx tsc --noEmit` 零错误 | **PASS** | 退出码 0，无输出 |
| | D16 前端确实改调 `/api/session/search` 与 `/api/session/children` | **PASS** | 详情检索与子会话均已切新端点；`/api/search/content` 仅剩全局检索在用 |

**必测项计数：PASS 16 / FAIL 0**（Round 1 首次为 15/1，唯一失败项 C14 已修复并复测通过，详见 §8）

### 1.2 断言级计数（73 条）

| 分组 | 断言数 | Round 1 PASS | Round 1 FAIL | **Round 2（终态）** |
|---|---|---|---|---|
| A 向后兼容 | 4 | 4 | 0 | **4/4 PASS** |
| B 性能 | 4 | 4 | 0 | **4/4 PASS** |
| C 功能正确性（C9–C14） | 63 | 62 | 1 | **63/63 PASS** |
| D 前端静态核查 | 2 | 2 | 0 | **2/2 PASS** |
| **合计** | **73** | 72 | 1 | **73/73 PASS** |

Round 1 唯一失败断言：`C14 非法 catalog_id（search）→ 非 500`（实测 500）。
Round 2 该断言实测 **404**，全量 73 条断言零失败。

### 1.3 智能路由判定

| 判定 | 内容 |
|---|---|
| **Round 1 路由目标** | **Engineer（software-engineer）** —— 存在 **1 个**源码缺陷 |
| 缺陷 | `web_app.py:3309-3317`，`/api/session/search` 把 `DetailError(404)` 吞成 500 |
| **Round 2 复测** | Engineer 已修复（`web_app.py:3315-3322`），复测 **PASS** |
| **Round 3（D-2/D-3 复验）** | D-2 列表 ETag **已修复**；D-3 前端轮号 **已修复**；63/63 断言 PASS |
| **终态路由** | **NoOne** —— 无未决源码缺陷 |
| 自修项 | **3 处**测试脚本问题（C10 分片口径 / C12.6 匹配语义 / B8 的 304 单样本阈值），均已自行修正，不占源码缺陷额度 |
| 业务代码改动 | **0 行**（仅改测试资产 `tools/qa_regression.py`、`tools/bench_api.py`） |

> 收尾：18922 已由 Engineer 于 08:31 前后重启，**D-1 已上线**（实测 404）。重启窗口期的
> 瞬时 500 已记为 R10。

---

## 2. A 向后兼容（4/4 PASS）

### A1 `/api/sessions` 不传参：字段只增不减，`count` 语义不变

```bash
curl -s --noproxy '*' -o .tmp/qa_s_all.json \
  -w "status=%{http_code} bytes=%{size_download} time=%{time_total}\n" \
  "http://127.0.0.1:18922/api/sessions"

# 与改造前快照 _s.json 做字段集合比对
.venv/Scripts/python.exe -c "
import json
o=json.load(open('_s.json',encoding='utf-8')); n=json.load(open('.tmp/qa_s_all.json',encoding='utf-8'))
f=lambda rs:{k for r in rs for k in r}
print('row-fields missing-in-new :', sorted(f(o['sessions'])-f(n['sessions'])))
print('row-fields added-in-new   :', sorted(f(n['sessions'])-f(o['sessions'])))
print('top-keys old:', sorted(o)); print('top-keys new:', sorted(n))
print('count old=',o['count'],'len=',len(o['sessions']),'| count new=',n['count'],'len=',len(n['sessions']))
print('per-item bytes old=%.1f new=%.1f'%(277034/len(o['sessions']),285363/len(n['sessions'])))
"
```

实测输出：

```
status=200 bytes=285363 time=0.03
row-fields missing-in-new : []
row-fields added-in-new   : []
top-keys old: ['count', 'sessions']
top-keys new: ['count', 'has_more', 'limit', 'meta', 'offset', 'sessions', 'snapshot', 'total']
count old= 353 len= 353 | count new= 364 len= 364
per-item bytes old=784.8 new=784.0
```

| 断言 | 基线 | 实测 | 结论 |
|---|---|---|---|
| 会话行字段（`catalog_id`/`session_id`/`file_path`/`children`/`mtime`… 全 30+ 键） | 353 条的并集 | 364 条的并集 | 差集为空 → **无删无改名** |
| 顶层键 | `{count, sessions}` | 上列 8 键 | 旧 2 键保留，新增 6 键 → **只增** |
| `count` 语义 | = 本次返回条数（353 == len 353） | = 本次返回条数（364 == len 364） | **语义不变** |
| 单条平均字节 | 784.8 B | 784.0 B | **无逐条膨胀** |
| 总体积 | 277,034 B | 285,363 B（+3.0%） | 增量来源是会话数 353→364（数据增长），非字段膨胀 |
| 耗时 | 589 ms | 30.5 ms（−94.8%） | 快照指纹命中，零重算 |

### A2 旧单页 `/`（旧消费方活体探针）

```bash
curl -s --noproxy '*' -o .tmp/qa_legacy.html \
  -w "GET / -> status=%{http_code} bytes=%{size_download}\n" "http://127.0.0.1:18922/"
grep -c "sessionsGrid" .tmp/qa_legacy.html
```

```
GET / -> status=200 bytes=248586
3
```

结论 **PASS**：旧页面仍完整下发（248,586 B），`sessionsGrid` 容器出现 3 次（元素 id、CSS 选择器、JS 引用），旧前端代码路径未被切断。

### A3 契约基线护栏

```bash
.venv/Scripts/python.exe tools/contract_baseline.py --check --base http://127.0.0.1:18922
```

```
校验契约 <- http://127.0.0.1:18922（基线 docs/refactor/contract-baseline.json）
  [ OK ] status (/api/status) status=200
  [ OK ] sessions_all (/api/sessions) status=200
  [ OK ] sessions_format_antigravity (/api/sessions?format=antigravity) status=200
  [ OK ] sessions_search (/api/sessions?q=Git&format=all) status=200
  [ OK ] session_detail (/api/session/detail?catalog_id=1eaa5a8745ff40cb) status=200
  [ OK ] session_inspect (/api/session/inspect?catalog_id=1eaa5a8745ff40cb) status=200
  [ OK ] search_content (/api/search/content?q=Git&limit=5) status=200
  [ OK ] POST /api/catalog/refresh keys=[]
  [ OK ] POST /api/catalog/add_root keys=['format', 'path']
  [ OK ] POST /api/catalog/remove_root keys=['id']
  [ OK ] POST /api/session/migrate keys=['catalog_id','target_format','mode','custom_out_dir']
  [ OK ] POST /api/session/delete keys=['catalog_id','session_id','format','file_path']
  [ OK ] POST /api/sessions/batch_delete keys=['sessions']
  [ OK ] POST /api/sessions/batch_migrate keys=['catalog_ids','target_format']
  [ OK ] POST /api/open_folder keys=['path']
--------------------------------------------------------------------
结论：PASS —— 15 个接口结构向后兼容（只增不删不改名）   EXIT=0
```

结论 **PASS**。特别注意 `session_detail`（不带任何分片参数）也 OK —— 证明**旧全量路径的响应结构未被分片改造破坏**。

### A4 自检护栏有效性（负向测试）

```bash
.venv/Scripts/python.exe tools/contract_baseline.py --check \
  --base http://127.0.0.1:18922 --mutate-drop file_path; echo "EXIT=$?"
```

```
  [ OK ] status (/api/status) status=200
  [!] 自检：已从 sessions_all 的当前结构里删除字段 file_path
  [FAIL] sessions_all (/api/sessions) status=200
         - sessions_all.sessions[].file_path: 字段缺失
  [!] 自检：已从 sessions_format_antigravity 的当前结构里删除字段 file_path
  [FAIL] sessions_format_antigravity (/api/sessions?format=antigravity) status=200
         - sessions_format_antigravity.sessions[].file_path: 字段缺失
  [!] 自检：已从 sessions_search 的当前结构里删除字段 file_path
  [FAIL] sessions_search (/api/sessions?q=Git&format=all) status=200
         - sessions_search.sessions[].file_path: 字段缺失
  ...
结论：FAIL —— 3/15 个接口破坏契约
EXIT=1
```

结论 **PASS**：退出码 `1`（非 0），护栏在字段被摘掉时**确实变红**。A3 的绿灯因此可信——不是"永远返回 PASS"的空壳。

---

## 3. B 性能（4/4 PASS）

> 说明：`tools/bench_api.py` 用 `urllib` 且不带 `Accept-Encoding`，因此下述字节数均为**未压缩**体积，与 `baseline.json` 的口径一致（可比）。

### B5 列表 lite 分页

```bash
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 \
  --path "/api/sessions?limit=60&fields=lite" --n 5 --skip-first --max-bytes 51200 --json
```

```
status   : [200, 200, 200, 200, 200]
bytes    : 34545
gzip?    : no
etag     : "7943d6f1dfed5f3ddc1432b40eab543f"
ms       : avg=16.5 p95=50.6 max=33.7 (n=4)
  count: 60 | total: 364 | offset: 0 | limit: 60 | has_more: True
RESULT   : PASS
```

**34,545 B ≤ 51,200 B** → PASS。单条 575.8 B，相对全量单条 784.0 B 降 **26.6%**。

### B6 详情分片（最大会话 `1eaa5a8745ff40cb`）

```bash
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 \
  --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" \
  --n 3 --max-bytes 409600 --json
```

```
status   : [200, 200, 200]
bytes    : 355415
etag     : "a0e5839533a427a06b45dd511269776f68016571"
ms       : avg=34.7 p95=66.0 max=49.7 (n=3)
  events: 396 | turns_total: 12 | has_more: True
RESULT   : PASS
```

**355,415 B ≤ 409,600 B** → PASS（占预算 86.8%，余量偏小，见 §7 风险 R2）。

### B7 LRU 命中（二次打开详情）

```bash
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 \
  --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" \
  --n 6 --skip-first --max-ms 250
```

```
ms       : avg=30.7 p95=31.4 max=31.2 (n=5)
RESULT   : PASS
```

**p95 31.4 ms ≤ 250 ms** → PASS。

补充：另取一个**本次验证中从未解析过**的大会话（`f0c9aa2faa9243aa`，源文件 60,727,296 B）测冷热对比：

```
冷 首屏 turn_limit=8: status=200 bytes=374089 ms=1304.4
热 首屏 turn_limit=8: status=200 bytes=374087 ms=37.7
热 首屏 turn_limit=8: status=200 bytes=374087 ms=17.3
304 条件请求        : status=304 body=0B ms=19.7
```

冷 → 热降幅 **97.1%**，且 ETag 三次一致（`9994acb9…`）→ 证明 LRU key 的 `(cid, mtime_ns, size, PARSER_VERSION)` 稳定。

### B8 304 条件请求

```bash
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 \
  --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" --n 1 --etag
```

```
cond     : status=304 body_bytes=0 ms=20.7
RESULT   : PASS
```

**304 且 body = 0 B**（脚本同时断言 304 耗时 ≤30 ms）→ PASS。

### 3.1 性能对比表（改造前 vs 改造后）

| 指标 | 改造前 | 改造后 | 变化 |
|---|---:|---:|---:|
| `/api/sessions` 不传参 — 字节 | 277,034 B | 285,363 B | +3.0%（会话数 353→364 所致；单条 784.8→784.0 B，**无膨胀**） |
| `/api/sessions` 不传参 — 耗时 | 589 ms | **30.5 ms** | **−94.8%** |
| `/api/sessions?limit=60&fields=lite` — 字节 | 无此能力（只能全量 277,034 B） | **34,545 B** | 首屏 **−87.5%**（条目数不同，等价口径按单条 −26.6%） |
| `/api/sessions?limit=60&fields=lite` — 耗时 | 589 ms（全量） | **16.5 ms** | **−97.2%** |
| `/api/session/detail`（最大会话）— 字节 | 4,520,694 B | **355,415 B** | **−92.1%** |
| `/api/session/detail`（最大会话）— 耗时 | 1,205 ms | **34.7 ms** | **−97.1%** |
| `/api/session/detail` 旧全量路径 — 字节 | 4,520,694 B | 4,548,120 B | +0.61%（纯新增 `turns`/`turn_index`/`events_shipped` 等字段，事件一条未增） |
| `/api/session/detail` 冷解析（60.7 MB 源文件） | — | 1,304 ms | 单次解析成本未变（优化点在缓存与裁剪，不在解析器） |
| `/api/session/detail` LRU 命中 | — | **30.7 ms** | 相对冷解析 **−97.6%** |
| `/api/session/detail` 304 | 不支持 | **0 B / 20.7 ms** | 字节 **−100%** |
| 详情事件数（最大会话首屏） | 6,635 条 | **396 条** | **−94.0%**（opaque 丢弃 + 分片） |
| 全文索引体积 | 71.7 MB | 未见变化（本轮未重建索引） | — |

---

## 4. C 功能正确性（63/63 PASS，Round 2 终态）

统一入口（脚本内含 C9–C14 共 63 条断言）：

```bash
.venv/Scripts/python.exe tools/qa_regression.py --base http://127.0.0.1:18922 -v
```

### 4.1 C9 分页

```
C9 列表分页（limit=60，翻到尽）
  [PASS] C9.0 首页 200 — status=200
  [PASS] C9.1 首页返回条数 == limit — count=60
  [PASS] C9.2 snapshot 令牌非空 — snapshot=f346566f43f0
  [PASS] C9.3 全量翻页无重复 catalog_id — pages=7 rows=364 dup=0
  [PASS] C9.4 全量翻页无遗漏（行数 == total） — rows=364 total=364
  [PASS] C9.5 末页 has_more=false — last_count=4 has_more=False
  [PASS] C9.6 每页 offset 回显正确 — offsets=0,60,120,180,240,300,360
  [PASS] C9.7 裸 offset 翻 3 页也无重复 — rows=180 dup=0
       分页明细：[60, 60, 60, 60, 60, 60, 4]
```

`total=364`，`limit=60` 实际是 7 页而非 3 页；按 team-lead 要求额外单独验证了"前 3 页"（C9.7），并把**翻到尽**作为更强的口径（C9.3/C9.4/C9.5）。两种翻法（带 `snapshot` 令牌 / 裸 `offset`）都无重复。

### 4.2 C10 分片

```
C10 详情分片（1–8 / 9–12 拼接 + 默认预算推进）
  [PASS] C10.1 turns_total == 12 — turns_total=12
  [PASS] C10.2 turn_offset=0 归一化为起始轮 1 — turn_offset=1
  [PASS] C10.3 首片兑现 turn_limit=8 → 轮 1..8 — head=[1,2,3,4,5,6,7,8]
  [PASS] C10.4 次片为末片（轮 9..12 且 has_more=false） — tail=[9,10,11,12] has_more=False
  [PASS] C10.5 两片 turns 无重叠 — 交集=[]
  [PASS] C10.6 两片拼成连续 1..12 无断档 — merged=[1..12]
  [PASS] C10.7 首片 has_more=true — has_more=True
  [PASS] C10.8 span 首尾相接（end == 下轮 start） — 断档=[]
  [PASS] C10.9 末轮 end == events_total_raw — last_end=6635 raw=6635
  [PASS] C10.10 首片 turn_index 与 events 逐项等长 — events=461 turn_index=461
  [PASS] C10.11 首片 turn_index 取值都在本片 turns 内 — 越界=[]
  [PASS] C10.10 次片 turn_index 与 events 逐项等长 — events=1279 turn_index=1279
  [PASS] C10.11 次片 turn_index 取值都在本片 turns 内 — 越界=[]
       —— 默认字节预算（max_bytes 缺省）下的连续推进 ——
       shard#1 off=1  turns=[1,2,3,4,5]  shipped=396 dropped=3 budget_hit=True  has_more=True
       shard#2 off=6  turns=[6,7,8,9]    shipped=118 dropped=3 budget_hit=True  has_more=True
       shard#3 off=10 turns=[10]         shipped=678 dropped=2 budget_hit=True  has_more=True
       shard#4 off=11 turns=[11]         shipped=286 dropped=1 budget_hit=True  has_more=True
       shard#5 off=12 turns=[12]         shipped=262 dropped=0 budget_hit=False has_more=False
  [PASS] C10.12 默认预算下顺序推进覆盖 1..12 且无重复 — shards=5 covered=[1..12]
  [PASS] C10.13 turn_offset=999 → 200 且 events 为空
  [PASS] C10.14 不同分片的 ETag 不相同 — etag1="714080a5…" etag2="41e088fc…"
  [PASS] C10.15 串用别的分片 ETag 不得返回 304 — status=200 body=41256B
```

**口径修正说明（Round 1 自修，非源码缺陷）**：首版断言按 team-lead 字面要求写成
「`turn_offset=0/8` 两片拼成 12 轮」，失败后核查发现是**我的断言错**，依据三点：

1. `turn_offset` 是 **1 基起始轮号**（`services/turns.py:129-135` `resolve_start_position`），
   `0` 会被归一化为 `1`。因此 `0/8` 天然在**第 8 轮重叠**，本身不是合法切分点；
   合法切分是 `1` 与 `9`。
2. `max_bytes` 缺省 384 KB，`build_shard`（`services/detail.py:351-360`）按**整轮粒度**
   截断并回 `turns_dropped_by_budget` / `budget_hit`。所以「请求 8 轮拿到 5 轮」是
   **设计行为**，且 `has_more=true` 已正确告知"还有后续"。
3. 前端 `SessionDetailModal.tsx:495` 的 `nextTurnOffset` 已按「已到达最后一轮 + 1」推进
   （源码注释原文："后端会按字节预算裁掉后几轮（实测请求 8 轮只发回 5 轮，
   turns_dropped_by_budget=3），用请求值推进会漏轮"）。说明实现方对此已有共识。

因此把 C10 拆成两条独立路径重新断言：**纯切片契约**（`max_bytes` 充足 → `turn_limit` 精确兑现）
与**默认预算路径**（顺序推进 → 覆盖 1–12），二者均 PASS。
额外补了两条 team-lead 未点名但风险更高的断言：
**C10.14/15 分片 ETag 互不相同、串用不得 304** —— 这是"第 81–85 轮被 304 成第 1–5 轮"这类
静默错数据的唯一防线，实测防线有效。

### 4.3 C11 体积构成

```
C11 详情体积构成（opaque 丢弃 / tool_result 截断）
  [PASS] C11.1 events_total_raw == 6635 — events_total_raw=6635
  [PASS] C11.2 events_shipped ≈ 396（±15%） — events_shipped=396
  [PASS] C11.3 shipped 事件数 == len(events) — shipped=396 len=396
  [PASS] C11.4 events_count 保持旧语义（全量事件数） — events_count=6635 raw=6635
  [PASS] C11.5 响应内已无 kind=opaque 事件 — kinds={'message':19,'tool_result':160,'tool_call':160,'thinking':57}
  [PASS] C11.6 响应体不含 "opaque" 字面量 — 已在 JSON 序列化层复检
  [PASS] C11.7 tool_result.text 均 ≤1200 字 — 超长条数=0
  [PASS] C11.8 存在被标记 truncated 的事件（裁剪生效） — truncated 条数=67
  [PASS] C11.9 hidden_chars 记录了被隐藏字数 — 条数=67
  [PASS] C11.10 message 正文不被截断（Markdown 红线） — 超 1200 字的 message 条数=11
```

`"opaque"` 检查做了两层：① 逐事件判 `kind=="opaque"`（0 条）；② 对响应整体序列化后
搜 `"opaque"` 字面量（0 次）——② 用来排除"opaque 藏在 payload 里"这种绕过。
C11.10 是反向保护：**证明确实存在 >1200 字的 message 且未被裁**（若裁了条数会变 0），
说明"message 全量不裁"的红线没被误伤。

### 4.4 C12 详情内检索

```
C12 详情内检索（/api/session/search）
  [PASS] C12.0 接口 200 — status=200
  [PASS] C12.1 catalog_id 回显一致 — catalog_id=1eaa5a8745ff40cb
  [PASS] C12.2 命中 5 条 — count=5 len=5 source=memory
  [PASS] C12.3 count 与 matches 长度一致
  [PASS] C12.4 turn_index 全在 1..turns_total 内 — turn_index=[1,9,10,11,12]
  [PASS] C12.5 turn_index 去重（同轮不重复）
  [PASS] C12.6 每个命中轮次的正文确实含 Git（归属该 catalog_id） — 未命中的轮次=[]
       - turn 1  [assistant] {"input": {"CommandLine": "cd F:\\OpenMAIC; git status --sho...
       - turn 9  [assistant] …if (f !== 'node_modules' && f !== '.next' && f !== '...
```

「命中 5 条且全部属于该 catalog_id」的验证方式：按返回的 `turn_index` 回查该会话
**全量详情**的对应 span，逐轮确认正文含 `git`（不区分大小写），5/5 命中。
归属关系在服务端由 `WHERE conversation_fts MATCH ? AND catalog_id = ?` 与
`search_in_events(该 cid 的 events)` 双重保证，交叉验证结果一致。

> **口径修正（Round 1 自修）**：首版 C12.6 只扫事件的 `text` 字段，turn 9 / 12 报失败。
> 核查后确认是断言不全：`search_in_events`（`services/detail.py:592-597`）的匹配语义是
> **「`text` 为空时退化为 `payload` 的 JSON」**，而这两轮的 `git` 恰好出现在
> `tool_call.payload.input`（如 `{"CommandLine":"cd f:\\OpenMAIC; git status --short"}`）
> 与 JS 源码片段里的 `'.git'` 字符串。补上 payload 后 5/5 通过，源码无问题。

### 4.5 C13 子会话

```
C13 子会话按需拉取（/api/session/children）
  [PASS] C13.0 接口 200 — status=200
  [PASS] C13.1 返回 3 个子会话 — children_count=3 len=3
  [PASS] C13.2 children_count == len(children) — 3 vs 3
  [PASS] C13.3 子会话 id 互不重复 — ids=['ef990d5ca6c3408f','02b0e8e752724b3c','f279f78a19324e3d']
  [PASS] C13.4 每个子会话都有 catalog_id
       - ef990d5ca6c3408f 2026-11-10 · 基因到通路研究平台实验构建评估 · browser 子
       - 02b0e8e752724b3c 2026-11-10 · 基因到通路研究平台实验构建评估 · browser 子
       - f279f78a19324e3d 2026-11-10 · 基因到通路研究平台实验构建评估 · browser 子
```

### 4.6 C14 边界（16/16 PASS，Round 2 终态；Round 1 曾 1 项 FAIL ← 唯一源码缺陷 D-1）

```
C14 边界参数（不得 500）
  [PASS] limit=0 → 200        [PASS] turn_offset=999 → 200
  [PASS] limit=99999 → 200    [PASS] turn_limit=0 → 200
  [PASS] offset=99999 → 200   [PASS] max_bytes=0 → 200
  [PASS] limit=-1 → 200       [PASS] max_bytes=xxx → 200
  [PASS] limit=abc → 200      [PASS] q= 空 → 200（count=0, source=empty）
  [PASS] q 全空 → 400（catalog_id required）
  [FAIL] 非法 catalog_id（search） → 500
         {"error": "Failed to search session: Session not found in catalog: catalog session ID was not found"}
  [PASS] 非法 catalog_id（detail） → 404
  [PASS] 非法 catalog_id（children） → 404
  [PASS] children 缺参 → 400
  [PASS] C14.15 limit=0 回落为全量（count == total） — count=364 total=364
```

最小复现（4 个会话分支全部命中同一缺陷）：

```bash
for cid in __nope__ ag_deadbeef wb_nope trae_nope; do
  printf "%-14s " "$cid"
  curl -s --noproxy '*' -o /dev/null -w "search=%{http_code}\n" \
    "http://127.0.0.1:18922/api/session/search?catalog_id=$cid&q=Git"
done
```

```
__nope__       search=500
ag_deadbeef    search=500
wb_nope        search=500
trae_nope      search=500
```

---

## 5. D 前端静态核查（2/2 PASS）

### D15 TypeScript 类型检查

```bash
cd frontend && npx tsc --noEmit; echo "TSC_EXIT=$?"
```

```
（无输出）
TSC_EXIT=0
```

**零错误** → PASS。

### D16 端点切换核查

```bash
rg -n "/api/session/search|/api/session/children|/api/search/content" frontend/src
```

| 关注点 | 实测位置 | 结论 |
|---|---|---|
| 详情内检索是否走后端新端点 | `client.ts:192-214` `searchInSession()` → `GET /api/session/search?catalog_id=&q=`；调用方 `SessionDetailModal.tsx:570` `.searchInSession(cid, q, {strict:true})` | **已切换** |
| 子会话是否按需拉取 | `client.ts:163-180` `getSessionChildren()` → `GET /api/session/children?catalog_id=`；调用方 `SessionCard.tsx:131`（首次展开时才请求） | **已切换** |
| 是否仍在调旧 `/api/search/content` | `client.ts:216-226` `searchContent()`，唯一调用方 `GlobalSearchModal.tsx:40,56`（**全局**全文检索，非详情内检索） | **不算缺陷**：全局检索本就无 `catalog_id` 维度，沿用旧端点是正确的 |

`client.ts:187` 的源码注释也印证了这一分工："注意不是 `/api/search/content` —— 那个接口没有 catalog_id 过滤能力。"

补充核查（超出必测项，记录备查）：
- 列表分页：`page.tsx:54` `fields:'lite'`、`client.ts:125` 默认 `fields=lite`、`client.ts:130` 透传 `snapshot`、`page.tsx:120` 以 `hasMore` 控制加载 → 与后端新增参数对齐。
- 详情分片：`SessionDetailModal.tsx:138` `TURNS_PER_SHARD=8`、`:495-505` `nextTurnOffset`（按实际到达轮次推进）、`:528` 空分片判定 `setStalled` 防空转 → 与后端字节预算行为对齐。
- 降级路径齐全：`normalize.ts:129-157` 无 `meta` 时回落"一次全量 + hasMore=false"；`client.ts:210-212` 检索失败返回空数组并退回前端扫描 → 后端未升级时不白屏。

---

## 6. 智能路由判定

### 6.1 路由到 Engineer（1 个源码缺陷）

| # | 文件:行 | 现象 | 期望 | 影响面 |
|---|---|---|---|---|
| **D-1** | `web_app.py:3309-3317`（`handle_session_search` 的 FTS 未命中回退分支） | `GET /api/session/search?catalog_id=<不存在>&q=Git` → **500** `{"error":"Failed to search session: Session not found in catalog: ..."}`；`__nope__` / `ag_deadbeef` / `wb_nope` / `trae_nope` 四分支全中 | **404** `{"error":"Session not found: ..."}` | team-lead 必测项 C14 |

**根因**：`_detail_probe()`（`web_app.py:3368` 起）在四个会话分支都抛
`detail_service.DetailError(message, 404)`，而该处只有一个 `except Exception`，
把"客户端错误"升格成"服务端错误"，同时把内部异常文本泄漏进响应体。

```python
3315:            except Exception as exc:  # noqa: BLE001
3316:                self.send_json({"error": f"Failed to search session: {exc}"}, status=500)
```

**不是设计选择的三条旁证**：
1. 同源的 `/api/session/detail` 在 `services/detail.py:500-507` 明确 `except DetailError → exc.status`；
2. `/api/session/children` 在 `web_app.py:3246-3248` 正确返回 404；
3. `web_app.py:3270-3275` 里同一个函数对缺 `catalog_id` 已正确返回 400 —— 说明本意就是要区分 4xx。

**建议修法**：在 `except Exception` **之前**插入 `except detail_service.DetailError as exc:`，
用 `exc.status` 透传。已通过 SendMessage 下发完整复现步骤与修法给 software-engineer。

### 6.2 自修（3 处测试脚本问题，未计入源码缺陷）

| # | 断言 | 原写法的问题 | 修正 |
|---|---|---|---|
| S-1 | C10 分片拼接 | 假设 `turn_offset=0/8` 能无重叠拼成 12 轮，且假设 `turn_limit` 一定被精确兑现 | 拆成「纯切片契约（1 与 9，`max_bytes` 充足）」+「默认预算顺序推进」两条路径；并补充 `turn_offset` 1 基语义断言 |
| S-2 | C12.6 检索归属 | 只扫事件 `text`，漏掉 `payload` 里的命中 | haystack 改为 `text or json(payload)`，与 `search_in_events` 的匹配语义对齐 |
| S-3 | B8 的 304 耗时断言 | `bench_api.py` 用**单样本 ≤30 ms** 判定，Windows 回环 TCP 建连抖动必然误报（实测 6.1–35.4 ms 双峰分布，而 304 路径服务端零解析） | 功能断言改逐次全验（`--etag-n` 默认 5），耗时改**中位数**、阈值 50 ms（`--etag-max-ms`）。真回归是 1.2 s 量级，仍能兜住 |

三处均为**我的断言/脚本与实现语义不符**，源码行为符合设计文档，故不路由给 Engineer。
修正后 `tools/qa_regression.py` 已固化，可随时复跑。

### 6.3 未路由项

Round 2 终态：其余 73 条断言全部 PASS，无需再路由。
（D-2 见 §9.1，属 16 项之外的追加发现，已单独路由。

---

## 7. 遗留风险清单

> 均**不构成本轮 FAIL**，但建议记录并在后续迭代处理。按风险高低排序。

| ID | 风险 | 证据 / 位置 | 建议 |
|---|---|---|---|
| **R1** | **第三方消费方按 `offset += turn_limit` 推进会漏轮**。默认 `max_bytes=393216` 会按整轮裁掉后续轮次（实测请求 8 轮只发回 5 轮），`turns_dropped_by_budget=3`。前端已按「最后一轮+1」推进，但**脚本/第三方**若按请求值推进会永久漏掉第 6、7 轮，且服务端只给 `has_more=true`，不会报错。 | `services/detail.py:351-360`；实测 `shard#1 off=1 → turns=[1..5]`，`off=8 → turns=[8,9]`，第 6、7 轮被跳过 | 在 API 文档/注释里把「**必须用 `turns[].index` 的 max+1 推进**」写成硬约束；或让后端在 `has_more=true` 时额外回 `next_turn_offset` 字段，把推进责任收归服务端 |
| **R2** | **单轮本身超 `max_bytes` 时预算失效**。`build_shard` 的 `if chunks and used + chunk_bytes > max_bytes` 对**第一个** chunk 无条件放行（这是"绝不发半个轮次"的有意取舍）。因此若某一轮自身就有数 MB（如粘贴巨型文件），首屏仍会超预算。B6 实测 355,415 B 已占 400 KB 预算的 **86.8%**，余量偏小。 | `services/detail.py:356`；B6 355,415/409,600 = 86.8% | 保留该取舍，但考虑对**单轮内的超长 tool_result** 做更激进截断（当前 1200 字仍可能 × 若干百条）；并把 `max_bytes` 默认值从 384 KB 调到 512 KB 以留余量 |
| **R3** | **详情内检索在大会话上可能退回秒级**。`1eaa5a8745ff40cb` 的检索 `source=memory`（FTS 未命中），即走全量解析路径；LRU 命中时 ~30 ms，但缓存被淘汰后需 ~1.3 s。用户首次在大会话内检索会明显卡顿。 | C12 实测 `source=memory`；冷解析实测 1,304 ms | 跑 `tools/audit_fts.py` 核对 FTS 覆盖率（`turns.audit_fts_alignment`）；对"FTS 未覆盖"的大会话考虑预热 |
| **R4** | **LRU 单条 ≥32 MB 永不入缓存**。`f0c9aa2f`（源文件 60.7 MB）实测**入了缓存**（冷 1304 ms → 热 37.7 ms），当前安全；但语料继续增长后，若某会话的估算值越过 32 MB 阈值，将退化为"每次都冷解析"，且**无任何日志**。 | `services/detail.py:56,156-157` | 命中 `single_entry_max` 时打一条 WARN 日志，便于线上发现；或在 `/api/status` 暴露 `DETAIL_CACHE.stats()` |
| **R5** | **快照令牌只保留 3 个（`MAX_SNAPSHOTS=3`）**。用户多标签页翻页、期间发生 ≥3 次快照重建时，旧令牌失效会静默回落到"当前快照"，导致同一批分页跨了快照 → 极端情况下重复/漏条。 | `services/snapshot.py:35,128-157` | 令牌失效时回 `X-Snapshot-Stale: 1` 响应头，让前端感知并重置列表；或把 `MAX_SNAPSHOTS` 提到 5 |
| **R6** | **前端真机 UI 验证不由 QA 覆盖**。按 team-lead 要求本轮"以 API 层验证为主"，QA 侧仅做 `tsc --noEmit`（EXIT=0）与源码核查；分片续载的 `IntersectionObserver` 触发时机、检索跳轮滚动定位、`stalled` 态观感**未由 QA 在浏览器验证**。**（更新）** 此后 `software-engineer-2` 已补 Playwright E2E 并自证：`1eaa` 首屏 `1..5` 连续、`1/12`、搜 `Git` 1/5 并可逐条跳转、控制台 0 错误；对照会话 `b20148aa815d4fbd` 无回归。证据见 `shots/14-1eaa-detail-first.png` 与 `_verify/*.js`。**剩余缺口**：E2E 由实现方自证，非独立第三方验证。 | `SessionDetailModal.tsx:549-560,621-637`；`shots/`、`_verify/` | 若需完全独立，应由 QA 用 `_verify/` 脚本复跑一次并留存截图；当前接受实现方证据 |
| **R7** | **`count` 语义是长期陷阱**。`/api/sessions` 的 `count` 是"本次返回条数"而非总数，分页引入后语义更易误读。当前旧页 `/` 不传 `limit`（`count == total`），故未触发；但任何新消费方把 `count` 当总数都会显示错误。 | `services/snapshot.py:228-229` 注释已声明；`_s.json` 与实测均 `count == len(sessions)` | 保持现状（向后兼容优先），但前端新代码一律用 `total` / `meta.total`；在 API 文档里标 `count` 为 deprecated |
| **R8** | **gzip 未在本环境生效**。`bench_api.py` 不带 `Accept-Encoding`，实测 `gzip?=no`。若浏览器带 gzip，实际传输量会更低——但也意味着**上述所有字节数都是未压缩口径**，真实带宽收益应比报告数字更好，而**服务端 CPU（JSON 序列化）不会因此减少**。 | B5/B6 均 `gzip? : no` | 若要进一步压带宽，前端确保发 `Accept-Encoding: gzip`（浏览器默认会发，风险低）；本轮不改 |
| **R9** | **`turns[].start/end` 是原始全量事件的下标，不可用于切响应里的 `events`**（详见 §9.3 末）。实测 `span1 = [0,1558)`、`max(end)=1759`，而响应 `events` 只有 396 条、`events_total_raw=6635` —— 客户端从未收到过那个下标空间。按最自然写法 `events[start:end]` 取第 1 轮会返回 **396 条（全部）**，实际应为 **209 条**。**（更新）前端已不再依赖该字段**：轮号来源已切换为 `turn_index`（与裁剪后 events 平行），`turns[]` 仅作存在性标志。**但字段本身仍在误导，建议修正或删除**，避免后续消费方再踩一次。 | `services/detail.py:543-559`（`response["turns"] = shard["spans"]` 未重映射）；实测见 §9.3 | ① 分片响应不返回 `start/end`（客户端零价值，还能省字节），或②重映射到裁剪后 `events` 下标。文档写死「**唯一可信的轮次映射是 `turn_index`**」。**注意**：若做 ②，需同步调整 QA 断言 C10.9（当前依赖原始下标语义） |
| **R10** | **目录库重建期间 detail / search 会短暂 500**。实测 08:32 出现 `{"error":"Failed to resolve session: cannot open the private session catalog; move the disposable database aside and run \`session-migrate catalog refresh\`"}`，同期 `/api/status` 一度返回 `000`（连接层失败），`total` 从 365 掉到 362。约 1 分钟后自愈。属"服务重启 + catalog 重建"窗口期的瞬时不可用，**非代码缺陷**（我在稳定后复跑 63/63 PASS）。 | 观测时间线见 §8.1；错误文案来自 catalog 打开失败路径 | 运维层面：重启/刷新 catalog 应避开用户活跃期，或让 `/api/status` 在 catalog 不可用时返回 503 + `Retry-After` 而非直接断连；消费方应对 5xx 做重试 |

---

## 8. 复测记录（Round 2 / Round 3）

| 轮次 | 触发 | 动作 | 结果 |
|---|---|---|---|
| Round 1 | 首轮验证 | 写 `tools/qa_regression.py`，跑 73 条断言 | PASS 72 / FAIL 1（C14 非法 catalog_id → 500）；自修 S-1/S-2 两处测试断言；D-1 路由 Engineer |
| Round 2 | Engineer 修复 `web_app.py:3315` 后 | 复跑 `tools/qa_regression.py` + `bench_api.py` + `contract_baseline.py --check` | **见下方回填** |

### Round 2 回填

**Engineer 修复已落地**（`web_app.py:3315-3322`，文件 mtime `08:17`，比 Round 1 首测晚 2 分钟，
改动 +368 B，与建议修法逐字一致）：

```python
3315:            except detail_service.DetailError as exc:
3316:                # 会话不存在 / 源文件缺失属于 client error：原样透传状态码（404），
3317:                # 不要升格成 500，也不必把内部文本（catalog session ID ...）泄漏出去
3318:                self.send_json({"error": exc.message}, status=exc.status)
3319:                return
3320:            except Exception as exc:  # noqa: BLE001
3321:                self.send_json({"error": f"Failed to search session: {exc}"}, status=500)
3322:                return
```

`DetailError` 分支已正确置于 `except Exception` 之前。

#### ⚠️ 复测方式说明（未违反"勿重启"约束）

`main()` 用 `httpd.serve_forever()`，**没有热重载**。实测确认运行中的 18922 进程仍持有旧字节码：

```bash
$ curl -s --noproxy '*' -w "\nHTTP=%{http_code}\n" \
    "http://127.0.0.1:18922/api/session/search?catalog_id=__nope__&q=Git"
{"error": "Failed to search session: Session not found in catalog: catalog session ID was not found"}
HTTP=500        ← 源码已修，但进程未加载
```

因此**未重启 18922**（遵守 team-lead 约束），改用 `web_app.py` 自带的多实例参数
（`--port`，源码注释："多实例自测用；默认仍是 18922，行为不变"）在 **18924** 起一个
修复版实例做复测：

```bash
.venv/Scripts/python.exe web_app.py --port 18924 --no-browser
```

`release_port(18924)` 只清理 18924 上的监听者，主实例 18922 全程保持 200 不受影响（已复验）。
18924 为**冷进程**（LRU / 快照缓存全空），因此 Round 2 的性能数字更接近"服务刚启动"的真实首访。

#### Round 2 结果：全部 PASS

| 验证项 | Round 1（18922，旧字节码） | Round 2（18924，修复版） | 结论 |
|---|---|---|---|
| **C14 非法 catalog_id（search）** | **500** `Failed to search session: ...` | **404** `Session not found in catalog: ...` | **已修复** |
| C14 四分支逐一复核 | 4/4 → 500 | `__nope__`404 / `ag_deadbeef`404 / `wb_nope`404 / `trae_nope`404 | 全 404，且错误文本不再泄漏内部细节 |
| 既有功能未回归（正常会话检索） | `count=5, source=memory` | `count=5, source=memory`，首条 snippet 仍是 `git status --short` | 未回归 |
| `qa_regression.py` 全量 | 62/63 | **63/63 PASS，退出码 0** | 全绿 |
| A3 `contract_baseline --check` | PASS 15/15 | **PASS 15/15** | 修复未破坏契约 |
| A4 `--mutate-drop file_path` | EXIT=1 | **EXIT=1** | 护栏仍有效 |
| B5 列表 lite | 34,545 B / p95 50.6 ms | **34,474 B / p95 31.3 ms** | PASS，未回退 |
| B6 详情分片 | 355,415 B / p95 66.0 ms | **355,415 B / p95 99.3 ms**（p95 含冷启动首访） | PASS，字节未变 |
| B7 LRU 命中 | p95 31.4 ms | **p95 16.4 ms** | PASS |
| B8 304 | 304 / 0 B / 20.7 ms | **304 / 0 B / 21.6 ms** | PASS |
| D15 `tsc --noEmit` | EXIT=0 | EXIT=0（后端修复不影响前端） | PASS |

**Round 2 计数：必测项 16/16 PASS；断言 73/73 PASS。**

#### 收尾动作：**已完成**（18922 已重启上线）

> 原记录：18922 跑的是修复前字节码，需重启才对 D-1 生效。
> **后续复核：`software-engineer` 已于 08:31 前后重启 18922，D-1 现已上线。**

### 8.1 Round 3（对当前线上状态的复验）

`software-engineer` 在 Round 2 之后继续修复了 D-2，并重启了 18922。为确认没有引入回归，
我在其源码停止变动、服务恢复稳定后做了一次复验。

#### 环境状态观测（复验前提，必须先说清楚）

| 时间 | 观测 |
|---|---|
| 08:29:24 / 08:29:39 / 08:31:24 | `services/detail.py` / `web_app.py` / `services/snapshot.py` 相继被改 |
| ~08:31 | 18922 重启载入新代码 → **D-1 上线**：`__nope__` → **404** |
| ~08:32 | catalog 库重建窗口：detail / search 短暂 **500**（`cannot open the private session catalog`），`/api/status` 一度 `000`，`total` 365→362 |
| 08:33 | 恢复稳定：连续 60 s 内 detail 全 200、`total` 恒定 362 |
| 08:34:33 | `services/detail.py` 再次变动 → 我随即停止测量并改为与 Engineer 协调 |

> **重要**：08:32 窗口期的 500 **不是回归**。我在 `08:33` 恢复稳定后复跑，全绿（见下）。
> 若不做这个区分，会把环境噪声误报成代码缺陷。该现象已记为风险 **R10**。

#### 复验结果（源码冻结 + 服务稳定后）

| 项 | 结果 |
|---|---|
| `qa_regression.py` 63 条断言 | **63/63 PASS**，退出码 0（复跑两次一致） |
| A3 契约 `--check` | **PASS 15/15**（首次因并发压测撞上 `WinError 10054` 连接重置返回 EXIT=2，属网络错误非契约破坏；单独重跑 PASS） |
| A4 `--mutate-drop file_path` | **EXIT=1**（护栏仍有效） |
| D-1 `非法 catalog_id` | **404**（已上线） |
| D-2 列表 ETag | 去重 **1/4**、条件请求 **304 / 0 B**（**已修复**） |
| 详情 304 | **304 / 0 B ×5**（未回归） |
| D15 `tsc --noEmit`（前端改动后复测） | **EXIT=0，零错误** |
| B5 列表 lite | 34,438 B / p95 33.9 ms → PASS（≤51,200 B） |
| B6 详情分片 | 359,742 B → PASS（≤409,600 B）；冷解析 1,179 ms、热 17–31 ms |
| B7 LRU 命中 | p95 39.3 ms → PASS（≤250 ms） |
| B8 304 | **304 ×5 / body 0 ×5**，中位 8.4–30.1 ms → **PASS**（详见下方 S-3） |

#### S-3（QA 自修的测试脚本问题）：`bench_api.py` 的 304 耗时断言过严

复验期间 B8 曾报 FAIL：单样本 304 耗时 **35.0 ms** > 脚本内建的 30 ms 阈值。
我判定这是**测试脚本问题，不是被测代码回归**，证据：

```
详情 304 十二次(ms): 7.2 6.1 24.6 34.3 31.2 34.4 8.5 6.6 7.6 31.9 35.4 26.0
  min=6.1  median=25.3  max=35.4      <=30ms: 7/12   <=50ms: 12/12
列表 304 十次(ms): 12.5 10.7 11.6 25.0 10.8 35.6 30.4 31.5 29.5 31.2
  min=10.7 median=27.3 max=35.6
```

① 呈**双峰分布**，`min=6.1 ms` —— 说明服务端在 304 路径上确实"一次解析都不做"，
快的那一档才是真实成本；慢的那一档是 Windows 回环 TCP 建连抖动。
② 阈值 30 ms 是**单样本**判定，在并发环境下必然抖动。
③ team-lead 的 B8 原始要求只有「**必须 304 且 body 为 0**」，并未规定延迟上限，
30 ms 是 `bench_api.py` 自加的额外约束。

**修正**（仅改测试脚本 `tools/bench_api.py`，未动业务代码）：
- 功能断言改为**逐次全验**（`--etag-n` 默认 5 次，任一非 304 或 body 非空即 FAIL）；
- 耗时断言改为**中位数**，阈值 50 ms（`--etag-max-ms`）。
  50 ms 仍能兜住真回归——若 304 又去解析文件，那是 **1.2 s** 量级，超阈 24 倍。

修正后连续 4 轮 B8 全部 PASS，不再抖动：
```
cond: 304 ×5 body 0 ×5  median=30.1ms
cond: 304 ×5 body 0 ×5  median=20.9ms
cond: 304 ×5 body 0 ×5  median= 8.4ms
cond: 304 ×5 body 0 ×5  median=29.7ms
```

> 说明 B6 的 1,179 ms：会话文件 mtime 变化会使 LRU key 失效（`(cid, mtime_ns, size, PARSER_VERSION)`），
> 首访必然重新解析一次。实测随后 3 次为 30.9 / 18.2 / 17.1 ms。这是**设计行为**，非回归。

**Round 3 计数：63/63 断言 PASS；D-1、D-2 均已修复；B5–B8 全部达标。**

---

## 9. 追加发现（超出原 16 项必测范围，来自 teammate 交接）

> 以下三项**不是**原 16 项必测项的一部分，是在与 `software-engineer` / `software-engineer-2`
> 交叉核对交接信息时补充验证出来的。为保持结论诚实，单列于此，**不计入 16 项计数**。
>
> - §9.1 **D-2**：后端缺陷，**已修复并复验**（列表 ETag 稳定化）
> - §9.2 **澄清**：`q` 缺省语义，建议保持现状（不改）
> - §9.3 **D-3**：前端缺陷，**已修**；并由此暴露接口陷阱 **R9**

### 9.1 缺陷 D-2（**已修复并复验**）：`/api/sessions` 的 ETag 每次请求都变，304 永久不可能命中

**发现来源**：`software-engineer-2` 交接第 4 条（"列表 ETag 目前必然不命中 304"）→ 我独立复现确认。

```bash
# 连发 4 次同一请求，观察 ETag
.venv/Scripts/python.exe - <<'PY'
import urllib.request
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(4):
    with op.open("http://127.0.0.1:18922/api/sessions?limit=60&fields=lite") as r:
        print(i+1, r.headers.get("etag"))
PY
```

实测：

```
#1 etag="2f58b5725018d06c4ece27059ecf9295"
#2 etag="9d4063ab761bd538d0357210e394a58d"
#3 etag="9d64e23b69d7375774fcda1ba66eacf9"
#4 etag="21e0434fbddaef2bf7a0fac63acb99d6"
ETag 去重个数: 4 / 4  → 不稳定

拿 #1 的 ETag 做条件请求：
  If-None-Match="2f58b57..." -> status=200 body=34545B   ← 期望 304 / 0 B
```

**根因（已定位到单一字段）**：对两次相同请求的 body 做逐字段 diff，差异**只有 1 个字段**：

```
 .meta.ms : 9.17 -> 9.91        ← 逐请求耗时，必然变
差异字段总数: 1
```

`services/snapshot.py:212-224` 把 `meta.ms`（本次请求耗时）放进了**响应体**，
而 `_send_compressed` 在 `etag=None` 时用 `md5(body)` 现算 ETag（`web_app.py:3056-3063`）。
body 每请求都变 → ETag 每请求都变 → 条件请求永不命中。

**影响**：列表页每次重新拉取都要整包重传（34,545 B；前端口径 gzip 约 7.4 KB），
拿不到 304。前端 `client.ts:23-25` 的注释**明确宣称依赖这个能力**：

> "后端每份 JSON 都带 ETag 并支持 304 …… 改成 default 后相同参数的二次请求走 304，body 接近 0 字节。"

即：**该注释描述的行为在当前后端不成立**。详情接口的 304 是好的（ETag 预解析、
不依赖 body），问题只在列表。

**对照证据**（同一时刻的详情接口，证明这不是"ETag 机制整体坏了"）：

```
详情 ETag 三次: ['"a0e5839533a427a06b45dd511269776f68016571"'] ×3  去重=1
详情条件请求 -> status=304 body=0B                                    ✅
```

**建议修法（优先 A，零 body 变更、零前端风险）**：

- **A（推荐）**：仿照详情接口的做法，**不要让 ETag 由 body 派生**。在 `SnapshotCache.serve()`
  里按 `(snapshot_id, limit, offset, fields, fold, q, format, sort_by, order)` 算一个稳定指纹，
  作为 `etag=` 传给 `send_json()`。body 一个字节都不用改，`meta.ms` 保留给诊断用。
- **B（次选）**：把 `meta.ms` 从 body 移到响应头 `X-Elapsed-Ms`（详情 304 路径已有同名头，
  风格一致）。已确认前端 `normalize.ts:150-158` **只读** `total/offset/limit/has_more/snapshot`，
  不读 `meta.ms`，故删除它不会破坏任何消费方。

**路由**：已通过 SendMessage 报 `software-engineer`（D-2）与 `team-lead`。

**为什么不算本轮 FAIL**：原 16 项必测里 B8 只点名了**详情**的 304（实测 PASS）；
列表 304 不在验收范围内，属本轮改造声明能力与实际不符的**新增发现**。

#### 修复与复验（`services/snapshot.py` mtime 08:31:24）

Engineer 修复后复测：

```
ETag 连发 4 次: ['"6f0d1986b7c044871a51ae9e9ff401ccaf9a89a2"'] ×4
去重: 1 / 4  → ✅ 已稳定
条件请求 If-None-Match -> status=304 body=0B  → ✅ 304 命中
详情 304 对照 -> status=304 body=0B           → ✅ 未回归
```

**D-2 状态：已修复并复验通过。**

### 9.2 澄清：`/api/session/search` 的 `q` 缺省语义（经确认保持现状）

`software-engineer` 主动询问"`q` 缺失是否也要 400"。实测与结论：

| 请求 | 实测 | 判定 |
|---|---|---|
| `?catalog_id=<有效>&q=` | 200 `{count:0, matches:[], source:"empty"}` | 合理 |
| `?catalog_id=<有效>`（`q` 完全不传） | 200 `count=0` | 合理 |
| `?catalog_id=&q=`（缺 catalog_id） | 400 `catalog_id required` | 合理 |
| `?catalog_id=<不存在>&q=Git` | 404 | 本轮已修复 |

**QA 意见：保持现状，不改。** 理由：① `q` 是"检索词"，空检索返回空结果集是
REST 里的常规语义（`filter` 为空 = 不过滤），不是参数错误；② 该端点是**本轮新增**，
不存在"缺省 == 旧行为"的兼容包袱，但把 `q` 缺失改成 400 会让调用方多一条错误分支，
收益为零；③ 真正该 400 的是"无法确定在哪检索"（缺 `catalog_id`），当前已正确。

建议仅在 API 文档里写明这条语义，**已在 §9.2 存档**，不改代码。

### 9.3 前端缺陷 D-3（已修）：`1eaa` 首屏轮号跳号 `1,2,3,4,5,7` —— 后端无责

**结论修订**：本项在 Round 2 曾存档为"未复现（怀疑前端）"。经 `software-engineer-2` 定位
并修复后，**确认是前端 `buildTurns` 的轮号推导缺陷，后端行为始终正确**。本节据实修订。

#### 后端的正确性（我的独立复测，D-3 修复前就成立）

```
turns[] = [1, 2, 3, 4, 5]   shipped=396  dropped=3  budget_hit=True  has_more=True
每轮事件数（按 turn_index 统计）: {1:209, 2:32, 3:92, 4:15, 5:48}
turns[] 里但 0 事件的轮: []          ← 无空轮
backend turns 连续？ True             ← 严格连续
```

`build_shard` 的 `kept_spans = selected[:len(chunks)]`（`services/detail.py:362`）是**前缀切片**，
结构上不可能产出跳号；`turn_index` 按 span 广播（`services/detail.py:367-369`），
不会出现"轮在 `turns[]` 里但零事件"。**后端预算绝不会跳轮。**

#### 真正的根因（前端 `SessionDetailModal.tsx` 的 `absoluteTurnNumber`）

关键在**"首条用户指令之前的前缀区"**：`1eaa` 会话开头有 72 条与用户指令无关的事件
（跑脚本 / 读 model / 探目录）。实测验证：

```bash
# 首片 events 里 message+user 边界的下标
message+user 下标 = [72, 209, 241, 333, 348]
第一个边界下标 = 72
该下标之前的事件 kind 分布 = {'tool_result': 29, 'tool_call': 28, 'message': 9, 'thinking': 6}
```

后端与前端对这块前缀区**处理方式不同**，于是轮数不一致：

| | 前缀区处理 | `1eaa` 首片轮数 |
|---|---|---|
| 后端 `compute_turn_spans` | 并入第 1 轮（`starts = [0] + boundaries[1:]`，`services/turns.py:64` 有意如此，为与 FTS `turn_index` 对齐） | **5** 轮 |
| 前端 `buildTurns`（修复前） | 前缀区被单独顶成第 1 轮，真实第一条指令变成第 2 轮 | **6** 轮 |

前端 `absoluteTurnNumber` 按**序号**映射（`spans[k-1]`，兜底 `offset + k`）：

- 本地第 2 轮取到 `spans[1].index = 2`，实际应为 1 → 之后整体 +1 漂移（`1,2,3,4,5` 被映成 `2,3,4,5,6`）；
- 本地第 6 轮超出 5 个 span，走兜底 `offset(1) + 6 = 7` → **这就是 `…,5,7` 里那个 7 的来源**。

#### 修法与复验（由 `software-engineer-2` 完成）

改为**按轮数对齐 + 前缀区检测**：`localCount > spanCount` 时判定存在前缀轮，
本地轮整体前移一位（`slot = k - 2`），且前缀轮与第 1 轮**合并**（`user` 取有值者，
`thinks`/`tools`/`replies` 顺序拼接）——不是"先到先得"地丢弃，否则会连用户指令一起丢。
轮号仍取 `spans[].index`（绝对 1 基，与 FTS `turn_index` 同源）。

前端复验（真实后端，`:3001`，`tsc` 零错误 + `next build` 通过）：
```
turns[] = 1,2,3,4,5                     ← 连续，无跳号
turn-1: 用户气泡 1 个, 思考 1 折, 行动 1 折   ← 前缀区已并入第 1 轮
nav = 1 / 12   subtitle = 6635 条事件 · 12 轮
search "Git" = 1/5；连按 4 次 → 2/5,3/5,4/5,5/5，依次补 offset=9,10,11,12
控制台 0 错误
```
对照无前缀区的 `b20148aa815d4fbd`：`1..8` 连续、`1/18`、搜 `Git` 1/11、加载更多到 17，无回归。

**QA 判定：D-3 状态 = 已修，后端无责。** 原"未复现"的存档结论已作废并替换为本节。

#### 最终映射口径（后续改这块的人请直接看这段，不要重新推导）

> **前端以 `turn_index`（与裁剪后的 `events` 逐项平行）作为轮号的唯一来源。**
> `turns[].start/end` 属**原始全量事件空间**，已确认为**不可用字段**（R9），
> 前端只把 `turns[]` 当"有没有分片信息"的存在性标志，不再用它做编号或切片。

`software-engineer-2` 已据此把实现从 `turns[].index` 改成 `turn_index`，原"按 span 数对齐 +
前缀区检测"降级为 `turn_index` 缺失时的兜底。QA 独立验证三个前提全部成立：

```bash
.venv/Scripts/python.exe - <<'PY'
import urllib.request, json
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
d = json.loads(op.open("http://127.0.0.1:18922/api/session/detail"
                       "?catalog_id=1eaa5a8745ff40cb&turn_limit=8").read())
ev, ti = d["events"], d["turn_index"]
b = [i for i, e in enumerate(ev) if e.get("kind") == "message" and e.get("role") == "user"]
print("并行长度:", len(ti) == len(ev))              # 1) 逐项平行
print("前缀区并入第1轮:", ti[0] == 1 and ti[b[0]] == 1)  # 2) 72 条前缀区归第 1 轮
starts = [0] + b[1:]
print("本地轮起点->轮号:", [ti[s] for s in starts])   # 3) [1,2,3,4,5]
print("与 spans.index 一致:", sorted(set(ti)) == [s["index"] for s in d["turns"]])
PY
```

实测：
```
1) len(turn_index)=396 == len(events)=396 ? True
2) 首个 message+user 边界=72   turn_index[0]=1   turn_index[72]=1
   前缀区并入第1轮？ True
3) 本地轮起点 [0, 209, 241, 333, 348] -> turn_index [1, 2, 3, 4, 5]
   distinct=[1,2,3,4,5]   spans.index=[1,2,3,4,5]   一致？True
```

前端复验（真实后端 / `:3001` / `tsc` 零错误 / `build` 通过）：
`1eaa` → `1..5` 连续、`1/12`、搜 `Git` **1/5**、连跳补 `offset=9,10,11,12`；
`b20148aa815d4fbd`（无前缀区）→ `1..8` 连续、`1/18`、搜 `Git` **1/11**、加载更多到 17；
两处控制台 0 错误。首屏 357,083 B（gzip 76,556）。

> **QA 复核结果**：上述前提与数字**全部独立复现**（我测得 357,082 B，差 1 B 属快照漂移）。
> 该口径把"轮号"与"事件下标"两件事解耦，**是比原方案更稳的设计**。

#### ⚠️ 由此暴露的接口陷阱 R9（`spans[].start/end` 不可用于切 `events`）

交叉验证时发现一个**比跳号本身更危险**的问题，且**不是前端的错**，属接口设计缺陷：

```bash
len(events) 响应内事件数 = 396        turns_total=12   turns[]=[1,2,3,4,5]
span1 start=0 end=1558               max(all span.end)=1759
events_total_raw=6635
-> max(end) > len(events) ? True     max(end)==events_total_raw ? False
```

即 `turns[].start/end` 的下标空间是**原始全量事件数组**（后端 `_compose` 里对
`payload["events"]` 全集算的 spans），**既不是响应里裁剪后的 `events`（396 条），
也不是客户端能拿到的任何数组**（客户端从没收到过那 6635 条）。

后果：任何消费方按最自然的写法切分轮次都会拿到错数据 ——
`events[span.start:span.end]` 对第 1 轮返回 **396 条**（全部），而第 1 轮实际只有 **209 条**。

**这是一个真实的误用陷阱**（前端正是踩到它才先试"按下标找 span"然后放弃的）。
当前前端已改用 `turn_index`（逐事件对齐，正确），因此**线上无 bug**，故不列为缺陷，
但记录为 **R9**（见 §7）。建议后端二选一：① 分片响应里干脆不返回 `start/end`；
② 或把它们重映射到裁剪后的 `events` 下标空间。**消费方唯一可信的轮次映射是 `turn_index`。**

---

## 10. 最终结论

| 维度 | 结论 |
|---|---|
| 必测项（本轮验收口径） | **16/16 PASS**（Round 1 曾 15/16，1 个源码缺陷已由 Engineer 修复并复测通过） |
| 断言级 | **73/73 PASS** |
| 向后兼容 | 旧页 `/` 与不传参 `/api/sessions` 完全兼容；15 个接口契约零破坏 |
| 性能目标 | 4 项全部达标，详情字节降 **92.1%**、耗时降 **97.1%** |
| 前端 | `tsc` 零错误；检索与子会话均已切到新端点 |
| 路由判定 | Round 1 → **Engineer**（D-1，已修复）；Round 3 → **全绿** |
| **本轮验收是否可放行** | **可以** —— 16 项验收全部达标，无阻塞项 |
| **追加缺陷（均已消除）** | D-2 列表 ETag → **已修复并复验**（§9.1）；D-3 前端轮号跳号 → **已修复并复验**（§9.3） |
| 待排期风险 | **R9**（`turns[].start/end` 下标陷阱，前端已不依赖）、**R10**（catalog 重建窗口期瞬时 500） |

### 缺陷总览

| ID | 缺陷 | 位置 | 状态 | 影响验收 |
|---|---|---|---|---|
| **D-1** | `/api/session/search` 把 404 吞成 500 | `web_app.py:3309-3317` | **已修复并复测通过** | 是（C14）→ 已消除 |
| **D-2** | 列表 ETag 不稳定，304 永不命中 | `services/snapshot.py:212-224` + `web_app.py:3056-3063` | **已修复并复验**（ETag 去重 1/4、304 命中 0 B） | 否（超出原 16 项） |
| **D-3** | 详情首屏轮号跳号 `1,2,3,4,5,7` | `SessionDetailModal.tsx` `absoluteTurnNumber` | **已修复并复验**（前端自证 + QA 独立核对根因） | 否（后端无责；不在 D 项静态核查范围） |

> 另有 3 条**非缺陷**待澄清项已存档：`q` 缺省语义（§9.2，建议保持现状）、
> 前端"轮号不连续"已定位为前端 bug 并修复（§9.3）、`total` 364↔365 为语料数据漂移。
> 由 D-3 交叉验证暴露的接口陷阱记为 **R9**（§7）。

---

## 附录：本轮新增测试资产

| 文件 | 用途 | 是否触碰业务代码 |
|---|---|---|
| `tools/qa_regression.py` | C9–C14 只读回归（63 条断言），退出码 0/1，可直接接入 CI | 否 |
| `docs/refactor/03-verification.md` | 本报告 | 否 |

复跑全部验证：

```bash
.venv/Scripts/python.exe tools/contract_baseline.py --check --base http://127.0.0.1:18922
.venv/Scripts/python.exe tools/contract_baseline.py --check --base http://127.0.0.1:18922 --mutate-drop file_path
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 --path "/api/sessions?limit=60&fields=lite" --n 5 --skip-first --max-bytes 51200
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" --n 3 --max-bytes 409600
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" --n 6 --skip-first --max-ms 250
.venv/Scripts/python.exe tools/bench_api.py --base http://127.0.0.1:18922 --path "/api/session/detail?catalog_id=1eaa5a8745ff40cb&turn_limit=8" --n 1 --etag
.venv/Scripts/python.exe tools/qa_regression.py --base http://127.0.0.1:18922
cd frontend && npx tsc --noEmit
```
