'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronUp,
  ChevronDown,
  Copy,
  Check,
  Terminal,
  Sparkles,
  MessageSquare,
  AlertTriangle,
  Loader2,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SessionDetail, SessionEvent } from '../../types/session';
import { toast } from 'sonner';
import { ModalShell } from '../ui/Overlay';
import { formatClock, formatDateTime, stripDatePrefix } from '../../lib/format';
import { platformMeta } from '../../lib/platform';
import { renderMarkdown } from '../../lib/markdown';

type ViewMode = 'compact' | 'summary' | 'full';

type ToolData = {
  type: 'tool';
  name: string;
  input: string;
  output: string;
  error: boolean;
  ts: string;
};

type TraceItem = { type: 'think'; text: string; ts: string } | ToolData;

type Block =
  | TraceItem
  | { type: 'trace'; items: TraceItem[] }
  | { type: 'text'; text: string; ts: string }
  | { type: 'opaque'; text: string; ts: string };

interface Turn {
  index: number;
  user?: SessionEvent;
  blocks: Block[];
}

function pickToolInput(payload: any): string {
  const input = payload?.input ?? payload;
  if (!input) return '';
  if (typeof input === 'string') return input;
  const keys = [
    'CommandLine',
    'command',
    'cmd',
    'path',
    'file_path',
    'AbsolutePath',
    'TargetFile',
    'query',
    'url',
    'pattern',
  ];
  for (const k of keys) {
    if (typeof input[k] === 'string' && input[k]) return input[k];
  }
  try {
    return JSON.stringify(input, null, 2);
  } catch {
    return '';
  }
}

function buildTurns(events: SessionEvent[], mode: ViewMode): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  const ensureTurn = (): Turn => {
    if (!current) {
      current = { index: 1, blocks: [] };
      turns.push(current);
    }
    return current;
  };

  for (const evt of events) {
    const ts = evt.timestamp;
    if (evt.kind === 'message' && evt.role === 'user') {
      current = { index: turns.length + 1, user: evt, blocks: [] };
      turns.push(current);
      continue;
    }
    const turn = ensureTurn();

    if (evt.kind === 'thinking') {
      if (mode === 'compact') continue;
      if (!evt.text.trim()) continue;
      turn.blocks.push({ type: 'think', text: evt.text, ts });
      continue;
    }

    if (evt.kind === 'tool_call') {
      if (mode === 'compact') continue;
      turn.blocks.push({
        type: 'tool',
        name: evt.toolName || 'tool',
        input: pickToolInput(evt.payload),
        output: '',
        error: false,
        ts,
      });
      continue;
    }

    if (evt.kind === 'tool_result') {
      if (mode === 'compact') continue;
      const last = [...turn.blocks].reverse().find((b) => b.type === 'tool') as
        | Extract<Block, { type: 'tool' }>
        | undefined;
      const isError = Boolean((evt.payload as any)?.is_error);
      const output = evt.text || '';
      if (last && !last.output) {
        last.output = output;
        last.error = isError;
      } else if (output) {
        turn.blocks.push({
          type: 'tool',
          name: evt.toolName || 'tool',
          input: '',
          output,
          error: isError,
          ts,
        });
      }
      continue;
    }

    if (evt.kind === 'opaque') {
      if (mode !== 'full') continue;
      const raw =
        evt.text ||
        (typeof evt.payload === 'object' && evt.payload
          ? JSON.stringify(evt.payload)
          : String(evt.payload ?? ''));
      if (!raw.trim()) continue;
      turn.blocks.push({ type: 'opaque', text: raw, ts });
      continue;
    }

    // assistant message
    if (evt.text.trim()) turn.blocks.push({ type: 'text', text: evt.text, ts });
  }

  // 连续的工具调用聚合成一组，避免一轮里出现几十张碎片卡片
  // 摘要模式：把成片的「思考 + 工具调用」压成一段可展开的执行过程，只留结论
  if (mode === 'summary') {
    for (const turn of turns) {
      const merged: Block[] = [];
      let bucket: TraceItem[] = [];
      const flush = () => {
        if (bucket.length) {
          merged.push({ type: 'trace', items: bucket });
          bucket = [];
        }
      };
      for (const block of turn.blocks) {
        if (block.type === 'think' || block.type === 'tool') bucket.push(block);
        else {
          flush();
          merged.push(block);
        }
      }
      flush();
      turn.blocks = merged;
    }
  }

  return turns;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        } catch {
          toast.error('复制失败，请手动选择文本');
        }
      }}
      className="p-1 rounded text-ink-faint hover:text-ink hover:bg-surface-sunken transition-colors"
      title={label}
      aria-label={label}
    >
      {done ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
    </button>
  );
}

function ThinkBlock({ block, open }: { block: Extract<Block, { type: 'think' }>; open: boolean }) {
  return (
    <details
      open={open}
      className="group rounded-md border border-line bg-surface-muted px-3 py-2"
    >
      <summary className="cursor-pointer select-none list-none flex items-center gap-1.5 text-[11.5px] text-warn">
        <Sparkles size={11} />
        思考过程
        <span className="text-ink-faint tnum">{formatClock(block.ts)}</span>
        <span className="ml-auto text-ink-faint text-[10px] group-open:rotate-180 transition-transform">
          ▾
        </span>
      </summary>
      <div className="mt-2 text-[12.5px] leading-relaxed text-ink-muted whitespace-pre-wrap font-mono">
        {block.text}
      </div>
    </details>
  );
}

function ToolBlock({ block, open }: { block: Extract<Block, { type: 'tool' }>; open: boolean }) {
  return (
    <div className="rounded-md border border-line bg-surface-muted overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-line/70">
        <Terminal size={11} className="text-ink-faint shrink-0" />
        <span className="text-[11.5px] font-medium text-ink-soft font-mono truncate">
          {block.name}
        </span>
        {block.error && (
          <span className="inline-flex items-center gap-1 text-[10px] text-danger">
            <AlertTriangle size={9} /> 失败
          </span>
        )}
        <span className="ml-auto text-[10px] text-ink-faint tnum">{formatClock(block.ts)}</span>
      </div>
      {block.input && open && (
        <pre className="px-3 py-2 text-[11.5px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-all border-b border-line/70">
          {block.input}
        </pre>
      )}
      {block.output && (
        <details open={open} className="group">
          <summary className="px-3 py-1.5 text-[11px] text-ink-faint cursor-pointer select-none list-none hover:text-ink-soft">
            输出 {open ? '' : `(${block.output.length.toLocaleString()} 字符，点击展开)`}
          </summary>
          <pre className="px-3 pb-2.5 text-[11.5px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-all">
            {block.output}
          </pre>
        </details>
      )}
    </div>
  );
}

function TraceGroup({ items }: { items: TraceItem[] }) {
  const [expanded, setExpanded] = useState(false);
  const tools = items.filter((i): i is ToolData => i.type === 'tool');
  const thinks = items.filter((i) => i.type === 'think');
  const counts = new Map<string, number>();
  for (const t of tools) counts.set(t.name, (counts.get(t.name) || 0) + 1);
  const names = Array.from(counts.entries())
    .map(([n, c]) => (c > 1 ? `${n} ×${c}` : n))
    .slice(0, 4)
    .join(' · ');
  const failed = tools.filter((t) => t.error).length;

  return (
    <details
      className="group rounded-md border border-line bg-surface-muted"
      onToggle={(e) => setExpanded((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer select-none list-none px-3 py-1.5 flex items-center gap-2 flex-wrap">
        <Terminal size={11} className="text-ink-faint shrink-0" />
        <span className="text-[11.5px] font-medium text-ink-soft">执行过程</span>
        <span className="text-[11px] text-ink-faint tnum">
          {tools.length} 次工具调用
          {thinks.length > 0 && ` · ${thinks.length} 段思考`}
        </span>
        {names && (
          <span className="text-[10.5px] text-ink-faint font-mono truncate max-w-[16rem]">
            {names}
          </span>
        )}
        {failed > 0 && (
          <span className="inline-flex items-center gap-1 text-[10px] text-danger">
            <AlertTriangle size={9} />
            {failed} 失败
          </span>
        )}
        <span className="ml-auto text-[10px] text-ink-faint group-open:rotate-180 transition-transform">
          ▾
        </span>
      </summary>
      <div className="px-2 pb-2 space-y-1.5">
        {expanded &&
          items.map((it, i) =>
            it.type === 'think' ? (
              <ThinkBlock key={i} block={it} open={false} />
            ) : (
              <ToolBlock key={i} block={it} open={false} />
            )
          )}
      </div>
    </details>
  );
}

export function SessionDetailModal() {
  const {
    activeDetailCatalogId,
    activeDetailTurnIndex,
    closeSessionDetail,
    detailViewMode,
    setDetailViewMode,
  } = useStore();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [focusTurn, setFocusTurn] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const open = Boolean(activeDetailCatalogId);

  useEffect(() => {
    if (!activeDetailCatalogId) {
      setDetail(null);
      setError('');
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError('');
    api
      .getSessionDetail(activeDetailCatalogId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        const target = activeDetailTurnIndex && activeDetailTurnIndex > 0 ? activeDetailTurnIndex : 1;
        setFocusTurn(target);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeDetailCatalogId, activeDetailTurnIndex, reloadKey]);

  const turns = useMemo(
    () => (detail ? buildTurns(detail.events, detailViewMode as ViewMode) : []),
    [detail, detailViewMode]
  );

  const jumpTo = (n: number) => {
    if (!turns.length) return;
    const target = Math.min(Math.max(1, n), turns.length);
    setFocusTurn(target);
    const el = document.getElementById(`turn-${target}`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  useEffect(() => {
    if (!detail || !activeDetailTurnIndex) return;
    const timer = setTimeout(() => {
      document
        .getElementById(`turn-${activeDetailTurnIndex}`)
        ?.scrollIntoView({ behavior: 'auto', block: 'start' });
    }, 120);
    return () => clearTimeout(timer);
  }, [detail, activeDetailTurnIndex]);

  const meta = platformMeta(detail?.format);

  const segmented = (
    <div className="flex items-center p-0.5 rounded-md border border-line bg-surface-sunken text-[11.5px]">
      {(['compact', 'summary', 'full'] as ViewMode[]).map((m) => (
        <button
          key={m}
          onClick={() => setDetailViewMode(m)}
          className={`px-2 py-1 rounded transition-colors ${
            detailViewMode === m
              ? 'bg-surface text-ink font-medium shadow-card'
              : 'text-ink-muted hover:text-ink'
          }`}
        >
          {m === 'compact' ? '精简' : m === 'summary' ? '摘要' : '完整'}
        </button>
      ))}
    </div>
  );

  const turnNav = turns.length > 1 && (
    <div className="hidden sm:flex items-center gap-0.5 h-7 px-1.5 rounded-md border border-line bg-surface text-[11.5px] text-ink-muted tnum">
      <button
        onClick={() => jumpTo(focusTurn - 1)}
        disabled={focusTurn <= 1}
        className="p-0.5 rounded hover:text-ink disabled:opacity-30"
        title="上一轮 (Alt+↑)"
      >
        <ChevronUp size={13} />
      </button>
      <span className="px-0.5">
        {focusTurn} / {turns.length}
      </span>
      <button
        onClick={() => jumpTo(focusTurn + 1)}
        disabled={focusTurn >= turns.length}
        className="p-0.5 rounded hover:text-ink disabled:opacity-30"
        title="下一轮 (Alt+↓)"
      >
        <ChevronDown size={13} />
      </button>
    </div>
  );

  // Alt+↑/↓ 轮次跳转
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey) return;
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        jumpTo(focusTurn - 1);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        jumpTo(focusTurn + 1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, focusTurn, turns.length]);

  return (
    <ModalShell
      open={open}
      onClose={closeSessionDetail}
      width="max-w-5xl"
      icon={<MessageSquare size={15} />}
      title={detail ? stripDatePrefix(detail.title) : '会话详情'}
      subtitle={
        detail
          ? [
              meta.label,
              formatDateTime(detail.startedAt),
              `${detail.eventsCount} 条事件`,
              `${turns.length} 轮`,
            ]
              .filter(Boolean)
              .join(' · ')
          : undefined
      }
      actions={
        <>
          {turnNav}
          {segmented}
        </>
      }
    >
      <div ref={scrollRef} className="px-4 md:px-5 py-4 space-y-4">
        {loading && (
          <div className="py-24 flex flex-col items-center gap-2 text-ink-faint text-[12.5px]">
            <Loader2 size={18} className="animate-spin" />
            正在解析会话事件流…
          </div>
        )}

        {!loading && error && (
          <div className="py-20 text-center">
            <AlertTriangle size={20} className="mx-auto text-danger mb-2" />
            <p className="text-[13px] text-ink">加载失败：{error}</p>
            <p className="text-[12px] text-ink-muted mt-1">该会话可能已被删除、文件不可读，或后端正在执行扫描。</p>
            <button
              onClick={() => setReloadKey((k) => k + 1)}
              className="mt-3 h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft hover:bg-surface-sunken transition-colors"
            >
              重新加载
            </button>
          </div>
        )}

        {!loading && !error && turns.length === 0 && (
          <div className="py-20 text-center text-[12.5px] text-ink-muted">
            该会话没有可展示的对话记录
          </div>
        )}

        {!loading &&
          !error &&
          turns.map((turn) => (
            <section
              key={turn.index}
              id={`turn-${turn.index}`}
              className="rounded-lg border border-line bg-surface overflow-hidden scroll-mt-4"
            >
              <div className="flex items-start gap-2 px-3.5 py-2.5 bg-surface-muted border-b border-line">
                <span className="mt-0.5 px-1.5 py-0.5 rounded bg-accent-soft text-accent-ink text-[10.5px] font-medium tnum shrink-0">
                  #{turn.index}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[10.5px] text-ink-faint tnum">
                    <span>用户指令</span>
                    {turn.user?.timestamp && <span>{formatClock(turn.user.timestamp)}</span>}
                    {turn.user && turn.user.hiddenChars > 0 && (
                      <span title="已折叠系统提示等隐藏内容">
                        · 已折叠 {turn.user.hiddenChars} 字符
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-[13.5px] leading-relaxed text-ink whitespace-pre-wrap break-words">
                    {turn.user?.text || '（本轮无用户指令）'}
                  </p>
                </div>
                {turn.user?.text && <CopyButton text={turn.user.text} label="复制用户指令" />}
              </div>

              {turn.blocks.length > 0 && (
                <div className="px-3.5 py-3 space-y-2.5">
                  {turn.blocks.map((block, i) => {
                    if (block.type === 'think')
                      return (
                        <ThinkBlock key={i} block={block} open={detailViewMode === 'full'} />
                      );
                    if (block.type === 'tool')
                      return (
                        <ToolBlock key={i} block={block} open={detailViewMode === 'full'} />
                      );
                    if (block.type === 'trace')
                      return <TraceGroup key={i} items={block.items} />;
                    if (block.type === 'opaque')
                      return (
                        <p
                          key={i}
                          className="text-[11px] text-ink-faint font-mono break-all border-l-2 border-line pl-2"
                        >
                          [原始事件] {block.text.slice(0, 400)}
                        </p>
                      );
                    return (
                      <div key={i} className="group/msg relative">
                        <div
                          className="md-body"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(block.text) }}
                        />
                        <div className="absolute top-0 right-0 opacity-0 group-hover/msg:opacity-100 transition-opacity">
                          <CopyButton text={block.text} label="复制该段回复" />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          ))}
      </div>
    </ModalShell>
  );
}
