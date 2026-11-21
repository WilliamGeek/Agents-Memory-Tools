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
  'doubao',
  'codex',
  'cursor',
  'copilot',
];

const SORTS = [
  { value: 'mtime', label: '最近活跃' },
  { value: 'started_at', label: '创建时间' },
  { value: 'bytes', label: '文件大小' },
  { value: 'tokens', label: 'Token 数量' },
  { value: 'records', label: '交互步数' },
  { value: 'title', label: '标题名称' },
  { value: 'format', label: '平台类型' },
];

export function Toolbar({
  totalSessions,
  matchCount,
  totalBytes,
  totalTokens,
  formatCounts,
  countsPending = false,
}: {
  totalSessions: number;
  matchCount: number;
  totalBytes: number;
  totalTokens: number;
  formatCounts: Record<string, number>;
  countsPending?: boolean;
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

  const chipsRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const el = chipsRef.current;
    if (!el) return;
    const handleWheel = (event: WheelEvent) => {
      // 只接管纵向滚轮；触控板的横向滑动交给浏览器原生滚动
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      if (el.scrollWidth <= el.clientWidth) return;
      event.preventDefault();
      const step = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      el.scrollLeft += step;
    };
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, []);

  return (
    <section className="bg-surface border border-line rounded-card shadow-card px-3 py-2 flex flex-wrap items-center gap-2">
      {/* 搜索 */}
      <div className="relative w-full lg:w-56 shrink-0">
        <Search
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
        />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索会话名称、UUID、智能体..."
          className="w-full h-8 pl-8 pr-7 rounded-md bg-surface-muted border border-line text-[12.5px] text-ink placeholder:text-ink-faint focus:bg-surface transition-colors"
        />
        {searchQuery && (
          <button
            onClick={() => setSearchQuery('')}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-ink-faint hover:text-ink"
            title="清空"
          >
            <X size={12} />
          </button>
        )}
      </div>

      {/* 平台筛选 chips：单行横向滚动；滚轮停在筛选条上时，把纵向滚动转成横向移动 */}
      <div
        ref={chipsRef}
        className="flex items-center gap-1 overflow-x-auto no-scrollbar overscroll-x-contain flex-1 min-w-0 py-0.5"
      >
        {FILTERS.map((f) => {
          const active = activeFilter === f;
          const meta = f === 'all' ? null : platformMeta(f);
          const count = f === 'all' ? totalSessions : formatCounts[f] || 0;
          if (f !== 'all' && count === 0) return null;
          return (
            <button
              key={f}
              onClick={() => setActiveFilter(f)}
              className={`h-7 px-2.5 rounded-full text-[12px] shrink-0 inline-flex items-center gap-1.5 border transition-colors ${
                active
                  ? 'bg-accent-soft border-accent/40 text-accent-ink font-medium'
                  : 'bg-surface border-line text-ink-muted hover:border-line-strong hover:text-ink'
              }`}
            >
              {meta && (
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: meta.color }} />
              )}
              <span>{f === 'all' ? '全部' : meta!.label}</span>
              <span className={`tnum text-[10.5px] ${active ? 'text-accent' : 'text-ink-faint'}`}>
                {countsPending ? '—' : count}
              </span>
            </button>
          );
        })}
      </div>

      {/* 排序 / 升降序 / 折叠分叉 / 统计 */}
      <div className="flex items-center gap-1.5 shrink-0 ml-auto">
        <select
          value={sortField}
          onChange={(e) => setSortField(e.target.value)}
          className="h-8 px-2 rounded-md bg-surface-muted border border-line text-[12px] text-ink-soft cursor-pointer"
          title="选择会话排序依据"
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <button
          onClick={toggleSortOrder}
          className="h-8 w-8 rounded-md bg-surface-muted border border-line flex items-center justify-center text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
          title={sortOrder === 'desc' ? '当前降序，点击切换升序' : '当前升序，点击切换降序'}
        >
          {sortOrder === 'desc' ? <ArrowDownWideNarrow size={14} /> : <ArrowUpNarrowWide size={14} />}
        </button>
        <button
          onClick={toggleFoldLineage}
          aria-pressed={foldLineage}
          className={`h-8 w-8 rounded-md border flex items-center justify-center transition-colors ${
            foldLineage
              ? 'border-warn/40 bg-warn-soft text-warn'
              : 'border-line bg-surface-muted text-ink-muted hover:text-ink hover:bg-surface-sunken'
          }`}
          title="折叠同一条对话的分叉快照（Antigravity 分叉 / 副本），只保留主副本"
        >
          <CopyMinus size={14} />
        </button>

        <div
          className="hidden xl:flex items-center gap-1 pl-1 text-[11px] text-ink-muted tnum whitespace-nowrap"
          title="当前匹配的会话统计"
        >
          {countsPending ? (
            <span>统计加载中…</span>
          ) : (
            <>
              总收录 <strong className="text-ink font-medium">{formatCount(totalSessions)}</strong> · 匹配{' '}
              <strong className="text-ink font-medium">{formatCount(matchCount)}</strong> 篇 ·{' '}
              {formatBytes(totalBytes)} ·{' '}
              <strong className="text-accent-ink font-medium">{formatTokens(totalTokens)} 累计 Tokens</strong>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
