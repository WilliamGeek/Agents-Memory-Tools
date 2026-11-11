'use client';

import React, { useEffect, useState } from 'react';
import { Moon, Sun } from 'lucide-react';

type Theme = 'light' | 'dark';

/** 主题切换：写入 localStorage 与 <html data-theme>，首屏由 layout 内联脚本预置避免闪烁 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('light');

  useEffect(() => {
    const current = (document.documentElement.dataset.theme as Theme) || 'light';
    setTheme(current);
  }, []);

  const toggle = () => {
    const next: Theme = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('amt-theme', next);
    } catch {
      /* 隐私模式下忽略 */
    }
  };

  return (
    <button
      onClick={toggle}
      className="h-8 w-8 rounded-md border border-line bg-surface text-ink-muted inline-flex items-center justify-center hover:text-ink hover:bg-surface-sunken transition-colors"
      title={theme === 'light' ? '切换到暗色主题' : '切换到浅色主题'}
      aria-label="切换主题"
    >
      {theme === 'light' ? <Moon size={14} /> : <Sun size={14} />}
    </button>
  );
}
