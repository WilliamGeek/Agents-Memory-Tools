'use client';

import React from 'react';
import {
  FolderOpen,
  GitBranch,
  ArrowRightLeft,
  Trash2,
  Eye,
  Check,
  MessageSquare,
  CornerDownRight,
} from 'lucide-react';
import { SessionItem } from '../../types/session';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { formatBytes, formatDateTime, formatTokens, stripDatePrefix } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

export function SessionCard({ session, onChanged }: { session: SessionItem; onChanged?: () => void }) {
  const {
    openSessionDetail,
    setActiveSubagentParent,
    setActiveMigrateSession,
    selectedCatalogIds,
    toggleSelectSession,
  } = useStore();

  const meta = platformMeta(session.format);
  const selected = selectedCatalogIds.includes(session.catalogId);
  const isEmpty = session.records === 0;

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
        session.childrenCount > 0 ? `\n将同时删除 ${session.childrenCount} 个子代理会话。\n` : ''
      }`
    );
    if (!ok) return;
    try {
      const res = await api.deleteSession(session);
      toast.success(
        `已删除，释放 ${(res.freed_bytes / 1024).toFixed(1)} KB`
      );
      onChanged?.();
    } catch (err: any) {
      toast.error(`删除失败：${err.message}`);
    }
  };

  return (
    <article
      onClick={() => openSessionDetail(session.catalogId)}
      className={`group relative flex flex-col bg-surface border rounded-card p-3.5 cursor-pointer transition-all duration-150 ${
        selected
          ? 'border-accent/50 ring-2 ring-accent/15 shadow-card'
          : 'border-line hover:border-line-strong hover:shadow-lift'
      }`}
    >
      {/* 顶部：平台 / 时间 / 选择 */}
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
          <span className="inline-flex items-center gap-1.5 min-w-0">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ backgroundColor: meta.color }}
            />
            <span className="text-[10.5px] font-medium tracking-wide uppercase text-ink-muted truncate">
              {meta.label}
            </span>
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <time className="tnum text-[10.5px] text-ink-faint">
            {formatDateTime(session.startedAt)}
          </time>
          <button
            onClick={openFolder}
            className="p-1 rounded text-ink-faint hover:text-ink hover:bg-surface-sunken transition-colors"
            title={session.filePath || '无源文件路径'}
          >
            <FolderOpen size={12} />
          </button>
        </div>
      </div>

      {/* 标题 */}
      <h3
        className="text-[13.5px] font-medium leading-[1.55] text-ink line-clamp-2 min-h-[42px] mb-2"
        title={session.title}
      >
        {stripDatePrefix(session.title)}
      </h3>

      {/* 徽标行 */}
      {(session.lineageSize > 1 || session.childrenCount > 0 || isEmpty) && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2.5">
          {session.lineageSize > 1 && (
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-warn/30 bg-warn-soft text-[10px] text-warn"
              title={
                session.sideQuestion
                  ? `/btw 旁问：${session.sideQuestion}`
                  : `与「${session.lineageHeadTitle || '同源会话'}」为同一条对话的分叉副本`
              }
            >
              <CornerDownRight size={9} />
              {session.sideQuestion ? '旁问' : session.branchLabel || '同源分支'}
            </span>
          )}
          {session.childrenCount > 0 && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                setActiveSubagentParent(session);
              }}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-accent/30 bg-accent-soft text-[10px] text-accent-ink hover:border-accent/60 transition-colors"
              title="查看该会话派生的子代理会话"
            >
              <GitBranch size={9} />
              {session.childrenCount} 子会话
            </button>
          )}
          {isEmpty && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-line bg-surface-sunken text-[10px] text-ink-faint">
              <MessageSquare size={9} />
              空会话
            </span>
          )}
        </div>
      )}

      {/* 指标 */}
      <div className="mt-auto pt-2.5 border-t border-line flex items-center gap-2 text-[11px] text-ink-muted tnum">
        <span>{session.records} 步</span>
        <span className="text-line-strong">·</span>
        <span>{formatBytes(session.bytes)}</span>
        <span className="text-line-strong">·</span>
        <span>{formatTokens(session.tokens)} tokens</span>
      </div>

      {/* 操作 */}
      <div className="grid grid-cols-3 gap-1.5 mt-2.5">
        <button
          onClick={(e) => {
            e.stopPropagation();
            openSessionDetail(session.catalogId);
          }}
          className="h-7 rounded-md border border-line bg-surface text-[11.5px] text-ink-soft inline-flex items-center justify-center gap-1 hover:bg-surface-sunken hover:text-ink transition-colors"
        >
          <Eye size={11} />
          查看
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setActiveMigrateSession(session);
          }}
          className="h-7 rounded-md border border-line bg-surface text-[11.5px] text-ink-soft inline-flex items-center justify-center gap-1 hover:bg-surface-sunken hover:text-ink transition-colors"
        >
          <ArrowRightLeft size={11} />
          迁移
        </button>
        <button
          onClick={remove}
          className="h-7 rounded-md border border-line bg-surface text-[11.5px] text-ink-muted inline-flex items-center justify-center gap-1 hover:bg-danger-soft hover:text-danger hover:border-danger/30 transition-colors"
        >
          <Trash2 size={11} />
          删除
        </button>
      </div>
    </article>
  );
}
