'use client';

import React, { useEffect, useState } from 'react';
import { FolderCog, FolderPlus, Trash2, AlertCircle, CheckCircle2, Plus } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { AppStatus } from '../../types/session';
import { toast } from 'sonner';
import { ModalShell } from '../ui/Overlay';
import { platformMeta } from '../../lib/platform';

const ADDABLE = [
  'antigravity',
  'claude',
  'workbuddy',
  'trae',
  'cursor',
  'copilot',
  'codex',
  'kimi',
];

export function RootsModal({ onRootsChanged }: { onRootsChanged?: () => void }) {
  const { isRootsModalOpen, setIsRootsModalOpen } = useStore();
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [format, setFormat] = useState('workbuddy');
  const [path, setPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const close = () => setIsRootsModalOpen(false);

  // 后端在扫描/索引进行中偶发 500，先重试一次再报错，避免弹窗停在「加载中」
  const load = async (retry = true) => {
    try {
      setStatus(await api.getStatus());
    } catch (e: any) {
      if (retry) {
        await new Promise((r) => setTimeout(r, 700));
        return load(false);
      }
      setError(e.message || '读取失败');
      toast.error(`读取目录失败：${e.message}`);
    }
  };

  useEffect(() => {
    if (!isRootsModalOpen) return;
    setError('');
    load();
  }, [isRootsModalOpen]);

  const add = async () => {
    const p = path.trim();
    if (!p) {
      toast.error('请填写要扫描的目录路径');
      return;
    }
    setBusy(true);
    try {
      await api.addRoot(format, p);
      toast.success('目录已登记');
      setPath('');
      load();
      onRootsChanged?.();
    } catch (e: any) {
      toast.error(`登记失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number, p: string) => {
    if (!window.confirm(`确认移除该扫描目录？\n\n${p}\n\n仅从索引中移除，不会删除原始会话文件。`))
      return;
    try {
      await api.removeRoot(id);
      toast.success('已移除');
      load();
      onRootsChanged?.();
    } catch (e: any) {
      toast.error(`移除失败：${e.message}`);
    }
  };

  const roots = status?.roots || [];

  return (
    <ModalShell
      open={isRootsModalOpen}
      onClose={close}
      width="max-w-2xl"
      icon={<FolderCog size={15} />}
      title="扫描目录管理"
      subtitle={
        status
          ? `当前收录 ${status.totalSessions} 篇会话，导出目录：${status.exportDir || 'exports'}`
          : error || '加载中…'
      }
      footer={
        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="h-9 px-2.5 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft"
          >
            {ADDABLE.map((f) => (
              <option key={f} value={f}>
                {platformMeta(f).label}
              </option>
            ))}
          </select>
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && add()}
            placeholder="例如 C:\\Users\\HP\\.workbuddy\\projects"
            className="flex-1 h-9 px-3 rounded-md border border-line bg-surface-muted text-[12.5px] text-ink placeholder:text-ink-faint focus:bg-surface"
          />
          <button
            onClick={add}
            disabled={busy}
            className="h-9 px-3 rounded-md bg-accent text-white text-[12.5px] font-medium inline-flex items-center gap-1.5 hover:bg-accent-ink disabled:opacity-60 transition-colors"
          >
            <Plus size={13} />
            登记目录
          </button>
        </div>
      }
    >
      <div className="p-4 space-y-2">
        {roots.length === 0 && (
          <div className="py-14 text-center text-[12.5px] text-ink-muted">
            <FolderPlus size={22} className="mx-auto text-ink-faint mb-2" />
            还没有登记任何扫描目录
          </div>
        )}

        {roots.map((r) => {
          const meta = platformMeta(r.format);
          const ok = r.lastScanStatus === 'ok';
          return (
            <div
              key={`${r.format}-${r.path}`}
              className="rounded-lg border border-line bg-surface px-3 py-2.5 flex items-start gap-3"
            >
              <span
                className="mt-1 w-1.5 h-1.5 rounded-full shrink-0"
                style={{ backgroundColor: meta.color }}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium text-ink">{meta.label}</span>
                  <span
                    className={`inline-flex items-center gap-1 text-[10.5px] ${
                      ok ? 'text-ok' : 'text-warn'
                    }`}
                    title={r.lastError || ''}
                  >
                    {ok ? <CheckCircle2 size={10} /> : <AlertCircle size={10} />}
                    {ok ? '扫描正常' : r.lastScanStatus || '未扫描'}
                  </span>
                </div>
                <p className="text-[11.5px] text-ink-muted font-mono break-all mt-0.5">
                  {r.path}
                </p>
              </div>
              <button
                onClick={() => remove(r.id, r.path)}
                className="p-1.5 rounded text-ink-faint hover:text-danger hover:bg-danger-soft transition-colors"
                title="移除该目录"
              >
                <Trash2 size={13} />
              </button>
            </div>
          );
        })}
      </div>
    </ModalShell>
  );
}
