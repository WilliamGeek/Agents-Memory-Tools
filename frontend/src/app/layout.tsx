import type { Metadata } from 'next';
import './globals.css';
import { Toaster } from 'sonner';

export const metadata: Metadata = {
  title: 'Agents Memory Tools · 会话记忆工作台',
  description: '全平台智能体会话记忆管理、层级溯源与一键互迁工作台',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-canvas text-ink antialiased">
        {children}
        <Toaster
          position="bottom-right"
          theme="light"
          toastOptions={{
            style: {
              background: '#ffffff',
              border: '1px solid #e4e7ec',
              color: '#171c22',
              boxShadow: '0 8px 28px rgba(23,28,34,0.12)',
              fontSize: '13px',
            },
          }}
        />
      </body>
    </html>
  );
}
