'use client';

import React, { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

/**
 * 统一的浮层行为：Esc 关闭、点遮罩关闭、打开时锁滚动、焦点移入。
 * 上一版的抽屉按 Esc 无反应、遮罩继续吞点击，就是因为每个组件各写一套且都没写全。
 */
export function useLayer(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);
}

function Backdrop({
  onClose,
  children,
  className,
}: {
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`fixed inset-0 z-50 bg-scrim/45 backdrop-blur-[2px] anim-fade ${className || ''}`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {children}
    </div>
  );
}

export function ModalShell({
  open,
  onClose,
  title,
  subtitle,
  icon,
  actions,
  footer,
  width = 'max-w-2xl',
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
  children: React.ReactNode;
}) {
  useLayer(open, onClose);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) boxRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <Backdrop onClose={onClose} className="flex items-center justify-center p-3 sm:p-6">
      <div
        ref={boxRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        className={`w-full ${width} max-h-[90vh] bg-surface rounded-panel shadow-panel border border-line flex flex-col overflow-hidden anim-up outline-none`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-3.5 border-b border-line flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-start gap-2.5 min-w-0">
            {icon ? <span className="mt-0.5 text-accent shrink-0">{icon}</span> : null}
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-ink truncate">{title}</h2>
              {subtitle ? (
                <p className="text-xs text-ink-muted truncate mt-0.5">{subtitle}</p>
              ) : null}
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {actions}
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
              title="关闭 (Esc)"
              aria-label="关闭"
            >
              <X size={16} />
            </button>
          </div>
        </header>
        <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
        {footer ? (
          <footer className="px-5 py-3 border-t border-line bg-surface-muted shrink-0">{footer}</footer>
        ) : null}
      </div>
    </Backdrop>
  );
}

export function SideSheet({
  open,
  onClose,
  title,
  subtitle,
  icon,
  footer,
  width = 'max-w-md',
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
  children: React.ReactNode;
}) {
  useLayer(open, onClose);
  if (!open) return null;

  return (
    <Backdrop onClose={onClose} className="flex justify-end">
      <aside
        role="dialog"
        aria-modal="true"
        className={`w-full ${width} h-full bg-surface border-l border-line shadow-panel flex flex-col anim-left`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-3.5 border-b border-line flex items-start justify-between gap-3 shrink-0">
          <div className="flex items-start gap-2.5 min-w-0">
            {icon ? <span className="mt-0.5 text-accent shrink-0">{icon}</span> : null}
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-ink truncate">{title}</h2>
              {subtitle ? <p className="text-xs text-ink-muted mt-0.5">{subtitle}</p> : null}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-surface-sunken transition-colors"
            title="关闭 (Esc)"
            aria-label="关闭"
          >
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
        {footer ? (
          <footer className="px-5 py-3 border-t border-line bg-surface-muted shrink-0">{footer}</footer>
        ) : null}
      </aside>
    </Backdrop>
  );
}
