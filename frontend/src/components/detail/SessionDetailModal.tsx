'use client';

import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronUp,
  ChevronDown,
  Copy,
  Check,
  MessageSquare,
  AlertTriangle,
  Loader2,
  Search,
  X,
  Trash2,
  ArrowRightLeft,
  Sparkles,
  Terminal,
  CornerDownRight,
  Bot,
  Info,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SessionDetail, SessionEvent, SessionEventDetail, SessionTurnSpan } from '../../types/session';
import { toast } from 'sonner';
import { ModalShell } from '../ui/Overlay';
import { formatClock, formatDateTime, stripDatePrefix } from '../../lib/format';
import { platformMeta } from '../../lib/platform';
import { renderMarkdown } from '../../lib/markdown';
import { summarizeTools, toolDetail, toolMeta } from '../../lib/toolMeta';

/* ------------------------------------------------------------------ */
/* 数据整理：指令 → 思考 → 行动 → 回复（对齐旧版 bubble 结构）           */
/* ------------------------------------------------------------------ */

interface ThinkItem {
  text: string;
  ts: string;
  /** 绝对事件下标（回源用） */
  eventIndex: number;
  /** 服务端已藏掉的字符数 */
  hiddenChars: number;
}

interface ToolItem {
  name: string;
  input: string;
  output: string;
  error: boolean;
  ts: string;
  callEventIndex: number;
  callHiddenChars: number;
  resultEventIndex: number;
  resultHiddenChars: number;
}

interface ReplyItem {
  text: string;
  ts: string;
  /** 绝对事件下标（回源用） */
  eventIndex: number;
  /** 服务端已藏掉的字符数 */
  hiddenChars: number;
}

interface Turn {
  index: number;
  user?: SessionEvent;
  thinks: ThinkItem[];
  tools: ToolItem[];
  replies: ReplyItem[];
}

function firstLine(s: string, max = 90): string {
  const line = (s || '').split('\n').find((l) => l.trim()) || '';
  const t = line.trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/**
 * 分轮：`kind === 'message' && role === 'user'` 为轮边界。
 * ⚠️ 函数体与改造前逐字一致（后端 services/turns.py 用同一口径计算轮边界），
 * 分片只改变"喂进来的 events"，不改变这段逻辑。
 */
function buildTurns(events: SessionEvent[]): Turn[] {
  const turns: Turn[] = [];
  let current: Turn | null = null;

  const ensure = (): Turn => {
    if (!current) {
      current = { index: 1, thinks: [], tools: [], replies: [] };
      turns.push(current);
    }
    return current;
  };

  for (const evt of events) {
    if (evt.kind === 'message' && evt.role === 'user') {
      current = { index: turns.length + 1, user: evt, thinks: [], tools: [], replies: [] };
      turns.push(current);
      continue;
    }
    const turn = ensure();

    if (evt.kind === 'thinking') {
      if (evt.text.trim()) {
        turn.thinks.push({
          text: evt.text,
          ts: evt.timestamp,
          eventIndex: evt.eventIndex,
          hiddenChars: evt.truncatedChars,
        });
      }
      continue;
    }

    if (evt.kind === 'tool_call') {
      const detail = toolDetail(evt.payload);
      turn.tools.push({
        name: evt.toolName || 'tool',
        input: detail ? firstLine(detail, 400) : '',
        output: '',
        error: false,
        ts: evt.timestamp,
        callEventIndex: evt.eventIndex,
        callHiddenChars: evt.truncatedChars,
        resultEventIndex: -1,
        resultHiddenChars: 0,
      });
      continue;
    }

    if (evt.kind === 'tool_result') {
      const last = [...turn.tools].reverse().find((t) => !t.output);
      const isError = Boolean((evt.payload as any)?.is_error);
      const output = evt.text || '';
      if (last) {
        last.output = output;
        last.error = isError;
        last.resultEventIndex = evt.eventIndex;
        last.resultHiddenChars = evt.truncatedChars;
      } else if (output) {
        turn.tools.push({
          name: evt.toolName || 'tool',
          input: '',
          output,
          error: isError,
          ts: evt.timestamp,
          callEventIndex: -1,
          callHiddenChars: 0,
          resultEventIndex: evt.eventIndex,
          resultHiddenChars: evt.truncatedChars,
        });
      }
      continue;
    }

    // assistant message
    if (evt.text.trim()) {
      turn.replies.push({
        text: evt.text,
        ts: evt.timestamp,
        eventIndex: evt.eventIndex,
        hiddenChars: evt.truncatedChars,
      });
    }
  }

  return turns;
}

/**
 * 同一轮里的过程性 assistant message（例如"我先定位…"、"验证发现…"）
 * 不是最终回复；把除最后一条以外的 assistant message 归入“思考过程”。
 * 只在轮次合并完成后执行，避免一条轮次跨分片时把中途消息误判成回复。
 */
function demoteAssistantProgress(turns: Turn[]): Turn[] {
  for (const turn of turns) {
    if (turn.replies.length <= 1) continue;
    const final = turn.replies[turn.replies.length - 1];
    const interim = turn.replies.slice(0, -1);
    for (const reply of interim) {
      if (!reply.text.trim()) continue;
      turn.thinks.push({
        text: reply.text,
        ts: reply.ts,
        eventIndex: reply.eventIndex,
        hiddenChars: reply.hiddenChars,
      });
    }
    turn.replies = [final];
  }
  return turns;
}

/* ------------------------------------------------------------------ */
/* 分片：详情按轮切片加载，已加载分片按绝对轮号拼回一条时间线            */
/* ------------------------------------------------------------------ */

/** 首屏轮数；与后端 turn_limit=8 的字节预算对齐（最大会话首屏 ≈ 340 KB） */
const TURNS_PER_SHARD = 8;

interface Shard {
  /** 请求时使用的 turn_offset */
  offset: number;
  /** 本分片实际产出多少轮（以 buildTurns 结果为准） */
  turnCount: number;
  events: SessionEvent[];
  spans: SessionTurnSpan[];
  /** 与 events 逐项平行的绝对轮号（服务端 turn_index），轮号映射的权威来源 */
  turnIndexes: number[];
  hasMoreTurns: boolean;
  turnsTotal: number;
  /** 服务端给的下一页起始轮号（0 表示没有下一页） */
  nextTurnOffset: number;
}

/** 第 n 轮（1 基）落在哪个 turn_offset 上。
 *
 * 实测后端（`/api/session/detail`）的 `turn_offset` 就是"起始轮号"且为 1 基：
 * 请求 turn_offset=0 会被归一化成 1。因此直接把轮号当 offset 用，
 * 既不会重复取轮，也不会因字节预算裁剪而跳过目标轮。
 */
function shardOffsetFor(turnNumber: number): number {
  return Math.max(1, Math.floor(turnNumber));
}

function toShard(offset: number, d: SessionDetail): Shard {
  // 用 event_index[] 给每条事件标注绝对下标：slim 丢弃 opaque 后 raw 下标不连续，
  // 回源 /api/session/event 必须用这个绝对值，不能自己按顺序数。
  const events: SessionEvent[] = d.events.map((e, i) => ({
    ...e,
    eventIndex: Number.isFinite(d.eventIndexes[i]) ? d.eventIndexes[i] : -1,
  }));
  return {
    offset,
    turnCount: buildTurns(events).length,
    events,
    spans: d.turns,
    turnIndexes: d.turnIndexes,
    hasMoreTurns: d.hasMoreTurns,
    turnsTotal: d.turnsTotal,
    nextTurnOffset: d.nextTurnOffset,
  };
}

/**
 * 分片内 `turns[i].index` 的编号口径。
 *
 * 实测后端返回的 `turns[].index` 已经是绝对轮号（1 基，与 FTS 的 turn_index 同源），
 * 直接当作 UI 轮号即可。只有分片里出现 `index === 0`（某些实现的 0 基口径）时才整体 +1，
 * 避免出现"用户指令 #0"。
 */
function shardIndexBase(shard: Shard): number {
  return shard.spans.some((s) => Number(s.index) === 0) ? 1 : 0;
}

/**
 * 分片内每个本地轮的起始事件下标（与 buildTurns 的分轮口径一致：
 * 第 0 个事件起一轮，之后每个 `message + user` 事件起一轮）。
 */
function shardTurnStarts(events: SessionEvent[]): number[] {
  const starts: number[] = [];
  events.forEach((e, i) => {
    if (i === 0 || (e.kind === 'message' && e.role === 'user')) starts.push(i);
  });
  return starts;
}

/**
 * 本地第 localIndex 轮对应的绝对轮号（1 基）。
 *
 * **权威来源是 `turn_index`**：它与裁剪后的 `events` 逐项平行，取该轮起始事件上的值即可，
 * 天然处理会话开头的"前缀区"（服务端把首条用户指令之前的事件并入第 1 轮）。
 *
 * 两个已经踩过的坑：
 * 1. 不能用 `offset + localIndex` 推 —— 1 基口径会整体多一轮，出现 `1,2,3,4,5,7` 跳号；
 * 2. 不能用 `spans[k].start/end` 对齐 —— 那是**原始全量事件**的下标空间
 *    （实测 span1 `end=1558`，而客户端只收到 396 条事件），与裁剪后的数组不可互换。
 *
 * `turn_index` 缺失时，退化为"按 span 数对齐 + 前缀区检测"。
 */
function absoluteTurnNumber(
  shard: Shard,
  localIndex: number,
  starts: number[],
  localCount: number
): number {
  const start = starts[localIndex - 1];
  if (start !== undefined && shard.turnIndexes.length > start) {
    const idx = Number(shard.turnIndexes[start]);
    if (Number.isFinite(idx) && idx > 0) return idx;
  }
  // 后端未支持分片（无 turns[]）：单分片全量，本地序号就是轮号
  if (!shard.spans.length) return localIndex;
  const spanCount = shard.spans.length;
  const hasPrefixTurn = localCount > spanCount;
  const slot = hasPrefixTurn ? localIndex - 2 : localIndex - 1;
  const clamped = Math.min(Math.max(0, slot), spanCount - 1);
  return Number(shard.spans[clamped].index) + shardIndexBase(shard);
}

function buildShardTurns(shards: Shard[]): Turn[] {
  const byIndex = new Map<number, Turn>();
  for (const shard of [...shards].sort((a, b) => a.offset - b.offset)) {
    const local = buildTurns(shard.events);
    const starts = shardTurnStarts(shard.events);
    local.forEach((turn, i) => {
      const abs = absoluteTurnNumber(shard, i + 1, starts, local.length);
      const prev = byIndex.get(abs);
      if (!prev) {
        byIndex.set(abs, { ...turn, index: abs });
        return;
      }
      // 同一绝对轮被两个本地轮覆盖（前缀区 + 该轮真正的用户指令）：按出现顺序合并。
      // 不能"先到先得"地丢弃后一个，否则会把用户指令和整轮正文一起丢掉。
      byIndex.set(abs, {
        index: abs,
        user: turn.user ?? prev.user,
        thinks: [...prev.thinks, ...turn.thinks],
        tools: [...prev.tools, ...turn.tools],
        replies: [...prev.replies, ...turn.replies],
      });
    });
  }
  return demoteAssistantProgress([...byIndex.values()].sort((a, b) => a.index - b.index));
}

/* ------------------------------------------------------------------ */
/* 小组件                                                              */
/* ------------------------------------------------------------------ */

function CopyButton({
  text,
  label,
  inverse = false,
}: {
  text: string;
  label: string;
  inverse?: boolean;
}) {
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
      className={`p-1 rounded transition-colors ${
        inverse
          ? 'text-white/70 hover:text-white hover:bg-white/15'
          : 'text-ink-faint hover:text-ink hover:bg-surface-sunken'
      }`}
      title={label}
      aria-label={label}
    >
      {done ? (
        <Check size={12} className={inverse ? 'text-emerald-300' : 'text-ok'} />
      ) : (
        <Copy size={12} />
      )}
    </button>
  );
}

const MemoMarkdown = memo(function MemoMarkdown({
  text,
  highlight,
  className = '',
  onClick,
  title,
}: {
  text: string;
  highlight: string;
  className?: string;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  title?: string;
}) {
  const html = useMemo(() => ({ __html: renderMarkdown(text, highlight) }), [text, highlight]);
  return <div className={className} onClick={onClick} title={title} dangerouslySetInnerHTML={html} />;
});

/** 长文本分片，避免一次渲染上百万字符。
 *
 * `hiddenChars > 0` 表示服务端 slim 裁剪还藏着这么多字符：此时"展开剩余 N 字符"
 * 的计数把隐藏部分算进去，点击先经 `onFetchOriginal` 回源 `/api/session/event` 取全文，
 * 再按原样展开。没有隐藏字符时行为与改造前完全一致（纯前端切换，不发请求）。
 */
function ClampedText({
  text,
  limit = 1200,
  className = '',
  plain = false,
  hiddenChars = 0,
  onFetchOriginal,
}: {
  text: string;
  limit?: number;
  className?: string;
  plain?: boolean;
  hiddenChars?: number;
  onFetchOriginal?: () => Promise<string>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [original, setOriginal] = useState<string | null>(null);

  const full = original ?? text;
  const hidden = original ? 0 : Math.max(0, hiddenChars);
  const remaining = Math.max(0, full.length - limit) + hidden;
  const truncated = remaining > 0;
  const shown = expanded || !truncated ? full : `${full.slice(0, limit)}…`;

  const toggle = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    // 还有服务端藏起来的内容 → 先回源取全文（只看文本长度已够时走下面的就地展开）
    if (onFetchOriginal && !original && hidden > 0) {
      setBusy(true);
      try {
        const fetched = await onFetchOriginal();
        setOriginal(fetched);
        setExpanded(true);
      } catch (e: any) {
        toast.error(`展开原始内容失败：${e?.message || '未知原因'}`);
      } finally {
        setBusy(false);
      }
      return;
    }
    setExpanded(true);
  };

  return (
    <div>
      {plain ? <pre className={className}>{shown}</pre> : <div className={className}>{shown}</div>}
      {truncated && (
        <button onClick={toggle} className="mt-1 text-[11px] text-accent-ink hover:underline">
          {busy ? '加载中…' : expanded ? '收起' : `展开剩余 ${remaining.toLocaleString()} 字符`}
        </button>
      )}
    </div>
  );
}

/** 单事件回源回调（index 为绝对事件下标） */
type FetchEvent = (
  index: number,
  field: 'text' | 'payload' | 'both'
) => Promise<SessionEventDetail>;

function ToolRow({ tool, fetchEvent }: { tool: ToolItem; fetchEvent?: FetchEvent }) {
  const [open, setOpen] = useState(false);
  const meta = toolMeta(tool.name);
  const canFetch = Boolean(fetchEvent);
  return (
    <div className="rounded-md border border-act/25 bg-surface/70 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 hover:bg-act/5 transition-colors"
        title="展开查看工具参数与输出"
      >
        <span className="text-[11px] shrink-0">{meta.icon}</span>
        <span className="text-[11.5px] font-medium text-act shrink-0">{meta.label}</span>
        {tool.input && (
          <span className="text-[11px] text-ink-muted font-mono truncate">{tool.input}</span>
        )}
        {tool.error && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-danger shrink-0">
            <AlertTriangle size={9} />
            失败
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-[10px] text-ink-faint tnum shrink-0">
          {formatClock(tool.ts)}
          <ChevronDown size={10} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>

      {open && (
        <div className="px-2.5 pb-2 space-y-1.5 border-t border-act/20">
          <div className="pt-1.5 text-[10px] text-ink-faint">
            {tool.name && tool.name !== 'tool' ? (
              <>
                工具标识 <span className="font-mono text-ink-muted">{tool.name}</span>
              </>
            ) : (
              '工具标识未记录'
            )}
          </div>
          {tool.input && (
            <div className="pt-1.5">
              <div className="text-[10px] text-ink-faint mb-0.5">参数</div>
              <ClampedText
                plain
                text={tool.input}
                limit={600}
                hiddenChars={tool.callHiddenChars}
                onFetchOriginal={
                  canFetch && tool.callEventIndex >= 0
                    ? async () => {
                        const d = await fetchEvent!(tool.callEventIndex, 'payload');
                        return d.payload ? JSON.stringify(d.payload, null, 2) : d.text;
                      }
                    : undefined
                }
                className="text-[11.5px] leading-relaxed text-ink-soft font-mono whitespace-pre-wrap break-all"
              />
            </div>
          )}
          {tool.output && (
            <div>
              <div className="text-[10px] text-ink-faint mb-0.5">
                输出 ·{' '}
                {(tool.output.length + tool.resultHiddenChars).toLocaleString()} 字符
              </div>
              <ClampedText
                plain
                text={tool.output}
                limit={2000}
                hiddenChars={tool.resultHiddenChars}
                onFetchOriginal={
                  canFetch && tool.resultEventIndex >= 0
                    ? () => fetchEvent!(tool.resultEventIndex, 'text').then((d) => d.text)
                    : undefined
                }
                className="text-[11.5px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-all"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** 思考 / 行动 轨道：默认折叠，展开后按需渲染子项 */
function Track({
  tone,
  icon,
  title,
  summary,
  count,
  metaText,
  open,
  children,
}: {
  tone: 'think' | 'act';
  icon: React.ReactNode;
  title: string;
  summary?: string;
  count: number;
  metaText?: string;
  open: boolean;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(open);
  useEffect(() => setExpanded(open), [open]);

  const cls = tone === 'think' ? 'block-think' : 'block-act';
  const tag = tone === 'think' ? 'tag-think' : 'tag-act';

  return (
    <div className={`rounded-lg border ${cls}`}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-3 py-1.5 flex items-center gap-2"
      >
        <span
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10.5px] ${tag}`}
        >
          {icon}
          {title}
        </span>
        {summary && <span className="text-[11px] text-ink-muted truncate font-mono">{summary}</span>}
        <span className="ml-auto flex items-center gap-1 text-[10.5px] text-ink-faint tnum shrink-0">
          {metaText && <span>{metaText}</span>}
          <ChevronDown size={11} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </span>
      </button>
      {expanded && <div className="px-2.5 pb-2.5 space-y-1.5">{children}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 主组件                                                              */
/* ------------------------------------------------------------------ */

export function SessionDetailModal() {
  const {
    activeDetailCatalogId,
    activeDetailTurnIndex,
    openSessionDetail,
    closeSessionDetail,
    setActiveMigrateSession,
    bumpDataVersion,
  } = useStore();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [shards, setShards] = useState<Shard[]>([]);
  const [serverTurnsTotal, setServerTurnsTotal] = useState(0);
  /** 服务端给的下一次起始轮号（字节预算裁轮后以此为权威，避免漏轮） */
  const [serverNextOffset, setServerNextOffset] = useState(0);
  const [stalled, setStalled] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [focusTurn, setFocusTurn] = useState(1);
  const [pendingFocus, setPendingFocus] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [chatQuery, setChatQuery] = useState('');
  /** null = 服务端检索不可用/未生效，退回前端扫描 */
  const [serverHits, setServerHits] = useState<number[] | null>(null);
  const [hitIdx, setHitIdx] = useState(0);
  const [expandAll, setExpandAll] = useState(false);
  const [rawOpen, setRawOpen] = useState<Record<number, boolean>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const shardsRef = useRef<Shard[]>([]);
  const inflightRef = useRef<Set<string>>(new Set());
  /** 豆包云端详情刷新次数：避免后台同步超过 24s 时无限重试 */
  const refreshRetryRef = useRef(0);

  const open = Boolean(activeDetailCatalogId);
  const cid = activeDetailCatalogId;

  const appendShard = useCallback((shard: Shard, mode: 'replace' | 'append') => {
    setShards((prev) => {
      const base = mode === 'replace' ? [] : prev;
      const next = [...base.filter((s) => s.offset !== shard.offset), shard].sort(
        (a, b) => a.offset - b.offset
      );
      shardsRef.current = next;
      return next;
    });
  }, []);

  /* 首屏：只取覆盖目标轮的那一个分片（默认第 1 轮的 0~7 轮） */
  useEffect(() => {
    if (!cid) {
      setDetail(null);
      setShards([]);
      shardsRef.current = [];
      setServerTurnsTotal(0);
      setServerNextOffset(0);
      setStalled(false);
      setError('');
      setServerHits(null);
      inflightRef.current.clear();
      return;
    }
    const target = activeDetailTurnIndex && activeDetailTurnIndex > 0 ? activeDetailTurnIndex : 1;
    const offset = shardOffsetFor(target);
    let cancelled = false;

    setLoading(true);
    setError('');
    setStalled(false);
    setServerTurnsTotal(0);
    setDetail(null);
    setShards([]);
    shardsRef.current = [];
    inflightRef.current.clear();
    setFocusTurn(target);
    setPendingFocus(target);

    api
      .getSessionDetail(cid, { turnOffset: offset, turnLimit: TURNS_PER_SHARD })
      .then((d) => {
        if (cancelled) return;
        const shard = toShard(offset, d);
        if (shard.turnCount === 0) setStalled(true);
        setDetail(d);
        if (d.turnsTotal > 0) setServerTurnsTotal(d.turnsTotal);
        if (d.nextTurnOffset > 0) setServerNextOffset(d.nextTurnOffset);
        appendShard(shard, 'replace');
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message || '加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [cid, activeDetailTurnIndex, reloadKey, appendShard]);

  /* 切换会话时重置云端刷新计数 */
  useEffect(() => {
    refreshRetryRef.current = 0;
  }, [cid]);

  /* 豆包云端详情：后台正在拉取最新正文时，每 3s 自动重取一次（最多 8 次）。 */
  useEffect(() => {
    if (!detail) return;
    if (!detail.refreshPending) {
      refreshRetryRef.current = 0;
      return;
    }
    if (!cid || refreshRetryRef.current >= 8) return;
    const timer = setTimeout(() => {
      refreshRetryRef.current += 1;
      setReloadKey((k) => k + 1);
    }, 3000);
    return () => clearTimeout(timer);
  }, [cid, detail?.refreshPending]);

  const turns = useMemo(() => buildShardTurns(shards), [shards]);

  const totalTurns = Math.max(serverTurnsTotal, turns.length);

  /**
   * 追加下一页的 turn_offset。
   *
   * 权威来源是服务端的 `next_turn_offset`（字节预算会整轮丢弃尾部，按
   * `offset += turnLimit` 推进会永久漏轮）。服务端未提供时，回落到
   * "实际到达的最后一轮 + 1"，再兜底 `offset + turnCount`。
   * 两者取 max 是为了防止"先跳到后面的分片、再回补前面的分片"时把起点拉回去。
   */
  const nextTurnOffset = useMemo(() => {
    let max = serverNextOffset;
    for (const s of shards) {
      const lastSpan = s.spans.length ? Number(s.spans[s.spans.length - 1].index) : NaN;
      const lastTurn = Number.isFinite(lastSpan)
        ? lastSpan + shardIndexBase(s)
        : s.offset + s.turnCount;
      max = Math.max(max, lastTurn + 1);
    }
    return max;
  }, [shards, serverNextOffset]);

  const hasMoreTurns = Boolean(
    !stalled && serverTurnsTotal > 0 && nextTurnOffset > 0 && nextTurnOffset <= totalTurns
  );

  const loadedTurnSet = useMemo(() => new Set(turns.map((t) => t.index)), [turns]);

  /** 单事件回源：拿被 slim 裁掉的完整内容（index 为绝对事件下标） */
  const fetchEvent = useCallback<FetchEvent>(
    async (index, field) => {
      if (!cid || !Number.isFinite(index) || index < 0) {
        throw new Error('该事件没有可回源的下标');
      }
      return api.getSessionEvent(cid, index, field);
    },
    [cid]
  );

  /** 按需加载某个分片；已加载或正在请求时直接返回 */
  const loadShard = useCallback(
    async (offset: number): Promise<void> => {
      if (!cid) return;
      const key = `${cid}#${offset}`;
      if (shardsRef.current.some((s) => s.offset === offset)) return;
      if (inflightRef.current.has(key)) return;
      inflightRef.current.add(key);
      setLoadingMore(true);
      try {
        const d = await api.getSessionDetail(cid, {
          turnOffset: offset,
          turnLimit: TURNS_PER_SHARD,
        });
        const shard = toShard(offset, d);
        // 后端返回空分片说明轮号已越过末尾，停止继续请求，避免空转
        if (shard.turnCount === 0) setStalled(true);
        if (d.turnsTotal > 0) setServerTurnsTotal(d.turnsTotal);
        if (d.nextTurnOffset > 0) setServerNextOffset(d.nextTurnOffset);
        setDetail((prev) => prev ?? d);
        appendShard(shard, 'append');
      } catch {
        // 追加失败不动已渲染内容，按钮保留可重试
      } finally {
        inflightRef.current.delete(key);
        setLoadingMore(false);
      }
    },
    [cid, appendShard]
  );

  const loadMoreTurns = useCallback(() => {
    if (!hasMoreTurns || loadingMore) return;
    void loadShard(nextTurnOffset);
  }, [hasMoreTurns, loadingMore, loadShard, nextTurnOffset]);

  /* 底部"加载更多轮次"进入视口时自动触发一次 */
  useEffect(() => {
    const el = moreRef.current;
    if (!el || !hasMoreTurns) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMoreTurns();
      },
      { rootMargin: '200px 0px' }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMoreTurns, loadMoreTurns]);

  /* 详情内检索：≥2 字且停顿 300ms 后走服务端 FTS 拿命中轮号 */
  useEffect(() => {
    const q = chatQuery.trim();
    setServerHits(null);
    if (!cid || q.length < 2) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .searchInSession(cid, q, { strict: true })
        .then((matches) => {
          if (cancelled) return;
          setServerHits(matches.map((m) => m.turnIndex));
        })
        .catch(() => {
          // 接口不可用（404 / 超时 / 未支持 catalog_id 过滤）→ 退回前端扫描
          if (!cancelled) setServerHits(null);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [chatQuery, cid, reloadKey]);

  /**
   * 前端扫描（兜底）：只看已加载轮次，作为服务端检索不可用时的降级路径。
   * 与改造前同一套扫描逻辑，仅按轮去重（服务端命中的粒度也是"轮"）。
   */
  const localHits = useMemo(() => {
    const q = chatQuery.trim().toLowerCase();
    if (!q) return [] as number[];
    const found = new Set<number>();
    const scan = (txt: string, turnIndex: number) => {
      if (txt && txt.toLowerCase().includes(q)) found.add(turnIndex);
    };
    for (const t of turns) {
      if (t.user?.text) scan(t.user.text, t.index);
      t.thinks.forEach((th) => scan(th.text, t.index));
      t.tools.forEach((tl) => {
        scan(tl.input, t.index);
        scan(tl.output, t.index);
      });
      t.replies.forEach((r) => scan(r.text, t.index));
    }
    return [...found].sort((a, b) => a - b);
  }, [turns, chatQuery]);

  /**
   * 命中轮：服务端可用时**以服务端为准** —— 它覆盖尚未加载的轮次，计数就是真实命中数；
   * 服务端不可用（404 / 超时 / 响应无 matches 字段）才退回前端扫描已加载轮次。
   */
  const hits = useMemo(() => {
    if (!chatQuery.trim()) return [] as number[];
    if (serverHits) {
      return [...new Set(serverHits.filter((n) => n > 0))].sort((a, b) => a - b);
    }
    return localHits;
  }, [localHits, serverHits, chatQuery]);

  /** 目标轮未加载时先补该轮所在分片，加载完由 pendingFocus 负责滚动 */
  const focusOn = useCallback(
    (n: number) => {
      const upper = Math.max(totalTurns, 1);
      const target = Math.min(Math.max(1, Math.round(n)), upper);
      setFocusTurn(target);
      const el = document.getElementById(`turn-${target}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setPendingFocus(null);
        return;
      }
      setPendingFocus(target);
      void loadShard(shardOffsetFor(target));
    },
    [totalTurns, loadShard]
  );

  const hitMarksRef = useRef<HTMLElement[]>([]);
  const [hitCount, setHitCount] = useState(0);

  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !chatQuery.trim()) {
      hitMarksRef.current = [];
      setHitCount(0);
      return;
    }
    const marks = Array.from(root.querySelectorAll<HTMLElement>('mark.chat-hit'));
    hitMarksRef.current = marks;
    setHitCount(marks.length);
    const activeIdx = marks.length ? Math.min(hitIdx, marks.length - 1) : 0;
    marks.forEach((m, i) => {
      m.classList.toggle('chat-hit-active', i === activeIdx);
    });
  }, [chatQuery, turns, expandAll, loading, rawOpen, hitIdx]);

  const gotoHit = (delta: number) => {
    const marks = hitMarksRef.current;
    if (marks.length > 0) {
      const next = (hitIdx + delta + marks.length) % marks.length;
      setHitIdx(next);
      const targetEl = marks[next];
      targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
      const turnSec = targetEl.closest<HTMLElement>('section[id^="turn-"]');
      if (turnSec) {
        const turnNum = Number(turnSec.id.replace('turn-', ''));
        if (Number.isFinite(turnNum) && turnNum > 0) setFocusTurn(turnNum);
      }
      return;
    }
    if (!hits.length) return;
    focusOn(hits[0]);
  };

  const jumpTo = (n: number) => {
    if (!turns.length && !serverTurnsTotal) return;
    focusOn(n);
  };

  /* 目标轮进入 DOM 后再滚动（分片是异步到的，早一帧会拿不到元素） */
  useEffect(() => {
    if (pendingFocus == null) return;
    if (!loadedTurnSet.has(pendingFocus)) return;
    const timer = setTimeout(() => {
      const el = document.getElementById(`turn-${pendingFocus}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        setPendingFocus(null);
      }
    }, 60);
    return () => clearTimeout(timer);
  }, [pendingFocus, loadedTurnSet, turns]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey) return;
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        focusOn(focusTurn - 1);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        focusOn(focusTurn + 1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, focusTurn, focusOn]);

  const meta = platformMeta(detail?.format);

  const turnNav = totalTurns > 1 && (
    <div className="hidden sm:flex items-center gap-0.5 h-7 px-1.5 rounded-md border border-line bg-surface text-[11.5px] text-ink-muted tnum">
      <button
        onClick={() => jumpTo(focusTurn - 1)}
        disabled={focusTurn <= 1}
        className="p-0.5 rounded hover:text-ink disabled:opacity-30"
        title="上一条用户指令 (Alt+↑)"
      >
        <ChevronUp size={13} />
      </button>
      <span className="px-0.5">
        {focusTurn} / {totalTurns}
      </span>
      <button
        onClick={() => jumpTo(focusTurn + 1)}
        disabled={focusTurn >= totalTurns}
        className="p-0.5 rounded hover:text-ink disabled:opacity-30"
        title="下一条用户指令 (Alt+↓)"
      >
        <ChevronDown size={13} />
      </button>
    </div>
  );

  return (
    <ModalShell
      open={open}
      onClose={closeSessionDetail}
      width="max-w-5xl"
      icon={<MessageSquare size={15} />}
      title={detail ? stripDatePrefix(detail.title) : '会话详情'}
      subtitle={
        detail ? (
          <div className="space-y-1 mt-0.5">
            <div>
              {[
                meta.label,
                formatDateTime(detail.startedAt),
                `${detail.eventsCount} 条事件`,
                `${totalTurns} 轮`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </div>
            {detail.isChild && (detail.parentCatalogId || detail.parentId) && (
              <div className="flex items-center gap-1.5 text-[11.5px] text-purple-400">
                <CornerDownRight size={12} className="shrink-0 text-purple-400" />
                <span className="font-semibold shrink-0">归属于父会话：</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    const pCid =
                      detail.parentCatalogId ||
                      (detail.parentId ? `ag_${detail.parentId.slice(0, 12)}` : '');
                    if (pCid) openSessionDetail(pCid);
                  }}
                  className="text-purple-300 hover:text-white underline decoration-dotted underline-offset-2 hover:decoration-solid font-medium truncate max-w-sm text-left transition-colors"
                  title={`点击切回主会话：${detail.parentTitle || detail.parentId}`}
                >
                  「{detail.parentTitle || detail.parentId}」
                </button>
                {detail.agentName && (
                  <span className="px-1.5 py-0.2 rounded bg-purple-500/20 border border-purple-500/35 text-purple-200 text-[10px] font-mono shrink-0">
                    {detail.agentName}
                  </span>
                )}
              </div>
            )}
          </div>
        ) : undefined
      }
      actions={turnNav}
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
                    inputTokens: 0,
                    outputTokens: 0,
                    thoughtsTokens: 0,
                    contentTokens: 0,
                    cacheReadTokens: 0,
                    cacheMissTokens: 0,
                    freshTokens: 0,
                    usageSource: 'estimated',
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
                    isChild: Boolean(detail.isChild),
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
      {/* 工具栏：全文检索 + 全部展开/收起 */}
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
            placeholder="在本次对话中搜索 (Enter 下一个 / Shift+Enter 上一个)"
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
              {hitCount ? `${Math.min(hitIdx + 1, hitCount)}/${hitCount}` : hits.length ? `0/${hits.length} 轮` : '0/0'}
            </span>
            <button
              onClick={() => gotoHit(-1)}
              disabled={!hitCount && !hits.length}
              className="p-0.5 rounded hover:text-ink disabled:opacity-30"
              title="上一个匹配 (Shift+Enter)"
            >
              <ChevronUp size={13} />
            </button>
            <button
              onClick={() => gotoHit(1)}
              disabled={!hitCount && !hits.length}
              className="p-0.5 rounded hover:text-ink disabled:opacity-30"
              title="下一个匹配 (Enter)"
            >
              <ChevronDown size={13} />
            </button>
          </div>
        )}

        <button
          onClick={() => setExpandAll((v) => !v)}
          className="ml-auto h-7 px-2.5 rounded border border-line bg-surface text-[11.5px] text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
          title={expandAll ? '把思考与行动折叠起来' : '展开全部思考与行动'}
        >
          {expandAll ? '全部收起' : '全部展开'}
        </button>
      </div>

      <div ref={scrollRef} className="px-4 md:px-5 py-4 space-y-3">
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
            <p className="text-[12px] text-ink-muted mt-1">
              该会话可能已被删除、文件不可读，或后端正在执行扫描。
            </p>
            <button
              onClick={() => setReloadKey((k) => k + 1)}
              className="mt-3 h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft hover:bg-surface-sunken transition-colors"
            >
              重新加载
            </button>
          </div>
        )}

        {!loading && !error && detail?.notice && (
          <div className="flex items-start gap-2 rounded-lg border border-line bg-surface-sunken px-3.5 py-2.5 text-[12px] leading-relaxed text-ink-soft">
            <Info size={14} className="mt-0.5 shrink-0 text-ink-muted" />
            <span>{detail.notice}</span>
          </div>
        )}

        {!loading && !error && detail?.refreshPending && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/5 px-3.5 py-2.5 text-[12px] leading-relaxed text-amber-200">
            <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" />
            <span>云端正文正在同步，完成后会自动刷新…</span>
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
            <section key={turn.index} id={`turn-${turn.index}`} className="space-y-2 scroll-mt-14">
              {/* 指令 */}
              {turn.user && (
                <div className="block-user-solid rounded-lg px-3.5 py-2.5">
                  <div className="flex items-center gap-2 text-[10.5px] tnum mb-1.5">
                    <span className="px-1.5 py-0.5 rounded bg-white/20 text-white font-medium">
                      用户指令 #{turn.index}
                    </span>
                    <span className="text-white/70">{formatClock(turn.user.timestamp)}</span>
                    {turn.user.hiddenChars > 0 && (
                      <span className="text-white/55">
                        · 已折叠 {turn.user.hiddenChars} 字符系统提示
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-1.5">
                      <span className="px-1.5 py-0.5 rounded bg-white/15 text-white/85">
                        {turn.user.text.length.toLocaleString()} 字符
                      </span>
                      {turn.user.rawText && turn.user.rawText !== turn.user.text && (
                        <button
                          onClick={() =>
                            setRawOpen((prev) => ({ ...prev, [turn.index]: !prev[turn.index] }))
                          }
                          className="px-1.5 py-0.5 rounded border border-white/30 bg-white/10 text-[10.5px] text-white/90 hover:bg-white/20 transition-colors"
                          title="切换「净化后的指令」与「含系统提示的原始记录」"
                        >
                          {rawOpen[turn.index] ? '净化后' : '原始记录'}
                        </button>
                      )}
                      <CopyButton inverse text={turn.user.text} label="复制用户指令" />
                    </span>
                  </div>

                  <MemoMarkdown
                    text={turn.user.text}
                    highlight={chatQuery}
                    className="md-body md-body-inverse"
                  />

                  {rawOpen[turn.index] && (
                    <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-white/20 bg-black/25 p-2 text-[11px] leading-relaxed text-white/80 font-mono whitespace-pre-wrap break-words">
                      {turn.user.rawText}
                    </pre>
                  )}
                </div>
              )}

              {/* 思考 */}
              {turn.thinks.length > 0 && (
                <Track
                  tone="think"
                  icon={<Sparkles size={10} />}
                  title="思考过程"
                  summary={firstLine(turn.thinks[0].text, 60)}
                  count={turn.thinks.length}
                  metaText={`${turn.thinks.length} 段 · ${turn.thinks
                    .reduce((a, t) => a + t.text.length, 0)
                    .toLocaleString()} 字`}
                  open={expandAll}
                >
                  {turn.thinks.map((th, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-think/20 bg-surface/70 px-2.5 py-2"
                    >
                      <div className="text-[10px] text-ink-faint tnum mb-1">
                        {formatClock(th.ts)} ·{' '}
                        {(th.text.length + th.hiddenChars).toLocaleString()} 字符
                      </div>
                      <ClampedText
                        plain
                        text={th.text}
                        limit={900}
                        hiddenChars={th.hiddenChars}
                        onFetchOriginal={
                          th.eventIndex >= 0
                            ? () => fetchEvent(th.eventIndex, 'text').then((d) => d.text)
                            : undefined
                        }
                        className="text-[12px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-words"
                      />
                    </div>
                  ))}
                </Track>
              )}

              {/* 行动 */}
              {turn.tools.length > 0 && (
                <Track
                  tone="act"
                  icon={<Terminal size={10} />}
                  title="行动"
                  summary={summarizeTools(turn.tools.map((t) => t.name))}
                  count={turn.tools.length}
                  metaText={`${turn.tools.length} 步 · ${turn.tools
                    .reduce((a, t) => a + t.input.length + t.output.length, 0)
                    .toLocaleString()} 字`}
                  open={expandAll}
                >
                  {turn.tools.map((tl, i) => (
                    <ToolRow key={i} tool={tl} fetchEvent={fetchEvent} />
                  ))}
                </Track>
              )}

              {/* 回复 */}
              {turn.replies.map((rep, i) => (
                <div key={i} className="block-reply rounded-lg border px-3.5 py-2.5">
                  <div className="flex items-center gap-2 text-[10.5px] text-ink-faint tnum mb-1">
                    <span className="px-1.5 py-0.5 rounded bg-surface-sunken text-ink-soft font-medium">
                      回复
                    </span>
                    <span>{formatClock(rep.ts)}</span>
                    <span className="px-1.5 py-0.5 rounded bg-surface-sunken text-ink-muted">
                      {rep.text.length.toLocaleString()} 字
                    </span>
                    <span className="ml-auto">
                      <CopyButton text={rep.text} label="复制该段回复" />
                    </span>
                  </div>
                  <MemoMarkdown
                    text={rep.text}
                    highlight={chatQuery}
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
                  />
                </div>
              ))}
            </section>
          ))}

        {/* 分片续载：仅当后端明确告知还有后续轮次时出现 */}
        {!loading && !error && hasMoreTurns && (
          <div ref={moreRef} className="pt-1 flex justify-center">
            <button
              onClick={loadMoreTurns}
              disabled={loadingMore}
              className="h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft hover:bg-surface-sunken transition-colors disabled:opacity-60"
            >
              {loadingMore ? '加载中…' : '加载更多轮次'}
            </button>
          </div>
        )}
      </div>
    </ModalShell>
  );
}
