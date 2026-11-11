/**
 * 接口适配层：把 Python 后端返回的原始字典，转成前端视图模型。
 *
 * 历史教训：上一版直接假设后端字段名（content / path / has_subagents），
 * 与真实响应（text / file_path / children）不一致，TS 编译期发现不了，
 * 运行时全部静默变成 undefined —— 于是详情页整页空白。
 * 这里做一次运行期归一化，字段缺失时给出安全默认值，禁止组件直接读原始响应。
 */
import { formatDateTime } from '../lib/format';
import {
  AppStatus,
  SessionChild,
  SessionDetail,
  SessionEvent,
  SessionEventKind,
  SessionItem,
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
  };
}

export function normalizeSession(raw: Raw): SessionItem {
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
    nestingDepth: num(raw.nesting_depth),
    agentName: str(raw.agent_name),
  };
}

export function normalizeDetail(raw: Raw): SessionDetail {
  const events = Array.isArray(raw.events) ? raw.events.map(normalizeEvent) : [];
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
