export interface PlatformMeta {
  label: string;
  short: string;
  color: string;
}

const MAP: Record<string, PlatformMeta> = {
  antigravity: { label: 'Antigravity', short: 'AG', color: '#6d5efc' },
  claude: { label: 'Claude Code', short: 'CC', color: '#c2710c' },
  workbuddy: { label: 'WorkBuddy', short: 'WB', color: '#0f9d58' },
  trae: { label: 'Trae', short: 'TR', color: '#7c3aed' },
  cursor: { label: 'Cursor', short: 'CU', color: '#0891b2' },
  copilot: { label: 'GitHub Copilot', short: 'CP', color: '#475569' },
  codex: { label: 'Codex', short: 'CX', color: '#0f766e' },
  kimi: { label: 'Kimi', short: 'KM', color: '#2563eb' },
};

export function platformMeta(format?: string): PlatformMeta {
  const key = (format || '').toLowerCase();
  return MAP[key] || { label: (format || '未知').toUpperCase(), short: '--', color: '#64748b' };
}

/** 迁移目标平台的中文说明，覆盖后端 supported_targets 的全部取值 */
const TARGET_HINT: Record<string, string> = {
  antigravity: 'Antigravity 原生会话库',
  claude: 'Claude Code CLI 历史',
  workbuddy: 'WorkBuddy 会话文件',
  cursor: 'Cursor 工作区会话库',
  trae: 'Trae 工程记忆文件',
  copilot: 'GitHub Copilot 会话',
  codex: 'OpenAI Codex 会话',
  kimi: 'Kimi 会话文件',
  qwen: '通义 Qwen 会话',
  grok: 'Grok 会话',
  vibe: 'Vibe 会话',
  muse: 'Muse 会话',
  pi: 'Pi 会话',
  omp: 'OMP 会话',
  opencode: 'OpenCode 会话',
  kilo: 'Kilo 会话',
  openhands: 'OpenHands 会话',
  hermes: 'Hermes 会话',
  mastracode: 'Mastra Code 会话',
  devin: 'Devin 会话',
};

export function targetHint(target: string): string {
  return TARGET_HINT[target] || `${target} 会话格式`;
}
