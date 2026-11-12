import {
  AppStatus,
  SessionChild,
  SessionDetail,
  SessionEventDetail,
  SessionItem,
  SessionListResponse,
  SessionSearchMatch,
  SearchResponse,
} from '../types/session';
import {
  normalizeChild,
  normalizeDetail,
  normalizeEventDetail,
  normalizeSearchResult,
  normalizeSessionList,
  normalizeSessionSearchMatches,
  normalizeStatus,
} from './normalize';

/**
 * 后端在「扫描目录」期间会持有 catalog 写锁，并发的读请求可能长时间排队。
 * 这里统一加超时，避免界面无限转圈——超时后给出可读的错误，而不是假装在加载。
 *
 * 缓存语义：`cache: 'default'`。旧实现把浏览器缓存整体关掉（fetch 的 cache 设为禁用模式），
 * 而后端每份 JSON 都带 ETag 并支持 304 —— 禁用缓存会让浏览器跳过条件请求，
 * 把 304 能力彻底关掉；改成 default 后相同参数的二次请求走 304，body 接近 0 字节。
 */
async function fetchJson<T>(url: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs = 25000, signal: externalSignal, ...init } = options || {};
  const controller = new AbortController();
  const onExternalAbort = () => controller.abort();
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort();
    else externalSignal.addEventListener('abort', onExternalAbort);
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
      cache: 'default',
      signal: controller.signal,
    });
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      throw new Error('请求超时，后端可能正在执行扫描或索引，请稍后重试');
    }
    throw new Error(e?.message || '网络请求失败');
  } finally {
    clearTimeout(timer);
    externalSignal?.removeEventListener('abort', onExternalAbort);
  }

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      if (data?.error) message = data.error;
    } catch {
      /* 保留状态码文案 */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

/** 删除/清理类接口都需要这四个标识，缺一不可（后端按 format + 路径决定清理策略） */
function sessionKey(s: SessionItem) {
  return {
    catalog_id: s.catalogId,
    session_id: s.sessionId,
    format: s.format,
    file_path: s.filePath,
  };
}

export interface GetSessionsParams {
  q?: string;
  format?: string;
  sortBy?: string;
  order?: 'asc' | 'desc';
  /** 缺省（或 0）时请求全量，与改造前行为完全一致 */
  limit?: number;
  offset?: number;
  /** lite：服务端按白名单裁剪字段；full/缺省：全量字段 */
  fields?: 'lite' | 'full';
  /** 是否请求服务端折叠同源分叉（前端仍保留本地兜底） */
  fold?: boolean;
  /** 分页期间锁定同一快照，避免 offset 漂移 */
  snapshot?: string;
}

export interface GetSessionDetailParams {
  /** 起始轮（0 基）。不传则请求全量（旧行为） */
  turnOffset?: number;
  /** 本次请求轮数。不传则请求全量（旧行为） */
  turnLimit?: number;
  /** 服务端裁剪；需要 /api/session/event 单事件回源配合，默认关闭 */
  slim?: boolean;
  signal?: AbortSignal;
}

export const api = {
  async getStatus(): Promise<AppStatus> {
    return normalizeStatus(await fetchJson<Record<string, any>>('/api/status'));
  },

  /**
   * 会话列表。
   *
   * 不传 `limit` 时**不发送** limit/offset 参数 —— 后端缺省即全量，响应也没有 meta，
   * 归一化后 total = 条数、hasMore = false，与改造前完全等价。
   */
  async getSessions(params?: GetSessionsParams): Promise<SessionListResponse> {
    const sp = new URLSearchParams();
    if (params?.q) sp.set('q', params.q);
    if (params?.format && params.format !== 'all') sp.set('format', params.format);
    if (params?.sortBy) sp.set('sort_by', params.sortBy);
    if (params?.order) sp.set('order', params.order);
    if (typeof params?.limit === 'number' && params.limit > 0) {
      sp.set('limit', String(params.limit));
      if (typeof params.offset === 'number' && params.offset > 0) {
        sp.set('offset', String(params.offset));
      }
      sp.set('fields', params.fields || 'lite');
    } else if (params?.fields) {
      sp.set('fields', params.fields);
    }
    if (params?.fold) sp.set('fold', '1');
    if (params?.snapshot) sp.set('snapshot', params.snapshot);
    const raw = await fetchJson<Record<string, any>>(`/api/sessions?${sp.toString()}`);
    return normalizeSessionList(raw);
  },

  /**
   * 会话详情。带 turnOffset/turnLimit 时请求分片。
   *
   * 后端未升级（忽略这两个参数）时响应里没有 turns_total / has_more_turns，
   * 归一化给出 hasMoreTurns=false，调用方按"一次全量"处理。
   */
  async getSessionDetail(
    catalogId: string,
    params?: GetSessionDetailParams
  ): Promise<SessionDetail> {
    const sp = new URLSearchParams({ catalog_id: catalogId });
    if (typeof params?.turnOffset === 'number') sp.set('turn_offset', String(params.turnOffset));
    if (typeof params?.turnLimit === 'number') sp.set('turn_limit', String(params.turnLimit));
    if (params?.slim) sp.set('slim', '1');
    const raw = await fetchJson<Record<string, any>>(`/api/session/detail?${sp.toString()}`, {
      timeoutMs: 20000,
      signal: params?.signal,
    });
    if (raw?.error) throw new Error(String(raw.error));
    return normalizeDetail(raw);
  },

  /**
   * 子会话列表（lite 字段集不再携带 children，改为按需拉取）。
   *
   * 默认**不抛错**：404 / 超时 / 后端未实现一律返回空数组，调用方的页面不会崩。
   * `strict: true` 时把错误抛给调用方，用于区分"确实没有子会话"与"取不到列表"。
   */
  async getSessionChildren(
    catalogId: string,
    opts?: { strict?: boolean; signal?: AbortSignal; timeoutMs?: number }
  ): Promise<SessionChild[]> {
    if (!catalogId) return [];
    try {
      const raw = await fetchJson<Record<string, any>>(
        `/api/session/children?catalog_id=${encodeURIComponent(catalogId)}`,
        { timeoutMs: opts?.timeoutMs ?? 12000, signal: opts?.signal }
      );
      if (raw?.error) throw new Error(String(raw.error));
      const list = Array.isArray(raw?.children) ? raw.children : [];
      return list.map(normalizeChild);
    } catch (e) {
      if (opts?.strict) throw e;
      return [];
    }
  },

  /**
   * 会话内检索（服务端索引，拿命中轮号）。
   *
   * 端点：`GET /api/session/search?catalog_id=&q=`，响应
   * `{catalog_id, q, count, source, matches:[{turn_index, snippet, kind, role}]}`。
   * （注意不是 /api/search/content —— 那个接口没有 catalog_id 过滤能力。）
   *
   * 默认**不抛错**，失败返回空数组。`strict: true` 用于区分"命中 0 轮"与"接口不可用"，
   * 后者由调用方退回前端扫描。
   */
  async searchInSession(
    catalogId: string,
    q: string,
    opts?: { limit?: number; strict?: boolean; signal?: AbortSignal }
  ): Promise<SessionSearchMatch[]> {
    const query = (q || '').trim();
    if (!catalogId || !query) return [];
    try {
      const sp = new URLSearchParams({ catalog_id: catalogId, q: query });
      if (opts?.limit) sp.set('limit', String(opts.limit));
      const raw = await fetchJson<Record<string, any>>(`/api/session/search?${sp.toString()}`, {
        timeoutMs: 12000,
        signal: opts?.signal,
      });
      if (raw?.error) throw new Error(String(raw.error));
      const { matches, scoped } = normalizeSessionSearchMatches(raw, catalogId);
      if (!scoped) throw new Error('该后端版本未支持会话内检索');
      return matches;
    } catch (e) {
      if (opts?.strict) throw e;
      return [];
    }
  },

  /**
   * 单事件回源：拿某条事件被 slim 裁掉的完整内容。
   *
   * `index` 必须是**绝对事件下标**（分片响应里的 `event_index[i]`），
   * 不能用 `turns[].start` —— slim 丢弃 opaque 后 raw 下标不连续。
   * 后端复用详情解析的 LRU，命中时 50–200ms。
   */
  async getSessionEvent(
    catalogId: string,
    index: number,
    field: 'text' | 'payload' | 'both' = 'text'
  ): Promise<SessionEventDetail> {
    const sp = new URLSearchParams({
      catalog_id: catalogId,
      index: String(index),
      field,
    });
    const raw = await fetchJson<Record<string, any>>(`/api/session/event?${sp.toString()}`, {
      timeoutMs: 20000,
    });
    if (raw?.error) throw new Error(String(raw.error));
    return normalizeEventDetail(raw);
  },

  async searchContent(query: string, limit = 60): Promise<SearchResponse> {
    const raw = await fetchJson<Record<string, any>>(
      `/api/search/content?q=${encodeURIComponent(query)}&limit=${limit}`
    );
    return {
      results: (raw.results || []).map(normalizeSearchResult),
      count: Number(raw.count) || 0,
      latencyMs: Number(raw.latency_ms) || 0,
      totalIndexedTurns: Number(raw.total_indexed_turns) || 0,
    };
  },

  /** 返回扫描结果概览（后端不返回 total_sessions，需要再查一次状态；失败时 HTTP 仍为 200） */
  async refreshCatalog() {
    const raw = await fetchJson<{
      success: boolean;
      scanned?: number;
      files_seen?: number;
      unchanged?: number;
      missing?: number;
      error?: string;
    }>('/api/catalog/refresh', { method: 'POST', timeoutMs: 180000 });
    if (raw.success === false) throw new Error(raw.error || '扫描失败');
    return raw;
  },

  openFolder: (path: string) =>
    fetchJson<{ success: boolean }>('/api/open_folder', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  deleteSession: (s: SessionItem) =>
    fetchJson<{ success: boolean; freed_bytes: number; is_shared_db: boolean }>(
      '/api/session/delete',
      { method: 'POST', body: JSON.stringify(sessionKey(s)) }
    ),

  deleteByCatalogId: (catalogId: string) =>
    fetchJson<{ success: boolean; freed_bytes: number }>('/api/session/delete', {
      method: 'POST',
      body: JSON.stringify({ catalog_id: catalogId }),
    }),

  batchDeleteSessions: (sessions: SessionItem[]) =>
    fetchJson<{
      success: boolean;
      deleted_count: number;
      total_freed_bytes: number;
      total_freed_mb: number;
    }>('/api/sessions/batch_delete', {
      method: 'POST',
      body: JSON.stringify({ sessions: sessions.map(sessionKey) }),
    }),

  /** 后端把结果包在 data 里（{success, data:{output_path,message,warnings}}） */
  async migrateSession(catalogId: string, targetFormat: string) {
    const raw = await fetchJson<{
      success: boolean;
      data?: { output_path?: string; message?: string; warnings?: unknown[] };
      error?: string;
    }>('/api/session/migrate', {
      method: 'POST',
      body: JSON.stringify({ catalog_id: catalogId, target_format: targetFormat }),
    });
    if (raw.success === false) throw new Error(raw.error || '迁移失败');
    return {
      outputPath: raw.data?.output_path || '',
      message: raw.data?.message || '',
      warnings: raw.data?.warnings || [],
    };
  },

  batchMigrateSessions: (catalogIds: string[], targetFormat: string) =>
    fetchJson<{ success: boolean; success_count: number; failed_count: number; total: number }>(
      '/api/sessions/batch_migrate',
      { method: 'POST', body: JSON.stringify({ catalog_ids: catalogIds, target_format: targetFormat }) }
    ),

  addRoot: (format: string, path: string) =>
    fetchJson<{ success: boolean; message?: string }>('/api/catalog/add_root', {
      method: 'POST',
      body: JSON.stringify({ format, path }),
    }),

  /** 后端按 root id 移除，不是按 format + path */
  removeRoot: (id: number) =>
    fetchJson<{ success: boolean }>('/api/catalog/remove_root', {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),
};
