'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';
import useSWRInfinite from 'swr/infinite';
import { Header } from '../components/layout/Header';
import { Toolbar } from '../components/layout/Toolbar';
import { SessionGrid } from '../components/sessions/SessionGrid';
import { GlobalSearchModal } from '../components/search/GlobalSearchModal';
import { SessionDetailModal } from '../components/detail/SessionDetailModal';
import { SubagentDrawer } from '../components/sessions/SubagentDrawer';
import { RootsModal } from '../components/modals/RootsModal';
import { MigrateModal } from '../components/modals/MigrateModal';
import { BatchManagementDrawer } from '../components/batch/BatchManagementDrawer';
import { api } from '../api/client';
import { useStore } from '../store/useStore';
import { Loader2 } from 'lucide-react';
import { SessionListResponse, SessionItem } from '../types/session';

/** 首屏条数：与后端 limit=60 的字节预算对齐（实测约 39.7 KB） */
const PAGE_SIZE = 60;
/** 输入停顿多久后才把关键词交给服务端，避免逐字触发整表查询 */
const SEARCH_DEBOUNCE_MS = 220;

type ListKey = {
  page: number;
  q: string;
  format: string;
  sortBy: string;
  order: 'asc' | 'desc';
  fold: boolean;
  limit: number;
  dataVersion: number;
};

/** 把连续输入收敛成一次请求；本地过滤用同一份值，保证"看到的"与"请求的"一致 */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const fetchPage = (key: ListKey): Promise<SessionListResponse> =>
  api.getSessions({
    q: key.q,
    format: key.format,
    sortBy: key.sortBy,
    order: key.order,
    limit: key.limit,
    offset: key.page * key.limit,
    fields: 'lite',
    fold: key.fold,
  });

export default function WorkspacePage() {
  const { activeFilter, searchQuery, sortField, sortOrder, isScanning, foldLineage, dataVersion } =
    useStore();

  const query = useDebounced(searchQuery.trim(), SEARCH_DEBOUNCE_MS);

  /**
   * 分页 key。
   * `page` 是页序号，不是 offset —— 组件只认"已请求几页"，offset 由 fetcher 换算。
   * 关键词 / 平台 / 排序 / 折叠 / 数据版本任一变化都会换 key，SWR 会把 size 重置为
   * initialSize(=1)，即"回到第一批"。
   */
  const getKey = useCallback(
    (pageIndex: number, prev: SessionListResponse | null): ListKey | null => {
      // 上一页已经到底就不再请求下一页（getKey 返回 null 即终止）
      if (prev && !prev.hasMore) return null;
      return {
        page: pageIndex,
        q: query,
        format: activeFilter,
        sortBy: sortField,
        order: sortOrder,
        fold: foldLineage,
        limit: PAGE_SIZE,
        dataVersion,
      };
    },
    [query, activeFilter, sortField, sortOrder, foldLineage, dataVersion]
  );

  const { data: pages, size, setSize, isValidating, mutate } = useSWRInfinite<SessionListResponse>(
    getKey,
    fetchPage,
    {
      initialSize: 1,
      revalidateFirstPage: false,
      revalidateAll: false,
      revalidateOnFocus: false,
      parallel: false,
      dedupingInterval: 2000,
      keepPreviousData: true,
    }
  );

  const { data: status, mutate: mutateStatus } = useSWR('/api/status', () => api.getStatus(), {
    revalidateOnFocus: false,
  });

  const refreshAll = useCallback(() => {
    void mutate();
    void mutateStatus();
  }, [mutate, mutateStatus]);

  const pageList = pages || [];
  const sessions = useMemo<SessionItem[]>(
    () => pageList.flatMap((p) => p.sessions || []),
    [pageList]
  );

  /** 服务端给的匹配总数（无 meta 的后端回落为已加载条数，与改造前一致） */
  const serverTotal = pageList.length > 0 ? pageList[0].total : 0;
  const lastPage = pageList.length > 0 ? pageList[pageList.length - 1] : null;
  const hasMore = Boolean(lastPage?.hasMore);
  // 后端返回了空页但声称还有下一页时不自动续拉，避免空转
  const lastPageEmpty = Boolean(lastPage && (lastPage.sessions || []).length === 0);
  const isLoadingMore = isValidating && sessions.length > 0;
  const isFirstLoading = !pages && isValidating;

  const locallyFoldedOut = useMemo(
    () =>
      foldLineage
        ? sessions.filter((s) => s.lineageSize > 1 && s.isLineageBranch).length
        : 0,
    [sessions, foldLineage]
  );

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    let list = sessions;
    // 折叠同源分叉：服务端 fold=1 时这里已是空操作，保留作后端未升级时的兜底
    if (foldLineage) list = list.filter((s) => !(s.lineageSize > 1 && s.isLineageBranch));
    if (!q) return list;
    return list.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.sessionId.toLowerCase().includes(q) ||
        s.format.toLowerCase().includes(q) ||
        s.filePath.toLowerCase().includes(q)
    );
  }, [sessions, query, foldLineage]);

  const stats = useMemo(() => {
    let bytes = 0;
    let tokens = 0;
    for (const s of filtered) {
      bytes += s.bytes || 0;
      tokens += s.tokens || 0;
    }
    return { bytes, tokens };
  }, [filtered]);

  const sentinelRef = useRef<HTMLDivElement>(null);

  const loadMore = useCallback(() => {
    if (!hasMore || isValidating || lastPageEmpty) return;
    void setSize(size + 1);
  }, [hasMore, isValidating, lastPageEmpty, setSize, size]);

  // 滚动到底自动续拉：IntersectionObserver 负责"进入视口"，下面的 effect 负责
  // 一页加载完哨兵仍在视口内时继续补，直到哨兵被推出屏幕。
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMore();
      },
      { rootMargin: '400px 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore]);

  useEffect(() => {
    if (!hasMore || isValidating || lastPageEmpty) return;
    const el = sentinelRef.current;
    if (!el) return;
    if (el.getBoundingClientRect().top < window.innerHeight + 240) loadMore();
  }, [hasMore, isValidating, lastPageEmpty, loadMore, sessions.length]);

  return (
    <div className="min-h-screen bg-canvas flex flex-col">
      <Header onRefresh={refreshAll} />

      <main className="flex-1 w-full max-w-shell mx-auto px-4 md:px-6 py-4 md:py-5 space-y-4">
        <Toolbar
          totalSessions={status?.totalSessions || serverTotal || sessions.length}
          matchCount={Math.max(0, (serverTotal || sessions.length) - locallyFoldedOut)}
          totalBytes={stats.bytes}
          totalTokens={stats.tokens}
          formatCounts={status?.formatCounts || {}}
        />
        {isScanning && (
          <div className="flex items-center gap-2 px-3.5 py-2 rounded-md border border-accent/30 bg-accent-soft text-[12px] text-accent-ink">
            <Loader2 size={13} className="animate-spin" />
            正在全量扫描会话目录，期间列表浏览可能较慢，请稍候…
          </div>
        )}

        <div className={isScanning ? 'pointer-events-none opacity-60 transition-opacity' : 'transition-opacity'}>
          <SessionGrid
            sessions={filtered}
            isLoading={isFirstLoading && sessions.length === 0}
            onChanged={refreshAll}
            hasQuery={Boolean(searchQuery.trim())}
          />
        </div>

        {/* 续拉哨兵 + 加载态：只在还有下一页时出现，不参与网格布局 */}
        {hasMore && (
          <div ref={sentinelRef} aria-hidden className="h-px w-full" />
        )}
        {hasMore && isLoadingMore && (
          <div className="py-3 text-center text-[11.5px] text-ink-faint">加载中…</div>
        )}
      </main>

      <GlobalSearchModal />
      <SessionDetailModal />
      <SubagentDrawer />
      <RootsModal onRootsChanged={refreshAll} />
      <MigrateModal />
      <BatchManagementDrawer sessions={filtered} onBatchActionFinished={refreshAll} />
    </div>
  );
}
