import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // 全量扫描 348 篇会话约需 30s，Next 代理默认 30s 会主动断开并抛 500，这里放宽到 3 分钟
  experimental: {
    proxyTimeout: 180_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:18922/api/:path*',
      },
    ];
  },
};

export default nextConfig;
