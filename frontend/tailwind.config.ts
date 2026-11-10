import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}', './app/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#f4f5f7',
        surface: {
          DEFAULT: '#ffffff',
          muted: '#fafbfc',
          sunken: '#f1f3f6',
        },
        line: {
          DEFAULT: '#e4e7ec',
          strong: '#d3d9e2',
        },
        ink: {
          DEFAULT: '#171c22',
          soft: '#3d4753',
          muted: '#6b7683',
          faint: '#98a2b0',
        },
        accent: {
          DEFAULT: '#1f6feb',
          ink: '#1052c4',
          soft: '#eef4ff',
        },
        danger: {
          DEFAULT: '#cf222e',
          soft: '#fff1f0',
        },
        ok: {
          DEFAULT: '#1a7f37',
          soft: '#eefaf1',
        },
        warn: {
          DEFAULT: '#9a6700',
          soft: '#fff8e6',
        },
        agent: {
          antigravity: '#6d5efc',
          claude: '#c2710c',
          workbuddy: '#0f9d58',
          trae: '#7c3aed',
          cursor: '#0891b2',
          copilot: '#475569',
          codex: '#0f766e',
          default: '#64748b',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          '"PingFang SC"',
          '"Microsoft YaHei"',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', '"JetBrains Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        card: '12px',
        panel: '14px',
        sm: '6px',
        md: '8px',
        lg: '10px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(23, 28, 34, 0.04)',
        lift: '0 4px 16px rgba(23, 28, 34, 0.08)',
        panel: '0 18px 48px rgba(23, 28, 34, 0.12)',
      },
      maxWidth: {
        shell: '1440px',
      },
    },
  },
  plugins: [],
};

export default config;
