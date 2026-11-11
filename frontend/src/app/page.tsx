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
import { Loader2, MessagesSquare, HardDrive, Coins, Activity } from 'lucide-react';
import { formatBytes, formatTokens, formatCount } from '../lib/format';

export default function WorkspacePage() {
  const { activeFilter, searchQuery, sortField, sortOrder, isScanning } = useStore();

  const { data, isLoading, mutate } = useSWR(
    ['/api/sessions', activeFilter, sortField, sortOrder],
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
    if (!q) return sessions;
    return sessions.filter(
      (s) =>
        s.title.toLowerCase().includes(q) ||
        s.sessionId.toLowerCase().includes(q) ||
        s.format.toLowerCase().includes(q) ||
        s.filePath.toLowerCase().includes(q)
    );
  }, [sessions, searchQuery]);

  const kpi = useMemo(() => {
    let weekActive = 0;
    const weekAgo = Date.now() - 7 * 86400000;
    const formats = new Set<string>();
    for (const s of sessions) {
      formats.add(s.format);
      const last = s.mtime ? s.mtime * 1000 : 0;
      if (last >= weekAgo) weekActive += 1;
    }
    return { weekActive, formats: formats.size };
  }, [sessions]);

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

        <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiCard
            icon={<MessagesSquare size={14} />}
            label="收录会话"
            value={formatCount(status?.totalSessions || sessions.length)}
            sub={`覆盖 ${kpi.formats} 个平台`}
            color="#1f6feb"
          />
          <KpiCard
            icon={<HardDrive size={14} />}
            label="占用存储"
            value={formatBytes(stats.bytes)}
            sub={`平均 ${formatBytes(filtered.length ? stats.bytes / filtered.length : 0)} / 会话`}
            color="#0f9d58"
          />
          <KpiCard
            icon={<Coins size={14} />}
            label="Token 总量"
            value={formatTokens(stats.tokens)}
            sub="按全部命中会话累计"
            color="#c2710c"
          />
          <KpiCard
            icon={<Activity size={14} />}
            label="近 7 天活跃"
            value={formatCount(kpi.weekActive)}
            sub="按最后修改时间统计"
            color="#6d5efc"
          />
        </section>

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

function KpiCard({
  icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="bg-surface border border-line rounded-card px-3.5 py-3 shadow-card">
      <div className="flex items-center gap-1.5 text-[11px] text-ink-muted">
        <span style={{ color }}>{icon}</span>
        {label}
      </div>
      <div className="mt-1.5 text-[20px] font-semibold text-ink tnum leading-none">{value}</div>
      <div className="mt-1 text-[10.5px] text-ink-faint">{sub}</div>
    </div>
  );
}
