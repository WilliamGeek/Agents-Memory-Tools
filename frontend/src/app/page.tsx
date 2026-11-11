'use client';

import React, { useCallback, useMemo } from 'react';
import useSWR from 'swr';
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
import { formatBytes, formatTokens } from '../lib/format';

export default function WorkspacePage() {
  const { activeFilter, searchQuery, sortField, sortOrder, isScanning, foldLineage, dataVersion } =
    useStore();

  const { data, isLoading, mutate } = useSWR(
    ['/api/sessions', activeFilter, sortField, sortOrder, dataVersion],
    () => api.getSessions({ format: activeFilter, sortBy: sortField, order: sortOrder }),
    { revalidateOnFocus: false, dedupingInterval: 2000 }
  );

  const { data: status, mutate: mutateStatus } = useSWR('/api/status', () => api.getStatus(), {
    revalidateOnFocus: false,
  });

  const refreshAll = useCallback(() => {
    void mutate();
    void mutateStatus();
  }, [mutate, mutateStatus]);

  const sessions = data?.sessions || [];

  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    let list = sessions;
    // 折叠同源分叉：只保留每组的主副本，避免同一对话刷屏
    if (foldLineage) list = list.filter((s) => !(s.lineageSize > 1 && s.isLineageBranch));
    if (!q) return list;
    return list.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.sessionId.toLowerCase().includes(q) ||
        s.format.toLowerCase().includes(q) ||
        s.filePath.toLowerCase().includes(q)
    );
  }, [sessions, searchQuery, foldLineage]);

  const stats = useMemo(() => {
    let bytes = 0;
    let tokens = 0;
    for (const s of filtered) {
      bytes += s.bytes || 0;
      tokens += s.tokens || 0;
    }
    return { bytes, tokens };
  }, [filtered]);

  return (
    <div className="min-h-screen bg-canvas flex flex-col">
      <Header onRefresh={refreshAll} />

      <main className="flex-1 w-full max-w-shell mx-auto px-4 md:px-6 py-4 md:py-5 space-y-4">
        <Toolbar
          totalSessions={status?.totalSessions || sessions.length}
          matchCount={filtered.length}
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
            isLoading={isLoading && sessions.length === 0}
            onChanged={refreshAll}
            hasQuery={Boolean(searchQuery.trim())}
          />
        </div>
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

