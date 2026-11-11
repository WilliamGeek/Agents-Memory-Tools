'use client';

import React, { useMemo, useState } from 'react';
import {
  Layers,
  CheckSquare,
  Square,
  Trash2,
  ArrowRightLeft,
  Loader2,
  RotateCcw,
  Filter,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { SessionItem } from '../../types/session';
import { toast } from 'sonner';
import { SideSheet } from '../ui/Overlay';
import { platformMeta, targetHint } from '../../lib/platform';
import { formatBytes, formatDateTime, parseTime, stripDatePrefix } from '../../lib/format';

const TARGETS = ['claude', 'antigravity', 'workbuddy', 'cursor', 'trae', 'copilot'];

type TimeType = 'all' | 'days_before' | 'days_within' | 'date_before' | 'date_after';

const TIME_OPTIONS: { value: TimeType; label: string }[] = [
  { value: 'all', label: '全部时间' },
  { value: 'days_before', label: '早于距今（天前）' },
  { value: 'days_within', label: '距今最近（天内）' },
  { value: 'date_before', label: '早于指定日期' },
  { value: 'date_after', label: '晚于指定日期' },
];

/** 存储形态：便于判断删除时会不会影响共享库 */
function storageShape(s: SessionItem): string {
  const p = s.filePath.toLowerCase();
  const ext = p.includes('.') ? p.slice(p.lastIndexOf('.') + 1) : '';
  if (ext === 'jsonl' || ext === 'json') return '独立文件';
  if (ext === 'vscdb' || ext === 'sqlite' || ext === 'sqlite3') return '共享数据库';
  if (ext === 'db') return s.format === 'trae' ? '共享数据库' : '独立会话库';
  return ext ? `${ext.toUpperCase()} 文件` : '未知形态';
}

const emptyFilters = {
  format: 'all',
  minSize: '',
  maxSize: '',
  sizeUnit: 'MB' as 'B' | 'KB' | 'MB',
  minSteps: '',
  maxSteps: '',
  timeType: 'all' as TimeType,
  days: '',
  date: '',
};

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
  const [f, setF] = useState({ ...emptyFilters });

  const close = () => setIsBatchDrawerOpen(false);

  const filtered = useMemo(() => {
    const now = Date.now();
    const unit = f.sizeUnit === 'MB' ? 1024 ** 2 : f.sizeUnit === 'KB' ? 1024 : 1;
    const minB = f.minSize ? Number(f.minSize) * unit : null;
    const maxB = f.maxSize ? Number(f.maxSize) * unit : null;
    const minSteps = f.minSteps ? Number(f.minSteps) : null;
    const maxSteps = f.maxSteps ? Number(f.maxSteps) : null;
    const days = f.days ? Number(f.days) : null;
    const dateTs = f.date ? parseTime(f.date)?.getTime() ?? null : null;

    return sessions.filter((s) => {
      if (f.format !== 'all' && s.format !== f.format) return false;
      if (minB !== null && s.bytes < minB) return false;
      if (maxB !== null && s.bytes > maxB) return false;
      if (minSteps !== null && s.records < minSteps) return false;
      if (maxSteps !== null && s.records > maxSteps) return false;

      const lastActive = s.mtime ? s.mtime * 1000 : parseTime(s.startedAt)?.getTime() ?? 0;
      if (f.timeType === 'days_before' && days !== null) {
        if (lastActive > now - days * 86400000) return false;
      } else if (f.timeType === 'days_within' && days !== null) {
        if (lastActive < now - days * 86400000) return false;
      } else if (f.timeType === 'date_before' && dateTs !== null) {
        if (lastActive >= dateTs) return false;
      } else if (f.timeType === 'date_after' && dateTs !== null) {
        if (lastActive <= dateTs) return false;
      }
      return true;
    });
  }, [sessions, f]);

  const selectedCount = selectedCatalogIds.length;
  const visibleIds = filtered.map((s) => s.catalogId);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedCatalogIds.includes(id));
  const totalBytes = filtered.reduce((a, s) => a + (s.bytes || 0), 0);

  const doMigrate = async () => {
    if (!selectedCount) return;
    const ok = window.confirm(
      `确认将选中的 ${selectedCount} 个会话迁移至 ${platformMeta(target).label}？\n\n` +
        `产物写入目标平台的原生存储目录，可直接被该平台读取；原会话不做改动。`
    );
    if (!ok) return;
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

  const inputCls =
    'h-8 px-2 rounded-md border border-line bg-surface text-[12px] text-ink placeholder:text-ink-faint focus:bg-surface-muted';

  return (
    <SideSheet
      open={isBatchDrawerOpen}
      onClose={close}
      icon={<Layers size={15} />}
      title="批量管理"
      subtitle={`已选 ${selectedCount} · 当前条件命中 ${filtered.length} / ${sessions.length} 个会话 · ${formatBytes(totalBytes)}`}
      width="max-w-5xl"
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
            迁移产物写入目标平台原生存储目录；删除会连同子代理会话一并清理，不可撤销。
          </p>
        </div>
      }
    >
      <div className="p-4 space-y-3">
        {/* 多维度筛选矩阵 */}
        <div className="rounded-lg border border-line bg-surface-muted p-3">
          <div className="flex items-center gap-1.5 mb-2.5 text-[11.5px] text-ink-muted">
            <Filter size={11} />
            筛选条件
            <button
              onClick={() => setF({ ...emptyFilters })}
              className="ml-auto inline-flex items-center gap-1 text-[11px] text-accent-ink hover:underline"
            >
              <RotateCcw size={10} />
              重置筛选
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <label className="space-y-1">
              <span className="text-[10.5px] text-ink-faint">智能体平台</span>
              <select
                value={f.format}
                onChange={(e) => setF({ ...f, format: e.target.value })}
                className={`${inputCls} w-full`}
              >
                <option value="all">全部平台</option>
                {Array.from(new Set(sessions.map((s) => s.format))).map((fmt) => (
                  <option key={fmt} value={fmt}>
                    {platformMeta(fmt).label}
                  </option>
                ))}
              </select>
            </label>

            <div className="space-y-1">
              <span className="text-[10.5px] text-ink-faint">存储大小</span>
              <div className="flex items-center gap-1">
                <input
                  value={f.minSize}
                  onChange={(e) => setF({ ...f, minSize: e.target.value })}
                  placeholder="最小"
                  className={`${inputCls} w-full min-w-0`}
                />
                <span className="text-ink-faint text-[11px]">~</span>
                <input
                  value={f.maxSize}
                  onChange={(e) => setF({ ...f, maxSize: e.target.value })}
                  placeholder="最大"
                  className={`${inputCls} w-full min-w-0`}
                />
                <select
                  value={f.sizeUnit}
                  onChange={(e) => setF({ ...f, sizeUnit: e.target.value as any })}
                  className="h-8 px-1 rounded-md border border-line bg-surface text-[11.5px] text-ink-soft"
                >
                  <option value="MB">MB</option>
                  <option value="KB">KB</option>
                  <option value="B">B</option>
                </select>
              </div>
            </div>

            <div className="space-y-1">
              <span className="text-[10.5px] text-ink-faint">对话步数</span>
              <div className="flex items-center gap-1">
                <input
                  value={f.minSteps}
                  onChange={(e) => setF({ ...f, minSteps: e.target.value })}
                  placeholder="最少"
                  className={`${inputCls} w-full min-w-0`}
                />
                <span className="text-ink-faint text-[11px]">~</span>
                <input
                  value={f.maxSteps}
                  onChange={(e) => setF({ ...f, maxSteps: e.target.value })}
                  placeholder="最多"
                  className={`${inputCls} w-full min-w-0`}
                />
                <span className="text-ink-faint text-[11px]">步</span>
              </div>
            </div>

            <div className="space-y-1">
              <span className="text-[10.5px] text-ink-faint">最后活跃</span>
              <div className="flex items-center gap-1">
                <select
                  value={f.timeType}
                  onChange={(e) => setF({ ...f, timeType: e.target.value as TimeType })}
                  className={`${inputCls} flex-1 min-w-0`}
                >
                  {TIME_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {f.timeType === 'days_before' || f.timeType === 'days_within' ? (
                  <input
                    value={f.days}
                    onChange={(e) => setF({ ...f, days: e.target.value })}
                    placeholder="天数"
                    className={`${inputCls} w-16`}
                  />
                ) : f.timeType === 'date_before' || f.timeType === 'date_after' ? (
                  <input
                    type="date"
                    value={f.date}
                    onChange={(e) => setF({ ...f, date: e.target.value })}
                    className={`${inputCls} w-[124px]`}
                  />
                ) : null}
              </div>
            </div>
          </div>
        </div>

        {/* 结果表 */}
        <div className="rounded-lg border border-line overflow-hidden">
          <div className="max-h-[46vh] overflow-y-auto">
            <table className="w-full text-[12px]">
              <thead className="sticky top-0 z-10 bg-surface-muted border-b border-line">
                <tr className="text-left text-[10.5px] text-ink-faint">
                  <th className="w-9 px-2 py-1.5">
                    <button
                      onClick={() =>
                        allVisibleSelected
                          ? clearSelectedSessions()
                          : selectAllSessions(Array.from(new Set([...selectedCatalogIds, ...visibleIds])))
                      }
                      title={allVisibleSelected ? '取消全选' : '全选当前筛选结果'}
                      className="inline-flex"
                    >
                      {allVisibleSelected ? <CheckSquare size={13} /> : <Square size={13} />}
                    </button>
                  </th>
                  <th className="w-24 px-2 py-1.5">平台</th>
                  <th className="px-2 py-1.5">会话标题</th>
                  <th className="w-16 px-2 py-1.5 text-right">步数</th>
                  <th className="w-20 px-2 py-1.5 text-right">大小</th>
                  <th className="w-20 px-2 py-1.5">存储形态</th>
                  <th className="w-28 px-2 py-1.5">最后活跃</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-[12px] text-ink-muted">
                      没有符合当前条件的会话，试试放宽筛选
                    </td>
                  </tr>
                )}
                {filtered.map((s) => {
                  const meta = platformMeta(s.format);
                  const checked = selectedCatalogIds.includes(s.catalogId);
                  return (
                    <tr
                      key={s.catalogId}
                      onClick={() => toggleSelectSession(s.catalogId)}
                      className={`border-b border-line/60 cursor-pointer transition-colors ${
                        checked ? 'bg-accent-soft/60' : 'hover:bg-surface-muted'
                      }`}
                    >
                      <td className="px-2 py-1.5">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleSelectSession(s.catalogId)}
                          onClick={(e) => e.stopPropagation()}
                          className="accent-[#1f6feb]"
                        />
                      </td>
                      <td className="px-2 py-1.5">
                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                          <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{ backgroundColor: meta.color }}
                          />
                          <span className="text-ink-soft">{meta.label}</span>
                        </span>
                      </td>
                      <td className="px-2 py-1.5">
                        <span className="text-ink truncate inline-block max-w-[26rem]" title={s.title}>
                          {stripDatePrefix(s.title)}
                        </span>
                        {s.childrenCount > 0 && (
                          <span className="ml-1.5 px-1 rounded bg-surface-sunken border border-line text-[9.5px] text-ink-muted">
                            +{s.childrenCount} 子会话
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5 text-right tnum text-ink-muted">{s.records}</td>
                      <td className="px-2 py-1.5 text-right tnum text-ink-muted">
                        {formatBytes(s.bytes)}
                      </td>
                      <td className="px-2 py-1.5 text-ink-muted whitespace-nowrap">
                        {storageShape(s)}
                      </td>
                      <td className="px-2 py-1.5 tnum text-ink-muted whitespace-nowrap">
                        {formatDateTime(s.mtime ? s.mtime * 1000 : s.startedAt)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex items-center justify-between text-[11.5px] text-ink-muted">
          <span>
            命中 <strong className="text-ink">{filtered.length}</strong> 条 · 已选{' '}
            <strong className="text-accent-ink">{selectedCount}</strong> 条
          </span>
          {selectedCount > 0 && (
            <button onClick={clearSelectedSessions} className="hover:text-danger">
              清空选择
            </button>
          )}
        </div>
      </div>
    </SideSheet>
  );
}
