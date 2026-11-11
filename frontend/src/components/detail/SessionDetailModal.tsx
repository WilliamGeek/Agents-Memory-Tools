'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
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
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SessionDetail, SessionEvent } from '../../types/session';
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
}

interface ToolItem {
  name: string;
  input: string;
  output: string;
  error: boolean;
  ts: string;
}

interface ReplyItem {
  text: string;
  ts: string;
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
      if (evt.text.trim()) turn.thinks.push({ text: evt.text, ts: evt.timestamp });
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
      } else if (output) {
        turn.tools.push({
          name: evt.toolName || 'tool',
          input: '',
          output,
          error: isError,
          ts: evt.timestamp,
        });
      }
      continue;
    }

    // assistant message
    if (evt.text.trim()) turn.replies.push({ text: evt.text, ts: evt.timestamp });
  }

  return turns;
}

/* ------------------------------------------------------------------ */
/* 小组件                                                              */
/* ------------------------------------------------------------------ */

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

/** 长文本分片，避免一次渲染上百万字符 */
function ClampedText({
  text,
  limit = 1200,
  className = '',
  plain = false,
}: {
  text: string;
  limit?: number;
  className?: string;
  plain?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const truncated = text.length > limit;
  const shown = expanded || !truncated ? text : `${text.slice(0, limit)}…`;
  return (
    <div>
      {plain ? <pre className={className}>{shown}</pre> : <div className={className}>{shown}</div>}
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

function ToolRow({ tool }: { tool: ToolItem }) {
  const [open, setOpen] = useState(false);
  const meta = toolMeta(tool.name);
  return (
    <div className="rounded-md border border-act/25 bg-surface/70 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-2.5 py-1.5 flex items-center gap-2 hover:bg-act/5 transition-colors"
        title="展开查看工具参数与输出"
      >
        <span className="text-[11px] shrink-0">{meta.icon}</span>
        <span className="text-[11.5px] font-medium text-act shrink-0">{meta.label}</span>
        {tool.name && tool.name !== meta.label && (
          <span className="text-[10.5px] font-mono text-ink-faint shrink-0">{tool.name}</span>
        )}
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
          {tool.input && (
            <div className="pt-1.5">
              <div className="text-[10px] text-ink-faint mb-0.5">参数</div>
              <ClampedText
                plain
                text={tool.input}
                limit={600}
                className="text-[11.5px] leading-relaxed text-ink-soft font-mono whitespace-pre-wrap break-all"
              />
            </div>
          )}
          {tool.output && (
            <div>
              <div className="text-[10px] text-ink-faint mb-0.5">
                输出 · {tool.output.length.toLocaleString()} 字符
              </div>
              <ClampedText
                plain
                text={tool.output}
                limit={2000}
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
  open,
  children,
}: {
  tone: 'think' | 'act';
  icon: React.ReactNode;
  title: string;
  summary?: string;
  count: number;
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
          {count > 1 && <span>{count} 项</span>}
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
    closeSessionDetail,
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
  const [expandAll, setExpandAll] = useState(false);
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
        const target =
          activeDetailTurnIndex && activeDetailTurnIndex > 0 ? activeDetailTurnIndex : 1;
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

  const turns = useMemo(() => (detail ? buildTurns(detail.events) : []), [detail]);

  // 详情内检索：按轮次定位
  const hits = useMemo(() => {
    const q = chatQuery.trim().toLowerCase();
    if (!q) return [] as number[];
    const list: number[] = [];
    const scan = (txt: string, turnIndex: number) => {
      const low = (txt || '').toLowerCase();
      let from = 0;
      for (;;) {
        const at = low.indexOf(q, from);
        if (at < 0) break;
        list.push(turnIndex);
        from = at + q.length;
      }
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
    document
      .getElementById(`turn-${target}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
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

  const meta = platformMeta(detail?.format);

  const turnNav = turns.length > 1 && (
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
        {focusTurn} / {turns.length}
      </span>
      <button
        onClick={() => jumpTo(focusTurn + 1)}
        disabled={focusTurn >= turns.length}
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
                <div className="block-user rounded-lg border px-3.5 py-2.5">
                  <div className="flex items-center gap-2 text-[10.5px] tnum mb-1">
                    <span className="tag-user px-1.5 py-0.5 rounded font-medium">
                      用户指令 #{turn.index}
                    </span>
                    <span className="text-ink-faint">{formatClock(turn.user.timestamp)}</span>
                    {turn.user.hiddenChars > 0 && (
                      <span className="text-ink-faint">
                        · 已折叠 {turn.user.hiddenChars} 字符系统提示
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-1">
                      {turn.user.rawText && turn.user.rawText !== turn.user.text && (
                        <button
                          onClick={() =>
                            setRawOpen((prev) => ({ ...prev, [turn.index]: !prev[turn.index] }))
                          }
                          className="px-1.5 py-0.5 rounded border border-user/40 bg-surface/70 text-[10.5px] text-user hover:bg-surface transition-colors"
                          title="切换「净化后的指令」与「含系统提示的原始记录」"
                        >
                          {rawOpen[turn.index] ? '净化后' : '原始记录'}
                        </button>
                      )}
                      <CopyButton text={turn.user.text} label="复制用户指令" />
                    </span>
                  </div>

                  <div
                    className="md-body md-body-user"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(turn.user.text, chatQuery) }}
                  />

                  {rawOpen[turn.index] && (
                    <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-user/25 bg-surface/70 p-2 text-[11px] leading-relaxed text-ink-muted font-mono whitespace-pre-wrap break-words">
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
                  open={expandAll}
                >
                  {turn.thinks.map((th, i) => (
                    <div
                      key={i}
                      className="rounded-md border border-think/20 bg-surface/70 px-2.5 py-2"
                    >
                      <div className="text-[10px] text-ink-faint tnum mb-1">
                        {formatClock(th.ts)} · {th.text.length.toLocaleString()} 字符
                      </div>
                      <ClampedText
                        plain
                        text={th.text}
                        limit={900}
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
                  open={expandAll}
                >
                  {turn.tools.map((tl, i) => (
                    <ToolRow key={i} tool={tl} />
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
                    <span className="ml-auto">
                      <CopyButton text={rep.text} label="复制该段回复" />
                    </span>
                  </div>
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
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(rep.text, chatQuery) }}
                  />
                </div>
              ))}
            </section>
          ))}
      </div>
    </ModalShell>
  );
}
