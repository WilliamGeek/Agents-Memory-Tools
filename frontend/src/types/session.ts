/** 前端唯一可信的视图模型定义（由 api/normalize.ts 运行期填充） */

export type AgentFormatType =
  | 'all'
  | 'antigravity'
  | 'claude'
  | 'workbuddy'
  | 'trae'
  | 'cursor'
  | 'copilot'
  | 'codex'
  | 'kimi'
  | 'qwen';

export type SessionEventKind = 'message' | 'thinking' | 'tool_call' | 'tool_result' | 'opaque';

export interface SessionEvent {
  kind: SessionEventKind;
  role: string;
  text: string;
  rawText: string;
  timestamp: string;
  toolName: string;
  toolCallId: string;
  payload: unknown;
  hiddenChars: number;
  collapsed: boolean;
  summary: string;
}

export interface SessionChild {
  catalogId: string;
  sessionId: string;
  title: string;
  startedAt: string;
  records: number;
  bytes: number;
  tokens: number;
  format: string;
  agentName: string;
  isChild: boolean;
}

export interface SessionItem {
  catalogId: string;
  sessionId: string;
  format: string;
  title: string;
  startedAt: string;
  mtime: number;
  records: number;
  bytes: number;
  tokens: number;
  chatTokens: number;
  filePath: string;
  exists: boolean;
  children: SessionChild[];
  childrenCount: number;
  lineage: string;
  lineageSize: number;
  lineageHeadTitle: string;
  branchLabel: string;
  isLineageBranch: boolean;
  sideQuestion: string;
  parentId: string;
  nestingDepth: number;
  agentName: string;
}

export interface SessionDetail {
  sessionId: string;
  format: string;
  title: string;
  startedAt: string;
  eventsCount: number;
  events: SessionEvent[];
  model: string;
  cwd: string;
  notice: string;
}

export interface AppStatus {
  totalSessions: number;
  formatCounts: Record<string, number>;
  roots: {
    id: number;
    format: string;
    path: string;
    enabled: boolean;
    lastScanStatus: string;
    lastError: string;
  }[];
  supportedTargets: string[];
  exportDir: string;
}

export interface SearchResultItem {
  catalogId: string;
  sessionId: string;
  sessionTitle: string;
  sessionFormat: string;
  role: string;
  turnIndex: number;
  timestamp: string;
  snippet: string;
}

export interface SearchResponse {
  results: SearchResultItem[];
  count: number;
  latencyMs: number;
  totalIndexedTurns: number;
}

export interface SessionListResponse {
  sessions: SessionItem[];
  count: number;
}
