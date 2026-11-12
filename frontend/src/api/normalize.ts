/**
 * 接口适配层：把 Python 后端返回的原始字典，转成前端视图模型。
 *
 * 历史教训：上一版直接假设后端字段名（content / path / has_subagents），
 * 与真实响应（text / file_path / children）不一致，TS 编译期发现不了，
 * 运行时全部静默变成 undefined —— 于是详情页整页空白。
 * 这里做一次运行期归一化，字段缺失时给出安全默认值，禁止组件直接读原始响应。
 *
 * 本轮改造（分页 / 详情分片）的上游约束：**新参数与新字段都是可选的**。
 * 后端未升级时响应里没有 meta / turn_offset / turns_total，
 * 归一化必须回落到"一次全量 + hasMore=false"，页面不允许因此白屏。
 */
import { formatDateTime } from '../lib/format';
import {
  AppStatus,
  SessionChild,
  SessionDetail,
  SessionEvent,
  SessionEventDetail,
  SessionEventKind,
  SessionItem,
  SessionListResponse,
  SessionSearchMatch,
  SessionTurnSpan,
  SearchResultItem,
} from '../types/session';

type Raw = Record<string, any>;

const str = (v: any): string => (v === null || v === undefined ? '' : String(v));
const num = (v: any): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

const KINDS: SessionEventKind[] = ['message', 'thinking', 'tool_call', 'tool_result', 'opaque'];

function normalizeKind(raw: Raw): SessionEventKind {
  const k = str(raw.kind);
  if (KINDS.includes(k as SessionEventKind)) return k as SessionEventKind;
  if (raw.tool_name) return 'tool_call';
  return raw.role === 'user' || raw.role === 'assistant' ? 'message' : 'opaque';
}

export function normalizeEvent(raw: Raw): SessionEvent {
  const kind = normalizeKind(raw);
  return {
    kind,
    role: str(raw.role),
    text: str(raw.text ?? raw.content),
    rawText: str(raw.raw_text ?? ''),
    timestamp: str(raw.timestamp),
    toolName: str(raw.tool_name),
    toolCallId: str(raw.tool_call_id),
    payload: raw.payload ?? null,
    hiddenChars: num(raw.hidden_chars),
    collapsed: Boolean(raw.collapsed),
    summary: str(raw.summary),
    truncated: Boolean(raw.truncated),
    truncatedChars: num(raw.truncated_chars),
    // 由 event_index[] 在分片装载时回填（列表/详情单独调用时为 -1）
    eventIndex: -1,
  };
}

/** 单事件回源响应归一化 */
export function normalizeEventDetail(raw: Raw): SessionEventDetail {
  return {
    catalogId: str(raw.catalog_id),
    index: num(raw.index),
    kind: str(raw.kind),
    role: str(raw.role),
    timestamp: str(raw.timestamp),
    text: str(raw.text ?? ''),
    payload: raw.payload ?? null,
    bytes: num(raw.bytes),
  };
}

export function normalizeTurnSpan(raw: Raw): SessionTurnSpan {
  return {
    index: num(raw.index),
    start: num(raw.start),
    end: num(raw.end),
    userPreview: str(raw.user_preview),
    ts: str(raw.ts),
  };
}

export function normalizeChild(raw: Raw): SessionChild {
  return {
    catalogId: str(raw.catalog_id),
    sessionId: str(raw.session_id),
    title: str(raw.title) || '未命名子会话',
    startedAt: str(raw.started_at),
    records: num(raw.records),
    bytes: num(raw.bytes),
    tokens: num(raw.tokens),
    format: str(raw.format),
    agentName: str(raw.agent_name),
    isChild: Boolean(raw.is_child),
    filePath: str(raw.file_path),
  };
}

export function normalizeSession(raw: Raw): SessionItem {
  // lite 字段集会省略 children（甚至整个键），这里一律回落成空数组：
  // 子会话改由 /api/session/children 按需拉取，卡片不得因缺键而崩。
  const children = Array.isArray(raw.children) ? raw.children.map(normalizeChild) : [];
  return {
    catalogId: str(raw.catalog_id),
    sessionId: str(raw.session_id),
    format: str(raw.format),
    title: str(raw.title) || '未命名会话',
    startedAt: str(raw.started_at),
    mtime: num(raw.mtime),
    records: num(raw.records),
    bytes: num(raw.bytes),
    tokens: num(raw.tokens),
    chatTokens: num(raw.chat_tokens),
    inputTokens: num(raw.input_tokens),
    outputTokens: num(raw.output_tokens),
    thoughtsTokens: num(raw.thoughts_tokens),
    contentTokens: num(raw.content_tokens),
    usageSource: str(raw.usage_source),
    filePath: str(raw.file_path),
    exists: raw.exists !== false,
    children,
    childrenCount: num(raw.children_count) || children.length,
    // Antigravity 谱系信息
    lineage: str(raw.lineage),
    lineageSize: num(raw.lineage_size),
    lineageHeadTitle: str(raw.lineage_head_title),
    lineageHeadId: str(raw.lineage_head_id),
    lineageHeadSteps: num(raw.lineage_head_steps),
    branchLabel: str(raw.branch_label),
    isLineageBranch: Boolean(raw.is_lineage_branch),
    sideQuestion: str(raw.side_question),
    parentId: str(raw.parent_id),
    isChild: Boolean(raw.is_child),
    nestingDepth: num(raw.nesting_depth),
    agentName: str(raw.agent_name),
  };
}

/**
 * 列表响应归一化。
 *
 * - 有 meta：total / has_more / offset / limit / snapshot 取服务端值（分页的权威来源）
 * - 无 meta（后端未升级）：total = 本页条数、hasMore = false，等价于"一次全量"
 */
export function normalizeSessionList(raw: Raw): SessionListResponse {
  const list = Array.isArray(raw?.sessions) ? raw.sessions : [];
  const sessions = list.map(normalizeSession);
  const meta = raw?.meta && typeof raw.meta === 'object' ? raw.meta : null;
  const pageCount = num(raw?.count) || sessions.length;

  if (!meta) {
    return {
      sessions,
      count: pageCount,
      total: sessions.length,
      offset: 0,
      limit: sessions.length,
      hasMore: false,
      snapshot: '',
    };
  }

  return {
    sessions,
    count: pageCount,
    total: num(meta.total) || sessions.length,
    offset: num(meta.offset),
    limit: num(meta.limit) || sessions.length,
    hasMore: Boolean(meta.has_more),
    snapshot: str(meta.snapshot),
  };
}

export function normalizeDetail(raw: Raw): SessionDetail {
  const events = Array.isArray(raw.events) ? raw.events.map(normalizeEvent) : [];
  const turns = Array.isArray(raw.turns) ? raw.turns.map(normalizeTurnSpan) : [];
  const turnIndexes = Array.isArray(raw.turn_index) ? raw.turn_index.map(num) : [];
  const eventIndexes = Array.isArray(raw.event_index) ? raw.event_index.map(num) : [];
  return {
    sessionId: str(raw.session_id),
    format: str(raw.format),
    title: str(raw.title) || '会话详情',
    startedAt: str(raw.started_at),
    eventsCount: num(raw.events_count) || events.length,
    events,
    model: str(raw.model),
    cwd: str(raw.cwd),
    notice: str(raw.notice),
    isChild: Boolean(raw.is_child),
    parentId: str(raw.parent_id),
    parentTitle: str(raw.parent_title),
    parentCatalogId: str(raw.parent_catalog_id),
    agentName: str(raw.agent_name),
    turnOffset: num(raw.turn_offset),
    // turn_limit 缺省记为 0：调用方据此判断"后端未支持分片"
    turnLimit: num(raw.turn_limit),
    turnsTotal: num(raw.turns_total),
    // 后端实际字段是 has_more；has_more_turns 是早期设计稿的命名，两者都认
    hasMoreTurns: Boolean(raw.has_more ?? raw.has_more_turns),
    nextTurnOffset: num(raw.next_turn_offset),
    turns,
    turnIndexes,
    eventIndexes,
    part: num(raw.part),
  };
}

export function normalizeSearchResult(raw: Raw): SearchResultItem {
  return {
    catalogId: str(raw.catalog_id),
    sessionId: str(raw.session_id),
    sessionTitle: str(raw.session_title),
    sessionFormat: str(raw.session_format),
    role: str(raw.role),
    turnIndex: num(raw.turn_index),
    timestamp: str(raw.timestamp),
    snippet: str(raw.snippet),
  };
}

/**
 * 会话内检索命中归一化。
 *
 * 新接口 `/api/session/search` 返回的是 `matches`（每项 {turn_index, snippet, kind, role}）。
 * 兼容分支：
 *  - 响应里既没有 matches 也没有 results → `scoped=false`，调用方退回前端扫描；
 *  - 只有旧版 `/api/search/content` 的 `results` → 逐条校验 catalog_id，
 *    有任何一条属于别的会话就说明后端没按会话过滤，同样判 `scoped=false`。
 */
export function normalizeSessionSearchMatches(
  raw: Raw,
  catalogId: string
): { matches: SessionSearchMatch[]; scoped: boolean } {
  const rows: Raw[] = Array.isArray(raw?.matches)
    ? raw.matches
    : Array.isArray(raw?.results)
      ? raw.results
      : [];

  if (!Array.isArray(raw?.matches) && !Array.isArray(raw?.results)) {
    return { matches: [], scoped: false };
  }

  const scoped = rows.every((r) => {
    const cid = str(r?.catalog_id);
    return !cid || cid === catalogId;
  });
  const matches: SessionSearchMatch[] = [];
  for (const r of rows) {
    const cid = str(r?.catalog_id);
    if (cid && cid !== catalogId) continue;
    const turnIndex = num(r?.turn_index);
    if (turnIndex <= 0) continue;
    matches.push({
      turnIndex,
      role: str(r?.role),
      timestamp: str(r?.timestamp),
      snippet: str(r?.snippet),
    });
  }
  return { matches, scoped };
}

export function normalizeStatus(raw: Raw): AppStatus {
  const roots = Array.isArray(raw.roots)
    ? raw.roots.map((r: Raw) => ({
        id: num(r.id),
        format: str(r.format),
        path: str(r.path),
        enabled: r.enabled !== false,
        lastScanStatus: str(r.last_scan_status),
        lastError: str(r.last_error),
      }))
    : [];
  return {
    totalSessions: num(raw.total_sessions),
    formatCounts: raw.format_counts && typeof raw.format_counts === 'object' ? raw.format_counts : {},
    roots,
    supportedTargets: Array.isArray(raw.supported_targets) ? raw.supported_targets.map(str) : [],
    exportDir: str(raw.export_dir),
  };
}

/** 详情页标题区显示的元信息行 */
export function describeSession(s: SessionItem): string {
  const parts = [formatDateTime(s.startedAt)];
  if (s.records) parts.push(`${s.records} 步`);
  return parts.filter(Boolean).join(' · ');
}
