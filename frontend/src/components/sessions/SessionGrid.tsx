'use client';

import React from 'react';
import { Inbox, FolderSearch } from 'lucide-react';
import { SessionCard } from './SessionCard';
import { SessionItem } from '../../types/session';

export function SessionGrid({
  sessions,
  isLoading,
  onChanged,
  hasQuery,
}: {
  sessions: SessionItem[];
  isLoading?: boolean;
  onChanged?: () => void;
  hasQuery?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-[168px] rounded-card border border-line bg-surface p-3.5 animate-pulse"
          >
            <div className="h-3 w-24 bg-surface-sunken rounded mb-3" />
            <div className="h-3.5 w-full bg-surface-sunken rounded mb-2" />
            <div className="h-3.5 w-2/3 bg-surface-sunken rounded mb-6" />
            <div className="h-3 w-40 bg-surface-sunken rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="py-20 border border-dashed border-line-strong rounded-card bg-surface flex flex-col items-center justify-center text-center px-6">
        <span className="w-11 h-11 rounded-full bg-surface-sunken border border-line flex items-center justify-center text-ink-faint mb-3">
          {hasQuery ? <FolderSearch size={19} /> : <Inbox size={19} />}
        </span>
        <h3 className="text-[14px] font-medium text-ink">
          {hasQuery ? '没有匹配的会话' : '还没有收录任何会话'}
        </h3>
        <p className="text-[12.5px] text-ink-muted mt-1.5 max-w-sm leading-relaxed">
          {hasQuery
            ? '试试缩短关键词，或切换到「全部」平台后再看。'
            : '在右上角「扫描目录」里登记各智能体的会话目录，然后点击「刷新数据」。'}
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
      {sessions.map((s) => (
        <SessionCard key={s.catalogId} session={s} onChanged={onChanged} />
      ))}
    </div>
  );
}
