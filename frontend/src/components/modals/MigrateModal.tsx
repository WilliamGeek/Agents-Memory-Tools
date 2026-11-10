'use client';

import React, { useEffect, useState } from 'react';
import { ArrowRightLeft, Loader2, Check } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { toast } from 'sonner';
import { ModalShell } from '../ui/Overlay';
import { platformMeta, targetHint } from '../../lib/platform';
import { formatBytes } from '../../lib/format';

const FALLBACK = ['claude', 'antigravity', 'workbuddy', 'cursor', 'trae', 'copilot'];

export function MigrateModal() {
  const { activeMigrateSession, setActiveMigrateSession } = useStore();
  const [targets, setTargets] = useState<string[]>(FALLBACK);
  const [target, setTarget] = useState('claude');
  const [busy, setBusy] = useState(false);

  const session = activeMigrateSession;

  useEffect(() => {
    if (!session) return;
    api
      .getStatus()
      .then((s) => {
        if (s.supportedTargets.length) setTargets(s.supportedTargets);
        if (session.format && s.supportedTargets.includes(session.format) === false) {
          // 保留默认目标，不做额外处理
        }
      })
      .catch(() => {});
  }, [session]);

  const run = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const res = await api.migrateSession(session.catalogId, target);
      toast.success(res.message || '迁移完成', { duration: 5000 });
      if (res.outputPath) {
        // 迁移产物落在目标平台的真实存储目录，提示具体位置便于核对
        console.info('[migrate] output:', res.outputPath);
      }
      setActiveMigrateSession(null);
    } catch (e: any) {
      toast.error(`迁移失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      open={Boolean(session)}
      onClose={() => setActiveMigrateSession(null)}
      width="max-w-xl"
      icon={<ArrowRightLeft size={15} />}
      title="跨平台会话迁移"
      subtitle={session ? session.title : undefined}
      footer={
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11.5px] text-ink-muted">
            产物写入目标平台的原生存储目录（可直接被该平台识别），原会话不做改动
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveMigrateSession(null)}
              className="h-8 px-3 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft hover:bg-surface-sunken transition-colors"
            >
              取消
            </button>
            <button
              onClick={run}
              disabled={busy || !session}
              className="h-8 px-3 rounded-md bg-accent text-white text-[12.5px] font-medium inline-flex items-center gap-1.5 hover:bg-accent-ink disabled:opacity-60 transition-colors"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <ArrowRightLeft size={13} />}
              {busy ? '迁移中' : '开始迁移'}
            </button>
          </div>
        </div>
      }
    >
      {session && (
        <div className="p-4 space-y-4">
          <div className="rounded-lg border border-line bg-surface-muted px-3 py-2.5">
            <div className="flex items-center gap-2 text-[11px] text-ink-muted">
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: platformMeta(session.format).color }}
              />
              {platformMeta(session.format).label}
              <span className="text-line-strong">|</span>
              <span className="tnum">{session.records} 步</span>
              <span className="text-line-strong">|</span>
              <span className="tnum">{formatBytes(session.bytes)}</span>
            </div>
            <p className="text-[13px] text-ink mt-1 line-clamp-2" title={session.title}>
              {session.title}
            </p>
          </div>

          <div>
            <p className="text-[11.5px] text-ink-muted mb-2">选择目标平台</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {targets.map((t) => {
                const active = target === t;
                const meta = platformMeta(t);
                return (
                  <button
                    key={t}
                    onClick={() => setTarget(t)}
                    className={`relative text-left rounded-lg border px-3 py-2 transition-colors ${
                      active
                        ? 'border-accent bg-accent-soft'
                        : 'border-line bg-surface hover:border-line-strong'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ backgroundColor: meta.color }}
                      />
                      <span
                        className={`text-[12.5px] font-medium ${
                          active ? 'text-accent-ink' : 'text-ink'
                        }`}
                      >
                        {meta.label}
                      </span>
                      {active && <Check size={11} className="ml-auto text-accent" />}
                    </div>
                    <p className="text-[10.5px] text-ink-muted mt-0.5 line-clamp-1">
                      {targetHint(t)}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </ModalShell>
  );
}
