'use client';

import React from 'react';
import { Search, FolderCog, Layers, RefreshCw, BrainCircuit } from 'lucide-react';
import { useStore } from '../../store/useStore';
import { api } from '../../api/client';
import { toast } from 'sonner';

const ghostBtn =
  'h-8 px-2.5 rounded-md border border-line bg-surface text-[12.5px] text-ink-soft ' +
  'hover:bg-surface-sunken hover:text-ink transition-colors inline-flex items-center gap-1.5';

export function Header({ onRefresh }: { onRefresh?: () => void }) {
  const {
    setIsGlobalSearchOpen,
    setIsRootsModalOpen,
    setIsBatchDrawerOpen,
    selectedCatalogIds,
    isScanning,
    setIsScanning,
  } = useStore();

  const handleRefresh = async () => {
    if (isScanning) return;
    setIsScanning(true);
    try {
      const res = await api.refreshCatalog();
      toast.success(
        `扫描完成：发现 ${res.files_seen ?? 0} 个文件，更新 ${res.scanned ?? 0} 个`
      );
      onRefresh?.();
    } catch (e: any) {
      toast.error(`刷新失败：${e.message}`);
    } finally {
      setIsScanning(false);
    }
  };

  return (
    <header className="sticky top-0 z-30 h-14 bg-surface/95 backdrop-blur border-b border-line">
      <div className="h-full max-w-shell mx-auto px-4 md:px-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-8 h-8 rounded-lg bg-accent text-white flex items-center justify-center shrink-0">
            <BrainCircuit size={17} />
          </span>
          <div className="min-w-0">
            <div className="text-[14.5px] font-semibold text-ink leading-tight truncate">
              Agents Memory Tools
            </div>
            <div className="text-[11px] text-ink-faint leading-tight hidden sm:block">
              跨智能体会话记忆工作台
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsGlobalSearchOpen(true)}
            className={ghostBtn}
            title="跨会话对话内容全文检索（Ctrl+Shift+F）"
          >
            <Search size={13} className="text-ink-muted" />
            <span className="hidden sm:inline">全文检索</span>
            <kbd className="hidden md:inline-block ml-0.5 px-1.5 py-0.5 rounded border border-line bg-surface-sunken text-[10px] text-ink-faint">
              Ctrl+Shift+F
            </kbd>
          </button>

          <button
            onClick={() => setIsRootsModalOpen(true)}
            className={ghostBtn}
            title="管理会话扫描根目录"
          >
            <FolderCog size={13} className="text-ink-muted" />
            <span className="hidden sm:inline">扫描目录</span>
          </button>

          <button
            onClick={() => setIsBatchDrawerOpen(true)}
            className={ghostBtn}
            title="批量选择、迁移或删除会话"
          >
            <Layers size={13} className="text-ink-muted" />
            <span className="hidden sm:inline">批量管理</span>
            {selectedCatalogIds.length > 0 && (
              <span className="ml-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-white text-[10px] font-semibold inline-flex items-center justify-center tnum">
                {selectedCatalogIds.length}
              </span>
            )}
          </button>

          <button
            onClick={handleRefresh}
            disabled={isScanning}
            className="h-8 px-3 rounded-md bg-accent text-white text-[12.5px] font-medium inline-flex items-center gap-1.5 hover:bg-accent-ink disabled:opacity-60 transition-colors shadow-sm"
            title="重新扫描并刷新全平台会话数据"
          >
            <RefreshCw size={13} className={isScanning ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">{isScanning ? '扫描中' : '刷新数据'}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
