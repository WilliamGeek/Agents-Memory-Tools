'use client';

import React from 'react';
import { Search, X, ArrowDownWideNarrow, ArrowUpNarrowWide, CopyMinus } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { AgentFormatType } from '../../types/session';
import { formatBytes, formatTokens, formatCount } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

const FILTERS: AgentFormatType[] = [
  'all',
  'antigravity',
  'claude',
  'workbuddy',
  'trae',
  'cursor',
  'copilot',
];

const SORTS = [
  { value: 'mtime', label: '最近活跃' },
  { value: 'started_at', label: '创建时间' },
  { value: 'records', label: '对话步数' },
  { value: 'bytes', label: '文件体积' },
  { value: 'tokens', label: 'Token 用量' },
  { value: 'title', label: '会话名称' },
  { value: 'format', label: '平台类型' },
];

export function Toolbar({
  totalSessions,
  matchCount,
  totalBytes,
  totalTokens,
  formatCounts,
}: {
  totalSessions: number;
  matchCount: number;
  totalBytes: number;
  totalTokens: number;
  formatCounts: Record<string, number>;
}) {
  const {
    activeFilter,
    setActiveFilter,
    searchQuery,
    setSearchQuery,
    sortField,
    setSortField,
    sortOrder,
    toggleSortOrder,
    foldLineage,
    toggleFoldLineage,
  } = useStore();

  return (
    <section className="bg-surface border border-line rounded-card shadow-card">
      {/* 第一行：检索 + 排序 */}
      <div className="p-3.5 flex flex-col lg:flex-row lg:items-center gap-3">
        <div className="relative flex-1 lg:max-w-md">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索会话标题、平台或 UUID"
            className="w-full h-9 pl-9 pr-9 rounded-md bg-surface-muted border border-line text-[13px] text-ink placeholder:text-ink-faint focus:bg-surface transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-ink-faint hover:text-ink hover:bg-surface-sunken"
              title="清空"
            >
              <X size={13} />
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 lg:ml-auto">
          <label className="text-[11.5px] text-ink-faint hidden sm:inline">排序</label>
          <select
            value={sortField}
            onChange={(e) => setSortField(e.target.value)}
            className="h-9 px-2.5 rounded-md bg-surface-muted border border-line text-[12.5px] text-ink-soft cursor-pointer"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <button
            onClick={toggleSortOrder}
            className="h-9 w-9 rounded-md bg-surface-muted border border-line flex items-center justify-center text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
            title={sortOrder === 'desc' ? '当前降序，点击切换升序' : '当前升序，点击切换降序'}
          >
            {sortOrder === 'desc' ? (
              <ArrowDownWideNarrow size={15} />
            ) : (
              <ArrowUpNarrowWide size={15} />
            )}
          </button>

          <button
            onClick={toggleFoldLineage}
            aria-pressed={foldLineage}
            className={`h-9 px-2.5 rounded-md border text-[12px] inline-flex items-center gap-1.5 transition-colors ${
              foldLineage
                ? 'border-warn/40 bg-warn-soft text-warn'
                : 'border-line bg-surface-muted text-ink-muted hover:text-ink hover:bg-surface-sunken'
            }`}
            title="折叠同一条对话的分叉快照（Antigravity 分叉 / 副本），只保留主副本"
          >
            <CopyMinus size={13} />
            <span className="hidden sm:inline">折叠分叉</span>
          </button>
        </div>
      </div>

      {/* 第二行：平台筛选 + 汇总 */}
      <div className="px-3.5 pb-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-2.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {FILTERS.map((f) => {
            const active = activeFilter === f;
            const meta = f === 'all' ? null : platformMeta(f);
            const count = f === 'all' ? totalSessions : formatCounts[f] || 0;
            if (f !== 'all' && count === 0) return null;
            return (
              <button
                key={f}
                onClick={() => setActiveFilter(f)}
                className={`h-7 px-2.5 rounded-full text-[12px] inline-flex items-center gap-1.5 border transition-colors ${
                  active
                    ? 'bg-accent-soft border-accent/40 text-accent-ink font-medium'
                    : 'bg-surface border-line text-ink-muted hover:border-line-strong hover:text-ink'
                }`}
              >
                {meta && (
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: meta.color }}
                  />
                )}
                <span>{f === 'all' ? '全部' : meta!.label}</span>
                <span className={`tnum text-[10.5px] ${active ? 'text-accent' : 'text-ink-faint'}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-2 text-[11.5px] text-ink-muted tnum">
          <span>
            匹配 <strong className="text-ink font-medium">{formatCount(matchCount)}</strong> 篇
          </span>
          <span className="text-line-strong">|</span>
          <span>{formatBytes(totalBytes)}</span>
          <span className="text-line-strong">|</span>
          <span>{formatTokens(totalTokens)} Tokens</span>
        </div>
      </div>
    </section>
  );
}
