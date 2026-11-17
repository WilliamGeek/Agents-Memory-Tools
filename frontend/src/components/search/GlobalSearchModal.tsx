'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Search,
  X,
  ArrowUpRight,
  CornerDownLeft,
  Loader2,
  FileSearch,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SearchResultItem, SessionItem } from '../../types/session';
import { ModalShell } from '../ui/Overlay';
import { formatClock, formatDateTime, stripDatePrefix } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

type SearchScope = 'all' | 'sessions' | 'messages';

interface SessionCardData {
  catalogId: string;
  title: string;
  format: string;
  startedAt?: string;
  records?: number;
  matchCount: number;
  firstTurn?: number;
}

const SESSION_LIMIT = 30;
const MESSAGE_LIMIT = 80;

function buildSessionCards(
  titleSessions: SessionItem[],
  messages: SearchResultItem[]
): { cards: SessionCardData[]; total: number } {
  const grouped = new Map<string, SessionCardData>();
  for (const session of titleSessions) {
    grouped.set(session.catalogId, {
      catalogId: session.catalogId,
      title: session.title,
      format: session.format,
      startedAt: session.startedAt,
      records: session.records,
      matchCount: 0,
    });
  }

  for (const message of messages) {
    const current = grouped.get(message.catalogId);
    if (current) {
      current.matchCount += 1;
      if (message.turnIndex > 0 && (!current.firstTurn || message.turnIndex < current.firstTurn)) {
        current.firstTurn = message.turnIndex;
      }
      if (!current.title) current.title = message.sessionTitle;
      if (!current.format) current.format = message.sessionFormat;
      if (!current.startedAt) current.startedAt = message.timestamp;
      continue;
    }
    grouped.set(message.catalogId, {
      catalogId: message.catalogId,
      title: message.sessionTitle,
      format: message.sessionFormat,
      startedAt: message.timestamp,
      matchCount: 1,
      firstTurn: message.turnIndex > 0 ? message.turnIndex : undefined,
    });
  }

  const cards = Array.from(grouped.values()).sort((a, b) => {
    if (b.matchCount !== a.matchCount) return b.matchCount - a.matchCount;
    return String(b.startedAt || '').localeCompare(String(a.startedAt || ''));
  });
  return { cards, total: cards.length };
}

function messageTag(item: SearchResultItem): { label: string; className: string } {
  const kind = (item.kind || '').toLowerCase();
  if (kind === 'tool_call' || kind === 'tool_result' || kind === 'action' || item.role === 'tool') {
    return { label: '行动', className: 'bg-warn-soft text-warn' };
  }
  if (kind === 'thinking' || kind === 'reasoning' || item.role === 'system') {
    return { label: '思考', className: 'bg-surface-sunken text-ink-muted' };
  }
  if (item.role === 'user') {
    return { label: '用户指令', className: 'bg-accent-soft text-accent-ink' };
  }
  return { label: '回复', className: 'bg-ok-soft text-ok' };
}

function SessionHit({
  session,
  onOpen,
}: {
  session: SessionCardData;
  onOpen: () => void;
}) {
  const meta = platformMeta(session.format);
  const title = stripDatePrefix(session.title) || session.catalogId;
  return (
    <button
      onClick={onOpen}
      className="w-full text-left rounded-lg border border-transparent hover:border-line hover:bg-surface-muted px-2.5 py-2 transition-colors group"
    >
      <div className="flex items-center gap-2 text-[11.5px] mb-1 min-w-0">
        <span className="inline-flex items-center gap-1 text-ink-muted shrink-0">
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: meta.color }}
          />
          {meta.label}
        </span>
        <span className="text-[12.5px] font-medium text-ink truncate">{title}</span>
        <span className="ml-auto text-[11px] text-ink-faint shrink-0 tnum">
          {formatDateTime(session.startedAt)}
        </span>
        <span className="text-accent-ink opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          <ArrowUpRight size={12} />
        </span>
      </div>
      <div className="flex items-center gap-2 text-[11px] text-ink-muted pl-3.5">
        {typeof session.records === 'number' && <span className="tnum">{session.records} 步</span>}
        {session.matchCount > 0 && (
          <span className="tnum">匹配 {session.matchCount} 条消息</span>
        )}
        {session.catalogId && (
          <span className="truncate max-w-[24rem] opacity-70" title={session.catalogId}>
            {session.catalogId}
          </span>
        )}
      </div>
    </button>
  );
}

export function GlobalSearchModal() {
  const { isGlobalSearchOpen, setIsGlobalSearchOpen, openSessionDetail } = useStore();
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<SearchScope>('all');
  const [sessions, setSessions] = useState<SessionCardData[]>([]);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [messageCount, setMessageCount] = useState(0);
  const [latency, setLatency] = useState(0);
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
    return () => clearTimeout(t);
  }, [isGlobalSearchOpen]);

  useEffect(() => {
    if (!query.trim()) {
      setSessions([]);
      setSessionTotal(0);
      setResults([]);
      setMessageCount(0);
      setLatency(0);
      setBusy(false);
      return;
    }

    let cancelled = false;
    setBusy(true);
    const timer = setTimeout(async () => {
      const q = query.trim();
      // 两个来源并行：会话标题/路径走 /api/sessions，消息正文走 FTS。
      // 任一来源失败不影响另一来源展示。
      const [messageRes, sessionRes] = await Promise.all([
        api.searchContent(q, MESSAGE_LIMIT).catch(() => null),
        api.getSessions({ q, limit: SESSION_LIMIT, fields: 'lite' }).catch(() => null),
      ]);
      if (cancelled) return;

      if (messageRes) {
        setResults(messageRes.results);
        setMessageCount(messageRes.count);
        setLatency(messageRes.latencyMs);
      } else {
        setResults([]);
        setMessageCount(0);
        setLatency(0);
      }

      const built = buildSessionCards(
        sessionRes?.sessions || [],
        messageRes?.results || []
      );
      setSessions(built.cards);
      setSessionTotal(Math.max(built.cards.length, sessionRes?.total || 0));
      setBusy(false);
    }, 180);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  const showSessions = scope !== 'messages' && sessions.length > 0;
  const showMessages = scope !== 'sessions' && results.length > 0;
  const activeCount =
    scope === 'sessions' ? sessionTotal : scope === 'messages' ? messageCount : sessionTotal + messageCount;
  const scopeTabs: Array<{ id: SearchScope; label: string }> = [
    { id: 'all', label: '全部' },
    { id: 'sessions', label: '会话' },
    { id: 'messages', label: '消息' },
  ];

  return (
    <ModalShell
      open={isGlobalSearchOpen}
      onClose={close}
      width="max-w-3xl"
      icon={<Search size={15} />}
      title="检索"
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
            placeholder="搜索会话标题或消息内容，例如：FTS5、评估报告、启动报错…"
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

        <div className="flex items-center gap-1.5 border-b border-line pb-2">
          {scopeTabs.map((tab) => {
            const active = scope === tab.id;
            const count =
              tab.id === 'sessions' ? sessionTotal : tab.id === 'messages' ? messageCount : activeCount;
            return (
              <button
                key={tab.id}
                onClick={() => setScope(tab.id)}
                className={`h-7 px-2.5 rounded-md text-[11.5px] transition-colors ${
                  active
                    ? 'bg-accent text-white'
                    : 'text-ink-muted hover:text-ink hover:bg-surface-sunken'
                }`}
              >
                {tab.label}
                {query && count > 0 ? <span className="ml-1 tnum opacity-80">{count}</span> : null}
              </button>
            );
          })}
          <span className="ml-auto text-[11px] text-ink-faint tnum">
            {query ? (
              busy ? (
                '检索中…'
              ) : (
                `耗时 ${latency} ms`
              )
            ) : (
              '输入关键词同时检索会话与消息'
            )}
          </span>
          <span className="hidden sm:flex items-center gap-1.5 text-[10.5px] text-ink-faint">
            <kbd className="px-1.5 py-0.5 rounded border border-line bg-surface-sunken">
              <CornerDownLeft size={9} className="inline" />
            </kbd>
            跳转
            <kbd className="px-1.5 py-0.5 rounded border border-line bg-surface-sunken">Esc</kbd>
            关闭
          </span>
        </div>

        <div className="max-h-[54vh] overflow-y-auto -mx-1 px-1 space-y-3">
          {!query && (
            <div className="py-14 text-center">
              <FileSearch size={22} className="mx-auto text-ink-faint mb-2" />
              <p className="text-[12.5px] text-ink-muted">输入关键词开始检索</p>
              <p className="text-[11.5px] text-ink-faint mt-1">
                结果会按“会话”和“消息”分开显示
              </p>
            </div>
          )}

          {query && !busy && activeCount === 0 && (
            <div className="py-14 text-center">
              <p className="text-[13px] text-ink">没有匹配「{query}」的会话或消息</p>
              <p className="text-[11.5px] text-ink-faint mt-1">试试更短的词，或换一种说法</p>
            </div>
          )}

          {showSessions && (
            <section className="space-y-1">
              <div className="flex items-center gap-2 px-2.5 text-[11px] text-ink-muted">
                <span className="font-medium text-ink">会话</span>
                <span className="tnum">{sessionTotal}</span>
                {sessionTotal > sessions.length && (
                  <span className="text-ink-faint">显示前 {sessions.length} 条</span>
                )}
              </div>
              {sessions.map((session) => (
                <SessionHit
                  key={session.catalogId}
                  session={session}
                  onOpen={() => {
                    close();
                    openSessionDetail(session.catalogId, session.firstTurn);
                  }}
                />
              ))}
            </section>
          )}

          {scope === 'sessions' && query && !busy && sessionTotal === 0 && (
            <div className="py-8 text-center text-[12px] text-ink-muted">没有匹配的会话</div>
          )}

          {showMessages && (
            <section className="space-y-1">
              <div className="flex items-center gap-2 px-2.5 text-[11px] text-ink-muted">
                <span className="font-medium text-ink">消息</span>
                <span className="tnum">{messageCount}</span>
                {messageCount > results.length && (
                  <span className="text-ink-faint">显示前 {results.length} 条</span>
                )}
              </div>
              {results.map((r, i) => {
                const meta = platformMeta(r.sessionFormat);
                const tag = messageTag(r);
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
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${tag.className}`}>
                        {tag.label}
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
            </section>
          )}

          {scope === 'messages' && query && !busy && messageCount === 0 && (
            <div className="py-8 text-center text-[12px] text-ink-muted">没有匹配的消息</div>
          )}
        </div>
      </div>
    </ModalShell>
  );
}
