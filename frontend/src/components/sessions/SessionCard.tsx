'use client';

import React, { useState } from 'react';
import {
  FolderOpen,
  ArrowRightLeft,
  Check,
  MessageSquare,
  CornerDownRight,
  Copy,
  CopyMinus,
  ChevronDown,
} from 'lucide-react';
import { SessionChild, SessionItem } from '../../types/session';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { formatBytes, formatDateTime, formatTokens, stripDatePrefix } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

const NL = String.fromCharCode(10);

export function SessionCard({ session, onChanged }: { session: SessionItem; onChanged?: () => void }) {
  const {
    openSessionDetail,
    setActiveMigrateSession,
    selectedCatalogIds,
    toggleSelectSession,
    openSessionDetail: openDetail,
  } = useStore();
  const [childrenOpen, setChildrenOpen] = useState(false);
  const [fetchedChildren, setFetchedChildren] = useState<SessionChild[] | null>(null);
  const [childrenState, setChildrenState] = useState<'idle' | 'loading' | 'ready' | 'error'>(
    'idle'
  );
  const [copied, setCopied] = useState<string | null>(null);
  const [expandedChildIds, setExpandedChildIds] = useState<Set<string>>(new Set());

  const toggleChildInlineCard = (childId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedChildIds((prev) => {
      const next = new Set(prev);
      if (next.has(childId)) next.delete(childId);
      else next.add(childId);
      return next;
    });
  };

  const meta = platformMeta(session.format);
  const recorded = session.usageSource === 'recorded';
  // “最近活跃”按 mtime 排序；卡片右上角显示同一时间基准，
  // 避免标题里的原始日期与排序结果看起来互相矛盾。
  const displayTime = session.mtime || session.startedAt;
  const tokenLabel = recorded
    ? `${formatTokens(session.tokens)} 累计 Tokens`
    : `≈ ${formatTokens(session.tokens)} Tokens`;
  const cacheHitPct =
    recorded && session.inputTokens > 0
      ? Math.round((session.cacheReadTokens / session.inputTokens) * 100)
      : 0;
  const freshTokens = session.freshTokens || session.cacheMissTokens + session.outputTokens;
  const tokenTip = recorded
    ? [
        '真实用量（客户端自身记录）',
        `• 累计 Token（含缓存命中）: ${session.tokens.toLocaleString()}`,
        `• 输入（上下文累计）: ${session.inputTokens.toLocaleString()}`,
        `• 缓存命中（重复上下文）: ${session.cacheReadTokens.toLocaleString()} (${cacheHitPct}%)`,
        `• 缓存未命中（新输入）: ${session.cacheMissTokens.toLocaleString()}`,
        `• 有效总量（未命中 + 输出）: ${freshTokens.toLocaleString()}`,
        `• 输出（含思考）: ${session.outputTokens.toLocaleString()}`,
        `• 思考: ${session.thoughtsTokens.toLocaleString()}`,
        `• 内容体积（去重）: ${session.contentTokens.toLocaleString()}`,
      ].join(NL)
    : [
        '估算用量（客户端未记录，按内容体积分词）',
        `• 内容体积: ${session.tokens.toLocaleString()} Tokens`,
        '• 实际计费通常为其数倍：每轮对话都会重发整段上下文',
      ].join(NL);
  const selected = selectedCatalogIds.includes(session.catalogId);
  const isEmpty = session.records === 0;
  const hasChildren = session.childrenCount > 0;
  const isForkGroup = session.lineageSize > 1 && !session.isLineageBranch;

  const copy = async (text: string, label: string, e: React.MouseEvent, key: string) => {
    e.stopPropagation();
    if (!text) {
      toast.error(`该会话没有可复制的${label}`);
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      toast.error('复制失败，请手动选择文本');
    }
  };

  const openFolder = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!session.filePath) {
      toast.error('该会话没有可定位的源文件');
      return;
    }
    try {
      await api.openFolder(session.filePath);
      toast.success('已在资源管理器中定位');
    } catch (err: any) {
      toast.error(`打开目录失败：${err.message}`);
    }
  };

  const remove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const ok = window.confirm(
      `确定彻底删除该会话？\n\n${session.title}\n${
        hasChildren ? `\n将同时删除 ${session.childrenCount} 个子代理会话。\n` : ''
      }`
    );
    if (!ok) return;
    try {
      const res = await api.deleteSession(session);
      toast.success(`已删除，释放 ${(res.freed_bytes / 1024).toFixed(1)} KB`);
      onChanged?.();
    } catch (err: any) {
      toast.error(`删除失败：${err.message}`);
    }
  };

  /**
   * 子会话按需拉取。
   *
   * lite 字段集只带 children_count、不再带 children，所以首次展开时才请求
   * /api/session/children；全量字段集（后端未升级）下 children 已在手，直接复用，
   * 不产生额外请求——展开行为与改造前一致。
   */
  const toggleChildren = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const next = !childrenOpen;
    setChildrenOpen(next);
    if (!next) return;
    if (childrenState === 'loading' || childrenState === 'ready') return;
    if (session.children.length > 0) {
      setFetchedChildren(session.children);
      setChildrenState('ready');
      return;
    }
    if (!session.catalogId) {
      setFetchedChildren([]);
      setChildrenState('error');
      return;
    }
    setChildrenState('loading');
    try {
      const list = await api.getSessionChildren(session.catalogId, { strict: true });
      setFetchedChildren(list);
      setChildrenState('ready');
    } catch {
      setFetchedChildren([]);
      setChildrenState('error');
    }
  };

  const childList = fetchedChildren ?? session.children;

  return (
    <article
      onClick={() => openSessionDetail(session.catalogId)}
      style={{ ['--rail-color' as any]: meta.color }}
      className={`rail group relative flex flex-col bg-surface border rounded-card p-3.5 cursor-pointer transition-all duration-150 ${
        selected
          ? 'border-accent/50 ring-2 ring-accent/15 shadow-card'
          : 'border-line hover:border-line-strong hover:shadow-lift'
      }`}
    >
      {/* 顶部：平台 / 谱系徽标 / 时间 */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <button
            onClick={(e) => {
              e.stopPropagation();
              toggleSelectSession(session.catalogId);
            }}
            className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
              selected
                ? 'bg-accent border-accent text-white'
                : 'border-line-strong bg-surface hover:border-ink-faint'
            }`}
            title={selected ? '取消选择' : '选择该会话'}
            aria-label="选择会话"
          >
            {selected && <Check size={11} strokeWidth={3} />}
          </button>
          <span
            className="inline-flex items-center gap-1.5 min-w-0 px-1.5 py-0.5 rounded border border-line bg-surface-muted"
            style={{ borderColor: `${meta.color}33` }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: meta.color }}
            />
            <span className="text-[10px] font-medium tracking-wide uppercase text-ink-muted truncate">
              {meta.label}
            </span>
          </span>

          {/* 分叉徽标：主副本显示「⧉ N 个分叉」，副本显示「↳ 同源分支 / 旁问」 */}
          {session.isLineageBranch ? (
            <span
              className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-warn/30 bg-warn-soft text-[9.5px] text-warn"
              title={
                session.sideQuestion
                  ? `/btw 旁问：${session.sideQuestion}`
                  : `与「${session.lineageHeadTitle || '主副本'}」是同一条对话的分叉快照（主副本 ${session.lineageHeadSteps} 步）`
              }
            >
              <CornerDownRight size={8} />
              {session.sideQuestion ? '旁问' : session.branchLabel || '同源分支'}
            </span>
          ) : isForkGroup ? (
            <span
              className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-line bg-surface-sunken text-[9.5px] text-ink-muted"
              title={`这条对话另有 ${session.lineageSize - 1} 个分叉副本占用磁盘`}
            >
              <CopyMinus size={8} />
              {session.lineageSize} 个分叉
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <time className="tnum text-[10.5px] text-ink-faint">
            {formatDateTime(displayTime)}
          </time>
        </div>
      </div>

      {/* 标题 */}
      <h3
        className="text-[13.5px] font-medium leading-[1.55] text-ink line-clamp-2 mb-1.5"
        title={session.title}
      >
        {stripDatePrefix(session.title)}
      </h3>

      {/* 旁问正文摘录 */}
      {session.sideQuestion && (
        <p
          className="mb-2 text-[11.5px] text-warn line-clamp-1"
          title={`/btw 旁问：${session.sideQuestion}`}
        >
          旁问：{session.sideQuestion}
        </p>
      )}

      {/* 指标行：步数 · 大小 · Token · UUID · 绝对路径 */}
      <div className="mt-auto pt-2 border-t border-line flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-ink-muted tnum">
        <span>{session.records} 步</span>
        <span className="text-line-strong">·</span>
        <span>{formatBytes(session.bytes)}</span>
        <span className="text-line-strong">·</span>
        <span className={recorded ? '' : 'text-ink-faint'} title={tokenTip}>
          {tokenLabel}
        </span>
        <span className="text-line-strong">·</span>
        <button
          onClick={(e) => copy(session.sessionId, ' UUID', e, 'id')}
          className={`inline-flex items-center gap-0.5 transition-colors ${
            copied === 'id' ? 'text-ok' : 'hover:text-ink'
          }`}
          title={`点击复制 UUID：${session.sessionId}`}
        >
          {copied === 'id' ? <Check size={9} /> : <Copy size={9} />}
          {copied === 'id' ? '已复制' : `${session.sessionId.slice(0, 8)}…`}
        </button>
        <span className="text-line-strong">·</span>
        <button
          onClick={(e) => copy(session.filePath, '绝对路径', e, 'path')}
          className={`inline-flex items-center gap-0.5 underline decoration-dotted underline-offset-2 transition-colors ${
            copied === 'path' ? 'text-ok no-underline font-medium' : 'hover:text-ink'
          }`}
          title={`点击复制绝对路径：${session.filePath}`}
        >
          {copied === 'path' ? (
            <>
              <Check size={9} />
              <span>已复制</span>
            </>
          ) : (
            '绝对路径'
          )}
        </button>
        {hasChildren && (
          <>
            <span className="text-line-strong">·</span>
            <button
              type="button"
              onClick={toggleChildren}
              className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium transition-colors ${
                childrenOpen
                  ? 'bg-purple-500/25 border border-purple-500/60 text-purple-200 shadow-sm'
                  : 'bg-purple-500/10 border border-purple-500/30 text-purple-300 hover:bg-purple-500/20 hover:text-white'
              }`}
              title={`点击展开 / 收起下属 ${session.childrenCount} 个子代理会话`}
            >
              <span>↳</span>
              <span>{session.childrenCount} 个子会话</span>
              <ChevronDown
                size={10}
                className={`transition-transform duration-200 ${childrenOpen ? 'rotate-180' : ''}`}
              />
            </button>
          </>
        )}
      </div>

      {/* 子代理会话抽屉（对齐历史版本双层卡片：一级紧凑行 + 二级就地展开操作卡片） */}
      {hasChildren && childrenOpen && (
        <div className="mt-3 pt-2.5 border-t border-dashed border-line/80 space-y-2 anim-down">
          <div className="flex items-center justify-between text-[11px] text-ink-muted font-medium px-0.5">
            <span>↳ 下属子代理会话 ({session.childrenCount})</span>
            {childrenState === 'loading' && <span className="text-ink-faint">加载中…</span>}
          </div>

          {childrenState === 'error' && (
            <div className="px-2.5 py-2 rounded-md bg-surface-muted border border-line text-[11.5px] text-ink-faint">
              子会话列表不可用
            </div>
          )}

          {childrenState !== 'loading' && childrenState !== 'error' && (
            <div className="space-y-1.5 max-h-[360px] overflow-y-auto pr-0.5">
              {childList.map((child) => {
                const isExpanded = expandedChildIds.has(child.catalogId);
                return (
                  <div
                    key={child.catalogId}
                    className="rounded-md border border-line bg-surface-muted/60 overflow-hidden hover:border-line-strong transition-colors"
                  >
                    {/* 一级紧凑行：优先显示标题，保留单个查看/收起按钮 */}
                    <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11.5px]">
                      <div className="flex items-center gap-1.5 min-w-0 flex-1">
                        <span className="px-1.5 py-0.5 rounded bg-purple-500/15 border border-purple-500/30 text-purple-300 text-[10px] font-mono font-semibold shrink-0">
                          {child.agentName || 'subagent'}
                        </span>
                        <span
                          className="text-[11.5px] font-medium text-ink truncate cursor-pointer hover:text-primary transition-colors"
                          title={child.title}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (child.catalogId) openDetail(child.catalogId);
                          }}
                        >
                          {stripDatePrefix(child.title)}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5 text-[10px] text-ink-muted tnum shrink-0">
                        <time className="text-ink-faint">
                          {child.startedAt ? stripDatePrefix(child.startedAt).slice(0, 11) : ''}
                        </time>
                        <span className="text-line-strong">·</span>
                        <span>{child.records} 步</span>
                        <span className="text-line-strong">·</span>
                        <span>{formatBytes(child.bytes)}</span>
                        <span className="text-line-strong">·</span>
                        <span className="text-warn">
                          {child.usageSource === 'recorded' ? '累计 ' : ''}
                          {formatTokens(child.tokens)}
                        </span>
                      </div>

                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={(e) => toggleChildInlineCard(child.catalogId, e)}
                          className={`px-2 py-0.5 rounded border text-[10.5px] inline-flex items-center gap-1 transition-colors ${
                            isExpanded
                              ? 'bg-purple-500/20 border-purple-500/40 text-purple-200'
                              : 'border-line text-ink-muted hover:text-ink hover:bg-surface-sunken'
                          }`}
                          title={isExpanded ? '收起详情卡片' : '展开详情卡片'}
                        >
                          <span>{isExpanded ? '收起' : '查看'}</span>
                          <ChevronDown
                            size={9}
                            className={`transition-transform duration-150 ${isExpanded ? 'rotate-180' : ''}`}
                          />
                        </button>
                      </div>
                    </div>

                    {/* 二级就地展开完整卡片 */}
                    {isExpanded && (
                      <div className="p-2.5 bg-black/15 border-t border-line space-y-2">
                        <div className="text-[12px] font-medium text-ink leading-snug line-clamp-2" title={child.title}>
                          {stripDatePrefix(child.title)}
                        </div>

                        <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[10.5px] text-ink-muted tnum">
                          <span>{child.records} 步</span>
                          <span className="text-line-strong">·</span>
                          <span>{formatBytes(child.bytes)}</span>
                          <span className="text-line-strong">·</span>
                          <span>{Number(child.tokens || 0).toLocaleString()} Tokens</span>
                          <span className="text-line-strong">·</span>
                          <button
                            type="button"
                            onClick={(e) => copy(child.sessionId, ' UUID', e, `child-id-${child.catalogId}`)}
                            className={`inline-flex items-center gap-0.5 transition-colors ${
                              copied === `child-id-${child.catalogId}` ? 'text-ok font-medium' : 'hover:text-ink'
                            }`}
                            title={`点击复制 UUID: ${child.sessionId}`}
                          >
                            {copied === `child-id-${child.catalogId}` ? <Check size={8} /> : <Copy size={8} />}
                            {copied === `child-id-${child.catalogId}` ? '已复制' : `${child.sessionId.slice(0, 8)}…`}
                          </button>
                          {child.filePath && (
                            <>
                              <span className="text-line-strong">·</span>
                              <button
                                type="button"
                                onClick={(e) => copy(child.filePath!, '绝对路径', e, `child-path-${child.catalogId}`)}
                                className={`inline-flex items-center gap-0.5 underline decoration-dotted underline-offset-2 transition-colors ${
                                  copied === `child-path-${child.catalogId}` ? 'text-ok no-underline font-medium' : 'hover:text-ink'
                                }`}
                                title={`绝对路径: ${child.filePath}`}
                              >
                                {copied === `child-path-${child.catalogId}` ? (
                                  <>
                                    <Check size={8} />
                                    <span>已复制</span>
                                  </>
                                ) : (
                                  '绝对路径'
                                )}
                              </button>
                            </>
                          )}
                        </div>

                        {/* 4 个操作按钮 */}
                        <div className="flex items-center gap-1 pt-1">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              if (child.catalogId) openDetail(child.catalogId);
                            }}
                            className="flex-1 h-6 rounded border border-line bg-surface text-[10.5px] text-ink-soft hover:bg-surface-sunken hover:text-ink transition-colors"
                            title="查看该子会话详细交互"
                          >
                            查看详情
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setActiveMigrateSession({
                                ...session,
                                catalogId: child.catalogId,
                                sessionId: child.sessionId,
                                title: child.title,
                                bytes: child.bytes,
                                tokens: child.tokens,
                                records: child.records,
                                filePath: child.filePath || '',
                                children: [],
                                childrenCount: 0,
                              });
                            }}
                            className="flex-1 h-6 rounded bg-accent text-white text-[10.5px] font-medium hover:bg-accent-ink transition-colors"
                            title="跨平台迁移该会话"
                          >
                            迁移
                          </button>
                          <button
                            type="button"
                            onClick={async (e) => {
                              e.stopPropagation();
                              if (!window.confirm(`确定彻底删除该子代理会话？\n\n${child.title}`)) return;
                              try {
                                const res = await api.deleteByCatalogId(child.catalogId);
                                toast.success(`子会话已删除，释放 ${(res.freed_bytes / 1024).toFixed(1)} KB`);
                                setFetchedChildren((prev) => (prev ? prev.filter((c) => c.catalogId !== child.catalogId) : null));
                                onChanged?.();
                              } catch (err: any) {
                                toast.error(`删除失败：${err.message}`);
                              }
                            }}
                            className="flex-1 h-6 rounded border border-line bg-surface text-[10.5px] text-ink-muted hover:bg-danger-soft hover:text-danger hover:border-danger/30 transition-colors"
                            title="删除该子代理会话"
                          >
                            删除
                          </button>
                          {child.filePath && (
                            <button
                              type="button"
                              onClick={async (e) => {
                                e.stopPropagation();
                                try {
                                  await api.openFolder(child.filePath!);
                                  toast.success('已在资源管理器中定位');
                                } catch (err: any) {
                                  toast.error(`打开目录失败：${err.message}`);
                                }
                              }}
                              className="w-6 h-6 rounded border border-line bg-surface text-ink-muted inline-flex items-center justify-center hover:bg-surface-sunken hover:text-ink transition-colors"
                              title="打开所在资源管理器并选中文件"
                            >
                              <FolderOpen size={11} />
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 空会话标记 */}
      {isEmpty && (
        <div className="mt-2">
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-line bg-surface-sunken text-[10px] text-ink-faint">
            <MessageSquare size={9} />
            空会话
          </span>
        </div>
      )}

      {/* 操作：查看 / 迁移 / 删除 / 文件夹 */}
      <div className="flex items-center gap-1.5 mt-2.5">
        <button
          onClick={(e) => {
            e.stopPropagation();
            openSessionDetail(session.catalogId);
          }}
          className="flex-1 h-7 rounded-md border border-line bg-surface text-[11.5px] text-ink-soft hover:bg-surface-sunken hover:text-ink transition-colors"
          title="查看会话消息历史"
        >
          查看
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setActiveMigrateSession(session);
          }}
          className="flex-1 h-7 rounded-md bg-accent text-white text-[11.5px] font-medium hover:bg-accent-ink transition-colors"
          title="跨平台迁移该会话"
        >
          迁移
        </button>
        <button
          onClick={remove}
          className="flex-1 h-7 rounded-md border border-line bg-surface text-[11.5px] text-ink-muted hover:bg-danger-soft hover:text-danger hover:border-danger/30 transition-colors"
          title="彻底删除该会话及其子会话文件"
        >
          删除
        </button>
        <button
          onClick={openFolder}
          className="w-7 h-7 rounded-md border border-line bg-surface text-ink-muted inline-flex items-center justify-center hover:bg-surface-sunken hover:text-ink transition-colors"
          title="打开所在资源管理器并选中文件"
        >
          <FolderOpen size={12} />
        </button>
      </div>

    </article>
  );
}
