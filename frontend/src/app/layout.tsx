import type { Metadata } from 'next';
import './globals.css';
import { Toaster } from 'sonner';

export const metadata: Metadata = {
  title: 'Agents Memory Tools · 会话记忆工作台',
  description: '全平台智能体会话记忆管理、层级溯源与一键互迁工作台',
};

/** 首屏前同步主题，避免刷新时先亮后暗的闪烁 */
const themeBootstrap = `(function(){try{var t=localStorage.getItem('amt-theme');if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme='light';}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className="min-h-screen bg-canvas text-ink antialiased">
        {children}
        <Toaster
          position="bottom-right"
          theme="system"
          toastOptions={{
            style: {
              background: 'rgb(var(--surface-rgb))',
              border: '1px solid rgb(var(--line-rgb))',
              color: 'rgb(var(--ink-rgb))',
              boxShadow: '0 8px 28px rgba(15,18,23,0.16)',
              fontSize: '13px',
            },
          }}
        />
      </body>
    </html>
  );
}
