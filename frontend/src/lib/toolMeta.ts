/** 工具调用的中文标签与图标，用于「行动」轨道的可读摘要 */
export interface ToolMeta {
  icon: string;
  label: string;
}

const RULES: { match: RegExp; meta: ToolMeta }[] = [
  { match: /^(run_command|bash|shell|terminal|exec|execute|cmd)/i, meta: { icon: '💻', label: '终端命令' } },
  { match: /^(read|view|open|cat|view_file|read_file)/i, meta: { icon: '📖', label: '查阅文件' } },
  { match: /^(write|create|edit|apply_patch|str_replace|multi_edit|notebook_edit)/i, meta: { icon: '✍️', label: '写入文件' } },
  { match: /^(grep|search|find|glob|list_dir|ls)/i, meta: { icon: '🔍', label: '检索定位' } },
  { match: /^(browser|web|fetch|http|curl|playwright)/i, meta: { icon: '🌐', label: '浏览器' } },
  { match: /^(task|agent|subagent|delegate)/i, meta: { icon: '🤖', label: '子代理' } },
  { match: /^(todo|plan|think|note)/i, meta: { icon: '📝', label: '记录计划' } },
];

export function toolMeta(name: string): ToolMeta {
  const n = (name || '').trim();
  for (const r of RULES) {
    if (r.match.test(n)) return r.meta;
  }
  return { icon: '🔧', label: n || '工具调用' };
}

/** 从工具入参里挑一个最能说明"在干什么"的字段 */
export function toolDetail(payload: any): string {
  const input = payload?.input ?? payload;
  if (!input) return '';
  if (typeof input === 'string') return firstLine(input);
  const keys = [
    'CommandLine',
    'command',
    'cmd',
    'TargetFile',
    'AbsolutePath',
    'file_path',
    'filePath',
    'path',
    'query',
    'pattern',
    'url',
  ];
  for (const k of keys) {
    const v = input[k];
    if (typeof v === 'string' && v.trim()) return firstLine(v);
  }
  try {
    return firstLine(JSON.stringify(input));
  } catch {
    return '';
  }
}

function firstLine(s: string, max = 90): string {
  const line = (s || '').split('\n').find((l) => l.trim()) || '';
  const t = line.trim();
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/** 行动轨道的汇总文案：💻 终端命令 ×7 · 📖 查阅文件 ×3 */
export function summarizeTools(names: string[]): string {
  const counter = new Map<string, { icon: string; count: number }>();
  for (const n of names) {
    const m = toolMeta(n);
    const cur = counter.get(m.label) || { icon: m.icon, count: 0 };
    cur.count += 1;
    counter.set(m.label, cur);
  }
  return Array.from(counter.entries())
    .map(([label, v]) => `${v.icon} ${label} ×${v.count}`)
    .join(' · ');
}
