'use client';

import React, { useState } from 'react';
import { Layers, CheckSquare, Square, Trash2, ArrowRightLeft, Loader2 } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SessionItem } from '../../types/session';
import { toast } from 'sonner';
import { SideSheet } from '../ui/Overlay';
import { platformMeta, targetHint } from '../../lib/platform';
import { formatBytes, formatDateTime, stripDatePrefix } from '../../lib/format';

const TARGETS = ['claude', 'antigravity', 'workbuddy', 'cursor', 'trae', 'copilot'];

export function BatchManagementDrawer({
  sessions,
  onBatchActionFinished,
}: {
  sessions: SessionItem[];
  onBatchActionFinished?: () => void;
}) {
  const {
    isBatchDrawerOpen,
    setIsBatchDrawerOpen,
    selectedCatalogIds,
    toggleSelectSession,
    selectAllSessions,
    clearSelectedSessions,
  } = useStore();
  const [target, setTarget] = useState('claude');
  const [busy, setBusy] = useState<'' | 'migrate' | 'delete'>('');

  const close = () => setIsBatchDrawerOpen(false);
  const selectedCount = selectedCatalogIds.length;
  const allSelected = sessions.length > 0 && selectedCount === sessions.length;

  const doMigrate = async () => {
    if (!selectedCount) return;
    setBusy('migrate');
    try {
      const res = await api.batchMigrateSessions(selectedCatalogIds, target);
      toast.success(`批量迁移完成：成功 ${res.success_count} / ${selectedCount}`);
      onBatchActionFinished?.();
    } catch (e: any) {
      toast.error(`批量迁移失败：${e.message}`);
    } finally {
      setBusy('');
    }
  };

  const doDelete = async () => {
    if (!selectedCount) return;
    const ok = window.confirm(
      `确认删除选中的 ${selectedCount} 个会话？\n\n该操作会同时清理其下派生的子代理会话，且不可撤销。`
    );
    if (!ok) return;
    setBusy('delete');
    try {
      const selected = sessions.filter((s) => selectedCatalogIds.includes(s.catalogId));
      const res = await api.batchDeleteSessions(selected);
      toast.success(`已删除 ${res.deleted_count} 个会话，释放 ${res.total_freed_mb} MB`);
      clearSelectedSessions();
      onBatchActionFinished?.();
    } catch (e: any) {
      toast.error(`批量删除失败：${e.message}`);
    } finally {
      setBusy('');
    }
  };

  return (
    <SideSheet
      open={isBatchDrawerOpen}
      onClose={close}
      icon={<Layers size={15} />}
      title="批量管理"
      subtitle={`已选 ${selectedCount} / 共 ${sessions.length} 个会话`}
      width="max-w-xl"
      footer={
        <div className="space-y-2.5">
          <div className="flex items-center gap-2">
            <select
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className="h-8 flex-1 px-2 rounded-md border border-line bg-surface text-[12px] text-ink-soft"
            >
              {TARGETS.map((t) => (
                <option key={t} value={t}>
                  迁移至 {platformMeta(t).label}（{targetHint(t)}）
                </option>
              ))}
            </select>
            <button
              onClick={doMigrate}
              disabled={!selectedCount || busy !== ''}
              className="h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft inline-flex items-center gap-1.5 hover:bg-surface-sunken disabled:opacity-50 transition-colors"
            >
              {busy === 'migrate' ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <ArrowRightLeft size={12} />
              )}
              批量迁移
            </button>
            <button
              onClick={doDelete}
              disabled={!selectedCount || busy !== ''}
              className="h-8 px-3 rounded-md border border-danger/30 bg-danger-soft text-[12.5px] text-danger inline-flex items-center gap-1.5 hover:bg-danger/10 disabled:opacity-50 transition-colors"
            >
              {busy === 'delete' ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Trash2 size={12} />
              )}
              批量删除
            </button>
          </div>
          <p className="text-[11px] text-ink-faint">
            迁移产物写入 exports 目录；删除将连同子代理会话一并清理，不可撤销。
          </p>
        </div>
      }
    >
      <div className="p-4 space-y-2">
        <div className="flex items-center justify-between pb-2 border-b border-line">
          <button
            onClick={() =>
              allSelected ? clearSelectedSessions() : selectAllSessions(sessions.map((s) => s.catalogId))
            }
            className="inline-flex items-center gap-1.5 text-[12px] text-ink-soft hover:text-ink"
          >
            {allSelected ? <CheckSquare size={13} /> : <Square size={13} />}
            {allSelected ? '取消全选' : '全选当前列表'}
          </button>
          {selectedCount > 0 && (
            <button
              onClick={clearSelectedSessions}
              className="text-[12px] text-ink-muted hover:text-danger"
            >
              清空选择
            </button>
          )}
        </div>

        {sessions.length === 0 && (
          <div className="py-16 text-center text-[12.5px] text-ink-muted">当前列表没有会话</div>
        )}

        {sessions.map((s) => {
          const checked = selectedCatalogIds.includes(s.catalogId);
          const meta = platformMeta(s.format);
          return (
            <label
              key={s.catalogId}
              className={`flex items-start gap-2.5 rounded-lg border px-2.5 py-2 cursor-pointer transition-colors ${
                checked ? 'border-accent/40 bg-accent-soft/50' : 'border-line hover:border-line-strong'
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleSelectSession(s.catalogId)}
                className="mt-0.5 accent-[#1f6feb]"
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[10.5px] text-ink-muted">
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: meta.color }}
                  />
                  {meta.label}
                  <span className="text-line-strong">|</span>
                  <span className="tnum">{formatDateTime(s.startedAt)}</span>
                  {s.childrenCount > 0 && (
                    <span className="px-1 rounded bg-surface-sunken border border-line text-[9.5px]">
                      +{s.childrenCount} 子会话
                    </span>
                  )}
                </div>
                <p className="text-[12.5px] text-ink leading-snug line-clamp-1 mt-0.5" title={s.title}>
                  {stripDatePrefix(s.title)}
                </p>
                <p className="text-[10.5px] text-ink-faint tnum mt-0.5">
                  {s.records} 步 · {formatBytes(s.bytes)}
                </p>
              </div>
            </label>
          );
        })}
      </div>
    </SideSheet>
  );
}
