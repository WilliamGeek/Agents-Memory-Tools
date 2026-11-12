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
  const [copied, setCopied] = useState<'id' | 'path' | null>(null);

  const meta = platformMeta(session.format);
  const recorded = session.usageSource === 'recorded';
  const tokenLabel = `${recorded ? '' : '≈ '}${formatTokens(session.tokens)} Tokens`;
  const tokenTip = recorded
    ? [
        '真实用量（客户端自身记录）',
        `• 计费总量: ${session.tokens.toLocaleString()} Tokens`,
        `• 输入（上下文累计）: ${session.inputTokens.toLocaleString()} Tokens`,
        `• 输出（含思考）: ${session.outputTokens.toLocaleString()} Tokens`,
        `• 思考: ${session.thoughtsTokens.toLocaleString()} Tokens`,
        `• 内容体积（去重）: ${session.contentTokens.toLocaleString()} Tokens`,
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

  const copy = async (text: string, label: string, e: React.MouseEvent, key: 'id' | 'path') => {
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
            {formatDateTime(session.startedAt)}
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
              onClick={toggleChildren}
              className="inline-flex items-center gap-0.5 text-accent-ink hover:underline"
              title={`展开 / 收起下属 ${session.childrenCount} 个子代理会话`}
            >
              ↳ {session.childrenCount} 个子会话
              <ChevronDown
                size={10}
                className={`transition-transform ${childrenOpen ? 'rotate-180' : ''}`}
              />
            </button>
          </>
        )}
      </div>

      {/* 子会话：就地展开（lite 字段集下首次展开才拉取列表） */}
      {hasChildren && (
        <div className="mt-2">
          {childrenOpen && (
            <div className="mt-1.5 rounded-md border border-line bg-surface-muted divide-y divide-line/70 max-h-[220px] overflow-y-auto">
              {childrenState === 'loading' && (
                <div className="px-2 py-1.5 text-[11.5px] text-ink-faint">加载中…</div>
              )}
              {childrenState === 'error' && (
                <div className="px-2 py-1.5 text-[11.5px] text-ink-faint">子会话列表不可用</div>
              )}
              {childrenState !== 'loading' &&
                childrenState !== 'error' &&
                childList.map((child) => (
                  <div
                    key={child.catalogId}
                    className="px-2 py-1.5 hover:bg-surface-sunken transition-colors"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (child.catalogId) openDetail(child.catalogId);
                    }}
                  >
                    <p className="text-[11.5px] text-ink-soft line-clamp-1" title={child.title}>
                      {stripDatePrefix(child.title)}
                    </p>
                    <p className="text-[10px] text-ink-faint tnum mt-0.5">
                      {child.records} 步 · {formatBytes(child.bytes)}
                      {child.agentName ? ` · ${child.agentName}` : ''}
                    </p>
                  </div>
                ))}
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
