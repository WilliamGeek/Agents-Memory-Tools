'use client';

import React from 'react';
import { GitBranch, Eye, ArrowRightLeft } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { SideSheet } from '../ui/Overlay';
import { formatBytes, formatDateTime, formatTokens } from '../../lib/format';
import { platformMeta } from '../../lib/platform';

export function SubagentDrawer() {
  const { activeSubagentParent, setActiveSubagentParent, openSessionDetail, setActiveMigrateSession } =
    useStore();

  const parent = activeSubagentParent;
  const children = parent?.children || [];

  return (
    <SideSheet
      open={Boolean(parent)}
      onClose={() => setActiveSubagentParent(null)}
      icon={<GitBranch size={15} />}
      title="子代理会话"
      subtitle={parent ? `父会话：${parent.title}` : undefined}
      width="max-w-lg"
      footer={
        parent ? (
          <div className="flex items-center justify-between text-[11.5px] text-ink-muted tnum">
            <span>共 {children.length} 个子会话</span>
            <span>
              {children.reduce((a, c) => a + (c.records || 0), 0)} 步 ·{' '}
              {formatBytes(children.reduce((a, c) => a + (c.bytes || 0), 0))}
            </span>
          </div>
        ) : undefined
      }
    >
      <div className="p-4 space-y-3">
        {children.length === 0 && (
          <div className="py-16 text-center text-[12.5px] text-ink-muted">
            该会话没有派生出的子代理记录
          </div>
        )}

        {children.map((child, i) => {
          const meta = platformMeta(child.format || parent?.format);
          return (
            <div
              key={child.catalogId || i}
              className="rounded-lg border border-line bg-surface p-3 hover:border-line-strong transition-colors"
            >
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <span className="inline-flex items-center gap-1.5 text-[10.5px] text-ink-muted">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: meta.color }}
                  />
                  <span className="uppercase tracking-wide">{meta.label}</span>
                  {child.agentName && (
                    <span className="px-1.5 py-0.5 rounded bg-surface-sunken border border-line text-[10px]">
                      {child.agentName}
                    </span>
                  )}
                </span>
                <time className="tnum text-[10.5px] text-ink-faint">
                  {formatDateTime(child.startedAt)}
                </time>
              </div>

              <h4 className="text-[13px] leading-relaxed text-ink line-clamp-2" title={child.title}>
                {child.title}
              </h4>

              <div className="mt-2 pt-2 border-t border-line flex items-center justify-between">
                <span className="text-[11px] text-ink-muted tnum">
                  {child.records} 步 · {formatBytes(child.bytes)} ·{' '}
                  {formatTokens(child.tokens)} tokens
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => {
                      const id = child.catalogId;
                      setActiveSubagentParent(null);
                      if (id) openSessionDetail(id);
                    }}
                    className="h-6.5 px-2 py-1 rounded border border-line bg-surface text-[11px] text-ink-soft inline-flex items-center gap-1 hover:bg-surface-sunken transition-colors"
                  >
                    <Eye size={10} />
                    查看
                  </button>
                  <button
                    onClick={() => {
                      setActiveSubagentParent(null);
                      if (parent) {
                        setActiveMigrateSession({
                          ...parent,
                          children: [child],
                          title: child.title,
                        } as any);
                      }
                    }}
                    className="px-2 py-1 rounded border border-line bg-surface text-[11px] text-ink-soft inline-flex items-center gap-1 hover:bg-surface-sunken transition-colors"
                  >
                    <ArrowRightLeft size={10} />
                    迁移
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </SideSheet>
  );
}
