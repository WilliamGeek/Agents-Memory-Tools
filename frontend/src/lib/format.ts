/** 后端各类时间戳统一格式化为本地可读时间。支持毫秒字符串与 ISO8601。 */
export function parseTime(raw?: string | number | null): Date | null {
  if (raw === null || raw === undefined || raw === '') return null;
  if (typeof raw === 'number') {
    // 秒 / 毫秒兼容
    return new Date(raw > 1e11 ? raw : raw * 1000);
  }
  const s = String(raw).trim();
  if (!s) return null;
  if (/^\d+$/.test(s)) {
    const n = Number(s);
    return new Date(n > 1e11 ? n : n * 1000);
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** 2026-11-11 01:52 */
export function formatDateTime(raw?: string | number | null): string {
  const d = parseTime(raw);
  if (!d) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 01:52 */
export function formatClock(raw?: string | number | null): string {
  const d = parseTime(raw);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 2026-11-11 */
export function formatDate(raw?: string | number | null): string {
  const d = parseTime(raw);
  if (!d) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** 相对时间：刚刚 / 3 小时前 / 2 天前 / 2026-10-01 */
export function formatRelative(raw?: string | number | null): string {
  const d = parseTime(raw);
  if (!d) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return formatDate(raw);
}

export function formatBytes(bytes?: number | null): string {
  const b = Number(bytes) || 0;
  if (b >= 1024 ** 3) return `${(b / 1024 ** 3).toFixed(2)} GB`;
  if (b >= 1024 ** 2) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  if (b >= 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${b} B`;
}

export function formatTokens(tokens?: number | null): string {
  const t = Number(tokens) || 0;
  if (t >= 1e9) return `${(t / 1e9).toFixed(2)}B`;
  if (t >= 1e6) return `${(t / 1e6).toFixed(2)}M`;
  if (t >= 1e3) return `${(t / 1e3).toFixed(1)}K`;
  return String(t);
}

export function formatCount(n?: number | null): string {
  return (Number(n) || 0).toLocaleString('zh-CN');
}

/**
 * 后端标题形如「2026-11-11 · 查看项目Git历史版本」，日期在卡片头部已单独展示，
 * 这里剥掉前缀避免同一屏出现两次日期。
 */
export function stripDatePrefix(title?: string | null): string {
  const t = (title || '').trim();
  if (!t) return '';
  const stripped = t.replace(/^\d{4}-\d{2}-\d{2}\s*[·•・\-–]\s*/, '').trim();
  return stripped || t;
}
