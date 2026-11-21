/** 前端唯一可信的视图模型定义（由 api/normalize.ts 运行期填充） */

export type AgentFormatType =
  | 'all'
  | 'antigravity'
  | 'claude'
  | 'workbuddy'
  | 'trae'
  | 'doubao'
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
  /** 服务端裁剪标记：true 表示 text 已被截断，完整内容需单事件回源 */
  truncated: boolean;
  /** 服务端本次实际藏掉的字符数（配合 /api/session/event 回源） */
  truncatedChars: number;
  /**
   * 该事件在会话**全量事件**里的绝对下标（分片模式下由 `event_index[]` 回填）。
   * 回源 `/api/session/event` 时用它，不能用 `turns[].start`（slim 后下标不连续）。
   */
  eventIndex: number;
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
  usageSource?: string;
  cacheReadTokens?: number;
  cacheMissTokens?: number;
  filePath?: string;
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
  inputTokens: number;
  outputTokens: number;
  thoughtsTokens: number;
  contentTokens: number;
  cacheReadTokens: number;
  cacheMissTokens: number;
  freshTokens: number;
  usageSource: string;
  filePath: string;
  exists: boolean;
  children: SessionChild[];
  childrenCount: number;
  lineage: string;
  lineageSize: number;
  lineageHeadTitle: string;
  lineageHeadId: string;
  lineageHeadSteps: number;
  branchLabel: string;
  isLineageBranch: boolean;
  sideQuestion: string;
  parentId: string;
  /** 是否为由主会话派生的子代理会话（列表里永久收进父卡片抽屉，不单独成卡） */
  isChild: boolean;
  nestingDepth: number;
  agentName: string;
}

/** 服务端返回的轮次边界（绝对轮号由 index 决定，slice 由 start/end 决定） */
export interface SessionTurnSpan {
  index: number;
  start: number;
  end: number;
  userPreview: string;
  ts: string;
}

export interface SessionDetail {
  sessionId: string;
  format: string;
  title: string;
  startedAt: string;
  /** 全量事件数（旧语义，未分片时也成立） */
  eventsCount: number;
  events: SessionEvent[];
  model: string;
  cwd: string;
  notice: string;
  isChild?: boolean;
  parentId?: string;
  parentTitle?: string;
  parentCatalogId?: string;
  agentName?: string;
  /** 本次响应覆盖的起始轮（0 基；后端未支持分片时为 0） */
  turnOffset: number;
  /** 本次响应请求的轮数（0 表示后端未支持分片） */
  turnLimit: number;
  /** 会话总轮数（0 表示后端未返回该字段） */
  turnsTotal: number;
  /** 是否还有后续轮次（后端未支持分片时恒为 false） */
  hasMoreTurns: boolean;
  /** 下一页的起始轮号（服务端给；0 表示没有下一页） */
  nextTurnOffset: number;
  /** 豆包云端详情：后台是否正在拉取最新正文 */
  refreshPending?: boolean;
  /** 豆包云端详情对应的完整会话 ID / 云端链接 */
  cloudLink?: string;
  /** 本次响应覆盖的轮次边界列表 */
  turns: SessionTurnSpan[];
  /**
   * 与 `events` **逐项平行**的绝对轮号数组（1 基，与 FTS 的 turn_index 同源）。
   * 唯一的可信轮次映射来源：`turns[].start/end` 是原始事件下标空间，
   * 与裁剪后的 events 不可互换。
   */
  turnIndexes: number[];
  /** 与 `events` 逐项平行的绝对事件下标（回源 /api/session/event 用） */
  eventIndexes: number[];
  /** 超预算单轮的切片序号 */
  part: number;
}

/** 单事件回源响应（/api/session/event） */
export interface SessionEventDetail {
  catalogId: string;
  index: number;
  kind: string;
  role: string;
  timestamp: string;
  text: string;
  payload: unknown;
  bytes: number;
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
  /** 事件分类（message / tool_call / thinking…）；旧后端可能不返回 */
  kind?: string;
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

/** 会话内检索命中项：只需要轮号与摘要 */
export interface SessionSearchMatch {
  turnIndex: number;
  role: string;
  timestamp: string;
  snippet: string;
}

/** 列表分页元信息（后端未升级时缺省） */
export interface SessionListMeta {
  total: number;
  offset: number;
  limit: number;
  hasMore: boolean;
  snapshot: string;
}

export interface SessionListResponse extends SessionListMeta {
  sessions: SessionItem[];
  /** 本页条数（旧语义，与后端 count 一致） */
  count: number;
  /** 当前查询/平台过滤下的全量统计；旧后端可能缺省 */
  stats?: {
    bytes: number;
    tokens: number;
    topLevelTotal?: number;
    childTotal?: number;
  };
}
