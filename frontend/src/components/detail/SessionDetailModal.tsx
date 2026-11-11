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
  Search,
  X,
  Trash2,
  ArrowRightLeft,
  ChevronsUpDown,
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

function blockTexts(b: Block): string[] {
  if (b.type === 'think') return [b.text];
  if (b.type === 'tool') return [b.name, b.input, b.output];
  if (b.type === 'text' || b.type === 'opaque') return [b.text];
  return b.items.flatMap((it) => (it.type === 'think' ? [it.text] : [it.name, it.input, it.output]));
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

/** 长文本分片：默认只渲染前 limit 个字符，避免一次挂上百万字导致界面卡死 */
function ClampedText({
  text,
  limit = 1200,
  className = '',
}: {
  text: string;
  limit?: number;
  className?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const truncated = text.length > limit;
  const shown = expanded || !truncated ? text : `${text.slice(0, limit)}…`;
  return (
    <div>
      <pre className={className}>{shown}</pre>
      {truncated && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-[11px] text-accent-ink hover:underline"
        >
          {expanded ? '收起' : `展开剩余 ${(text.length - limit).toLocaleString()} 字符`}
        </button>
      )}
    </div>
  );
}

function ThinkBlock({ block, open }: { block: Extract<Block, { type: 'think' }>; open: boolean }) {
  const [expanded, setExpanded] = useState(open);
  return (
    <details
      open={open}
      className="group rounded-md border border-line bg-surface-muted px-3 py-2"
      onToggle={(e) => setExpanded((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer select-none list-none flex items-center gap-1.5 text-[11.5px] text-warn">
        <Sparkles size={11} />
        思考过程
        <span className="text-ink-faint tnum">{formatClock(block.ts)}</span>
        <span className="text-ink-faint text-[10px]">
          {block.text.length.toLocaleString()} 字符
        </span>
        <span className="ml-auto text-ink-faint text-[10px] group-open:rotate-180 transition-transform">
          ▾
        </span>
      </summary>
      {expanded && (
        <div className="mt-2">
          <ClampedText
            text={block.text}
            limit={900}
            className="text-[12.5px] leading-relaxed text-ink-muted whitespace-pre-wrap break-words font-mono"
          />
        </div>
      )}
    </details>
  );
}

function ToolBlock({ block, open }: { block: Extract<Block, { type: 'tool' }>; open: boolean }) {
  // 工具输出默认不渲染内容、也不自动展开：一轮里可能上百次调用，全量展开会直接卡住界面
  const [showOutput, setShowOutput] = useState(false);
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
        <div className="px-3 py-2 border-b border-line/70">
          <ClampedText
            text={block.input}
            limit={600}
            className="text-[11.5px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-all"
          />
        </div>
      )}
      {block.output && (
        <details
          open={showOutput}
          className="group"
          onToggle={(e) => setShowOutput((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary className="px-3 py-1.5 text-[11px] text-ink-faint cursor-pointer select-none list-none hover:text-ink-soft">
            输出（{block.output.length.toLocaleString()} 字符{showOutput ? '' : '，点击展开'}）
          </summary>
          {showOutput && (
            <div className="px-3 pb-2.5">
              <ClampedText
                text={block.output}
                limit={2000}
                className="text-[11.5px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-all"
              />
            </div>
          )}
        </details>
      )}
    </div>
  );
}

function TraceGroup({ items, defaultOpen = false }: { items: TraceItem[]; defaultOpen?: boolean }) {
  const [expanded, setExpanded] = useState(defaultOpen);
  useEffect(() => {
    setExpanded(defaultOpen);
  }, [defaultOpen]);
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
      open={defaultOpen}
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
    setActiveMigrateSession,
    bumpDataVersion,
  } = useStore();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [focusTurn, setFocusTurn] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);
  const [chatQuery, setChatQuery] = useState('');
  const [hitIdx, setHitIdx] = useState(0);
  const [expandAll, setExpandAll] = useState<boolean | null>(null);
  const [rawOpen, setRawOpen] = useState<Record<number, boolean>>({});
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

  // 详情内全文检索：按轮次定位，命中的文本由 Markdown 渲染器高亮
  const hits = useMemo(() => {
    const q = chatQuery.trim().toLowerCase();
    if (!q) return [] as number[];
    const list: number[] = [];
    for (const t of turns) {
      const texts = [t.user?.text || '', ...t.blocks.flatMap(blockTexts)];
      for (const txt of texts) {
        const low = (txt || '').toLowerCase();
        let from = 0;
        for (;;) {
          const at = low.indexOf(q, from);
          if (at < 0) break;
          list.push(t.index);
          from = at + q.length;
        }
      }
    }
    return list;
  }, [turns, chatQuery]);

  const gotoHit = (delta: number) => {
    if (!hits.length) return;
    const next = (hitIdx + delta + hits.length) % hits.length;
    setHitIdx(next);
    document
      .getElementById(`turn-${hits[next]}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

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
  // 「全部展开 / 全部收起」优先于三档模式
  const blockOpen = expandAll === null ? detailViewMode === 'full' : expandAll;

  const segmented = (
    <div className="flex items-center p-0.5 rounded-md border border-line bg-surface-sunken text-[11.5px]">
      {(['compact', 'summary', 'full'] as ViewMode[]).map((m) => (
        <button
          key={m}
          onClick={() => setDetailViewMode(m)}
          aria-pressed={detailViewMode === m}
          className={`px-2 py-1 rounded transition-colors ${
            detailViewMode === m
              ? 'bg-surface text-accent-ink font-semibold shadow-card ring-1 ring-accent/30'
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
      footer={
        detail ? (
          <div className="flex items-center justify-between gap-2">
            <button
              onClick={async () => {
                if (
                  !window.confirm(
                    `确定彻底删除该会话？\n\n${detail.title}\n\n会同时清理其派生的子代理会话，不可撤销。`
                  )
                )
                  return;
                try {
                  await api.deleteByCatalogId(activeDetailCatalogId!);
                  toast.success('会话已删除');
                  closeSessionDetail();
                  bumpDataVersion();
                } catch (e: any) {
                  toast.error(`删除失败：${e.message}`);
                }
              }}
              className="h-8 px-3 rounded-md border border-danger/30 bg-danger-soft text-[12.5px] text-danger inline-flex items-center gap-1.5 hover:bg-danger/10 transition-colors"
            >
              <Trash2 size={12} />
              删除此会话
            </button>
            <div className="flex items-center gap-2">
              <button
                onClick={closeSessionDetail}
                className="h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft hover:bg-surface-sunken transition-colors"
              >
                关闭
              </button>
              <button
                onClick={() => {
                  if (!detail || !activeDetailCatalogId) return;
                  closeSessionDetail();
                  setActiveMigrateSession({
                    catalogId: activeDetailCatalogId,
                    sessionId: detail.sessionId,
                    format: detail.format,
                    title: detail.title,
                    startedAt: detail.startedAt,
                    mtime: 0,
                    records: detail.eventsCount,
                    bytes: 0,
                    tokens: 0,
                    chatTokens: 0,
                    filePath: '',
                    exists: true,
                    children: [],
                    childrenCount: 0,
                    lineage: '',
                    lineageSize: 0,
                    lineageHeadTitle: '',
                    lineageHeadId: '',
                    lineageHeadSteps: 0,
                    branchLabel: '',
                    isLineageBranch: false,
                    sideQuestion: '',
                    parentId: '',
                    nestingDepth: 0,
                    agentName: '',
                  });
                }}
                className="h-8 px-3 rounded-md bg-accent text-white text-[12.5px] font-medium inline-flex items-center gap-1.5 hover:bg-accent-ink transition-colors"
              >
                <ArrowRightLeft size={12} />
                迁移此会话
              </button>
            </div>
          </div>
        ) : undefined
      }
    >
      {/* 详情内工具栏：全文搜索 + 展开/收起 */}
      <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur border-b border-line px-4 md:px-5 py-2 flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search
            size={13}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
          />
          <input
            value={chatQuery}
            onChange={(e) => {
              setChatQuery(e.target.value);
              setHitIdx(0);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                gotoHit(e.shiftKey ? -1 : 1);
              }
            }}
            placeholder="在本次对话中搜索（Enter 下一个 / Shift+Enter 上一个）"
            className="w-full h-8 pl-8 pr-8 rounded-md bg-surface-muted border border-line text-[12px] text-ink placeholder:text-ink-faint focus:bg-surface"
          />
          {chatQuery && (
            <button
              onClick={() => {
                setChatQuery('');
                setHitIdx(0);
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-ink-faint hover:text-ink"
              title="清除搜索"
            >
              <X size={12} />
            </button>
          )}
        </div>

        {chatQuery && (
          <div className="flex items-center gap-1 text-[11.5px] text-ink-muted tnum">
            <span>
              {hits.length ? Math.min(hitIdx + 1, hits.length) : 0}/{hits.length}
            </span>
            <button
              onClick={() => gotoHit(-1)}
              disabled={!hits.length}
              className="p-0.5 rounded hover:text-ink disabled:opacity-30"
              title="上一个匹配 (Shift+Enter)"
            >
              <ChevronUp size={13} />
            </button>
            <button
              onClick={() => gotoHit(1)}
              disabled={!hits.length}
              className="p-0.5 rounded hover:text-ink disabled:opacity-30"
              title="下一个匹配 (Enter)"
            >
              <ChevronDown size={13} />
            </button>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={() => setExpandAll(false)}
            className="h-7 px-2 rounded border border-line bg-surface text-[11.5px] text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
            title="全部收起为极简摘要"
          >
            全部收起
          </button>
          <button
            onClick={() => setExpandAll(true)}
            className="h-7 px-2 rounded border border-line bg-surface text-[11.5px] text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
            title="全部展开查看完整详情"
          >
            全部展开
          </button>
        </div>
      </div>

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
                  {turn.user?.text ? (
                    <div
                      className="mt-1 md-body md-body-user"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(turn.user.text, chatQuery) }}
                    />
                  ) : (
                    <p className="mt-1 text-[13.5px] text-ink-soft">（本轮无用户指令）</p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {turn.user?.rawText && turn.user.rawText !== turn.user.text && (
                    <button
                      onClick={() =>
                        setRawOpen((prev) => ({ ...prev, [turn.index]: !prev[turn.index] }))
                      }
                      className={`px-1.5 py-0.5 rounded border text-[10.5px] transition-colors ${
                        rawOpen[turn.index]
                          ? 'border-warn/40 bg-warn-soft text-warn'
                          : 'border-line bg-surface text-ink-faint hover:text-ink'
                      }`}
                      title="切换「净化后的指令」与「含系统提示的原始记录」"
                    >
                      {rawOpen[turn.index] ? '净化后' : '原始记录'}
                    </button>
                  )}
                  {turn.user?.text && <CopyButton text={turn.user.text} label="复制用户指令" />}
                </div>
              </div>

              {turn.user && rawOpen[turn.index] && (
                <pre className="mx-3.5 mb-2 mt-1 max-h-64 overflow-auto rounded-md border border-line bg-surface-muted p-2 text-[11px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-words">
                  {turn.user.rawText}
                </pre>
              )}

              {turn.blocks.length > 0 && (
                <div className="px-3.5 py-3 space-y-2.5">
                  {turn.blocks.map((block, i) => {
                    if (block.type === 'think')
                      return (
                        <ThinkBlock key={i} block={block} open={blockOpen} />
                      );
                    if (block.type === 'tool')
                      return (
                        <ToolBlock key={i} block={block} open={blockOpen} />
                      );
                    if (block.type === 'trace')
                      return <TraceGroup key={i} items={block.items} defaultOpen={blockOpen} />;
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
                          onClick={(e) => {
                            const pre = (e.target as HTMLElement).closest('pre');
                            if (!pre) return;
                            const code = pre.querySelector('code')?.textContent || pre.textContent || '';
                            navigator.clipboard
                              .writeText(code)
                              .then(() => toast.success('代码块已复制'))
                              .catch(() => toast.error('复制失败'));
                          }}
                          title="点击代码块可复制"
                          dangerouslySetInnerHTML={{ __html: renderMarkdown(block.text, chatQuery) }}
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
