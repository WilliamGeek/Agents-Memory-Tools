'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Search, X, ArrowUpRight, CornerDownLeft, Loader2, FileSearch } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SearchResultItem } from '../../types/session';
import { ModalShell } from '../ui/Overlay';
import { formatClock } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

export function GlobalSearchModal() {
  const { isGlobalSearchOpen, setIsGlobalSearchOpen, openSessionDetail } = useStore();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [count, setCount] = useState(0);
  const [latency, setLatency] = useState(0);
  const [indexed, setIndexed] = useState(0);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const close = () => setIsGlobalSearchOpen(false);

  // 全局唤出
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        setIsGlobalSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setIsGlobalSearchOpen]);

  useEffect(() => {
    if (!isGlobalSearchOpen) return;
    const t = setTimeout(() => inputRef.current?.focus(), 30);
    api
      .searchContent('')
      .then((r) => setIndexed(r.totalIndexedTurns))
      .catch(() => {});
    return () => clearTimeout(t);
  }, [isGlobalSearchOpen]);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setCount(0);
      setBusy(false);
      return;
    }
    setBusy(true);
    const timer = setTimeout(async () => {
      try {
        const r = await api.searchContent(query.trim(), 80);
        setResults(r.results);
        setCount(r.count);
        setLatency(r.latencyMs);
        setIndexed(r.totalIndexedTurns);
      } catch {
        setResults([]);
      } finally {
        setBusy(false);
      }
    }, 180);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <ModalShell
      open={isGlobalSearchOpen}
      onClose={close}
      width="max-w-3xl"
      icon={<Search size={15} />}
      title="跨会话对话内容检索"
      subtitle={
        indexed > 0 ? `已索引 ${indexed.toLocaleString('zh-CN')} 轮历史对话` : '正在加载索引…'
      }
    >
      <div className="p-4 space-y-3">
        <div className="relative">
          <Search
            size={15}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
          />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入对话里的关键词或整句话，例如：FTS5、评估报告、启动报错…"
            className="w-full h-10 pl-9 pr-9 rounded-md bg-surface-muted border border-line text-[13.5px] text-ink placeholder:text-ink-faint focus:bg-surface transition-colors"
          />
          {busy ? (
            <Loader2
              size={15}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-accent animate-spin"
            />
          ) : query ? (
            <button
              onClick={() => setQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded text-ink-faint hover:text-ink hover:bg-surface-sunken"
              title="清空"
            >
              <X size={13} />
            </button>
          ) : null}
        </div>

        <div className="flex items-center justify-between text-[11.5px] text-ink-muted">
          <span className="tnum">
            {query ? (
              <>
                命中 <strong className="text-ink">{count}</strong> 处 · 耗时{' '}
                <strong className="text-accent-ink">{latency} ms</strong>
              </>
            ) : (
              '支持跨平台、跨会话的中文全文检索'
            )}
          </span>
          <span className="hidden sm:flex items-center gap-2 text-[11px] text-ink-faint">
            <kbd className="px-1.5 py-0.5 rounded border border-line bg-surface-sunken">
              <CornerDownLeft size={9} className="inline" />
            </kbd>
            跳转对应轮次
            <kbd className="px-1.5 py-0.5 rounded border border-line bg-surface-sunken">Esc</kbd>
            关闭
          </span>
        </div>

        <div className="max-h-[54vh] overflow-y-auto -mx-1 px-1 space-y-1.5">
          {!query && (
            <div className="py-14 text-center">
              <FileSearch size={22} className="mx-auto text-ink-faint mb-2" />
              <p className="text-[12.5px] text-ink-muted">输入关键词开始检索</p>
              <p className="text-[11.5px] text-ink-faint mt-1">
                结果可精确跳转到对应会话的具体轮次
              </p>
            </div>
          )}

          {query && !busy && results.length === 0 && (
            <div className="py-14 text-center">
              <p className="text-[13px] text-ink">没有匹配「{query}」的对话</p>
              <p className="text-[11.5px] text-ink-faint mt-1">试试更短的词，或换一种说法</p>
            </div>
          )}

          {results.map((r, i) => {
            const meta = platformMeta(r.sessionFormat);
            return (
              <button
                key={`${r.catalogId}-${r.turnIndex}-${i}`}
                onClick={() => {
                  close();
                  openSessionDetail(r.catalogId, r.turnIndex);
                }}
                className="w-full text-left rounded-lg border border-transparent hover:border-line hover:bg-surface-muted px-2.5 py-2 transition-colors group"
              >
                <div className="flex items-center gap-2 text-[11px] mb-1">
                  <span className="inline-flex items-center gap-1 text-ink-muted">
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ backgroundColor: meta.color }}
                    />
                    {meta.label}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] ${
                      r.role === 'user'
                        ? 'bg-accent-soft text-accent-ink'
                        : 'bg-ok-soft text-ok'
                    }`}
                  >
                    {r.role === 'user' ? '用户' : '助手'}
                  </span>
                  {r.turnIndex > 0 && (
                    <span className="tnum text-ink-faint">第 {r.turnIndex} 轮</span>
                  )}
                  <span className="text-ink-faint tnum">{formatClock(r.timestamp)}</span>
                  <span className="text-ink-soft truncate max-w-[16rem]" title={r.sessionTitle}>
                    {r.sessionTitle}
                  </span>
                  <span className="ml-auto text-accent-ink opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1 text-[11px]">
                    跳转 <ArrowUpRight size={11} />
                  </span>
                </div>
                <div
                  className="text-[12.5px] leading-relaxed text-ink-muted line-clamp-2 [&>mark]:bg-warn-soft [&>mark]:text-warn [&>mark]:rounded-sm [&>mark]:px-0.5"
                  dangerouslySetInnerHTML={{ __html: r.snippet }}
                />
              </button>
            );
          })}
        </div>
      </div>
    </ModalShell>
  );
}
