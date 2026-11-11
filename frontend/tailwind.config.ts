import type { Config } from 'tailwindcss';

/** 颜色统一走 CSS 变量（RGB 三元组），从而支持明/暗双主题 */
const v = (name: string) => `rgb(var(--${name}-rgb) / <alpha-value>)`;

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}', './app/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        canvas: v('canvas'),
        surface: {
          DEFAULT: v('surface'),
          muted: v('surface-muted'),
          sunken: v('surface-sunken'),
        },
        line: {
          DEFAULT: v('line'),
          strong: v('line-strong'),
        },
        ink: {
          DEFAULT: v('ink'),
          soft: v('ink-soft'),
          muted: v('ink-muted'),
          faint: v('ink-faint'),
        },
        accent: {
          DEFAULT: v('accent'),
          ink: v('accent-ink'),
          soft: v('accent-soft'),
        },
        danger: {
          DEFAULT: v('danger'),
          soft: v('danger-soft'),
        },
        ok: {
          DEFAULT: v('ok'),
          soft: v('ok-soft'),
        },
        warn: {
          DEFAULT: v('warn'),
          soft: v('warn-soft'),
        },
        scrim: v('scrim'),
        // 平台标识色：跨主题保持恒定，用于识别来源
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
        card: '0 1px 2px rgba(15, 18, 23, 0.05)',
        lift: '0 6px 20px rgba(15, 18, 23, 0.10)',
        panel: '0 20px 52px rgba(15, 18, 23, 0.20)',
      },
      maxWidth: {
        shell: '1440px',
      },
    },
  },
  plugins: [],
};

export default config;
