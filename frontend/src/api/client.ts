import {
  AppStatus,
  SessionDetail,
  SessionItem,
  SessionListResponse,
  SearchResponse,
} from '../types/session';
import {
  normalizeDetail,
  normalizeSearchResult,
  normalizeSession,
  normalizeStatus,
} from './normalize';

/**
 * 后端在「扫描目录」期间会持有 catalog 写锁，并发的读请求可能长时间排队。
 * 这里统一加超时，避免界面无限转圈——超时后给出可读的错误，而不是假装在加载。
 */
async function fetchJson<T>(url: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { timeoutMs = 25000, ...init } = options || {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
      cache: 'no-store',
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(timer);
    if (e?.name === 'AbortError') {
      throw new Error('请求超时，后端可能正在执行扫描或索引，请稍后重试');
    }
    throw new Error(e?.message || '网络请求失败');
  }
  clearTimeout(timer);

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

export const api = {
  async getStatus(): Promise<AppStatus> {
    return normalizeStatus(await fetchJson<Record<string, any>>('/api/status'));
  },

  async getSessions(params?: {
    q?: string;
    format?: string;
    sortBy?: string;
    order?: 'asc' | 'desc';
  }): Promise<SessionListResponse> {
    const sp = new URLSearchParams();
    if (params?.q) sp.set('q', params.q);
    if (params?.format && params.format !== 'all') sp.set('format', params.format);
    if (params?.sortBy) sp.set('sort_by', params.sortBy);
    if (params?.order) sp.set('order', params.order);
    const raw = await fetchJson<{ sessions?: Record<string, any>[]; count?: number }>(
      `/api/sessions?${sp.toString()}`
    );
    const sessions = (raw.sessions || []).map(normalizeSession);
    return { sessions, count: raw.count ?? sessions.length };
  },

  async getSessionDetail(catalogId: string): Promise<SessionDetail> {
    const raw = await fetchJson<Record<string, any>>(
      `/api/session/detail?catalog_id=${encodeURIComponent(catalogId)}`,
      { timeoutMs: 15000 }
    );
    if (raw?.error) throw new Error(String(raw.error));
    return normalizeDetail(raw);
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
