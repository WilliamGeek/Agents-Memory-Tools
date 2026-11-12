/** 工具调用的中文标签与图标，用于「行动」轨道的可读摘要 */
export interface ToolMeta {
  icon: string;
  label: string;
}

/**
 * 精确名映射（按小写匹配）。
 *
 * 覆盖全库实测出现的 108 个工具名中需要单独定性的那些：
 * 优先级高于下面的正则规则，避免 `Task`（子代理）被 `task*`（任务管理）误伤。
 */
const EXACT_LABELS: Record<string, ToolMeta> = {
  // 终端与执行
  run_command: { icon: '💻', label: '终端命令' },
  bash: { icon: '💻', label: '终端命令' },
  powershell: { icon: '💻', label: '终端命令' },
  remote_exec: { icon: '🖥️', label: '远程执行' },
  remote_check_connection: { icon: '🖥️', label: '远程连接检查' },
  remote_system_info: { icon: '🖥️', label: '远程系统信息' },
  execute_blender_code: { icon: '🧊', label: 'Blender 脚本' },
  ping: { icon: '📡', label: '连通性探测' },

  // 文件
  view_file: { icon: '📖', label: '查阅文件' },
  read_file: { icon: '📖', label: '查阅文件' },
  read: { icon: '📖', label: '查阅文件' },
  read_me: { icon: '📖', label: '读取说明' },
  use_file: { icon: '📎', label: '引用文件' },
  present_files: { icon: '📎', label: '展示文件' },
  viewimage: { icon: '🖼️', label: '查看图片' },
  write_file: { icon: '✍️', label: '写入文件' },
  write_to_file: { icon: '✍️', label: '写入文件' },
  write: { icon: '✍️', label: '写入文件' },
  edit: { icon: '✍️', label: '写入文件' },
  edit_file: { icon: '✍️', label: '写入文件' },
  replace_file_content: { icon: '✍️', label: '写入文件' },
  multi_replace_file_content: { icon: '✍️', label: '写入文件' },
  save_screenshots: { icon: '🖼️', label: '保存截图' },
  get_screenshot: { icon: '🖼️', label: '截取画面' },
  generate_image: { icon: '🎨', label: '生成图片' },

  // 检索
  list_dir: { icon: '🔍', label: '目录浏览' },
  list_files: { icon: '🔍', label: '目录浏览' },
  grep_search: { icon: '🔍', label: '检索定位' },
  find_by_name: { icon: '🔍', label: '按名检索' },
  search_web: { icon: '🔎', label: '联网搜索' },
  read_url_content: { icon: '🌐', label: '网页抓取' },

  // 任务与子代理
  manage_task: { icon: '🗂️', label: '任务管理' },
  taskcreate: { icon: '🗂️', label: '任务管理' },
  taskupdate: { icon: '🗂️', label: '任务管理' },
  taskget: { icon: '🗂️', label: '任务管理' },
  tasklist: { icon: '🗂️', label: '任务管理' },
  taskoutput: { icon: '🗂️', label: '任务管理' },
  taskstop: { icon: '🗂️', label: '任务管理' },
  task: { icon: '🤖', label: '子代理' },
  agent: { icon: '🤖', label: '子代理' },
  invoke_subagent: { icon: '🤖', label: '子代理' },
  manage_subagents: { icon: '🤖', label: '子代理' },
  define_subagent: { icon: '🤖', label: '子代理' },
  browser_subagent: { icon: '🌐', label: '浏览器子代理' },

  // 交互
  ask_question: { icon: '❓', label: '交互确认' },
  askuserquestion: { icon: '❓', label: '交互确认' },
  send_message: { icon: '✉️', label: '消息通信' },
  sendmessage: { icon: '✉️', label: '消息通信' },
  schedule: { icon: '⏰', label: '定时任务' },
  automation_update: { icon: '⏰', label: '定时任务' },

  // 技能 / MCP / 组件
  skill: { icon: '🧠', label: '技能调用' },
  call_mcp_tool: { icon: '🧩', label: 'MCP 工具' },
  deferexecutetool: { icon: '🧩', label: 'MCP 工具' },
  toolsearch: { icon: '🧰', label: '工具检索' },
  list_plugin_accounts: { icon: '🧩', label: '插件账户' },
  get_addon_status: { icon: '🧩', label: '插件状态' },
  get_scene_info: { icon: '🧩', label: '场景信息' },
  get_hunyuan3d_status: { icon: '🧩', label: '模型服务状态' },
  get_hyper3d_status: { icon: '🧩', label: '模型服务状态' },
  show_widget: { icon: '🧱', label: '交互组件' },
  widget_guidelines: { icon: '🧱', label: '组件规范' },
  batch: { icon: '📚', label: '批量调用' },
  generic: { icon: '🔧', label: '工具调用' },
};

/** 兜底正则：命中未知的新工具名时也能落到合适的中文分类 */
const RULES: { match: RegExp; meta: ToolMeta }[] = [
  { match: /^mcp_chrome_devtools|^chrome_devtools/i, meta: { icon: '🌐', label: '浏览器自动化' } },
  { match: /^(browser|playwright)/i, meta: { icon: '🌐', label: '浏览器自动化' } },
  { match: /^(mcp_|call_mcp|defer)/i, meta: { icon: '🧩', label: 'MCP 工具' } },
  { match: /^remote_/i, meta: { icon: '🖥️', label: '远程执行' } },
  { match: /blender/i, meta: { icon: '🧊', label: 'Blender 脚本' } },
  { match: /^(skill)/i, meta: { icon: '🧠', label: '技能调用' } },
  { match: /(subagent|delegate)/i, meta: { icon: '🤖', label: '子代理' } },
  { match: /^(task|todo)/i, meta: { icon: '🗂️', label: '任务管理' } },
  { match: /^(ask_question|askuserquestion)/i, meta: { icon: '❓', label: '交互确认' } },
  { match: /^(send_message|sendmessage|ping)/i, meta: { icon: '✉️', label: '消息通信' } },
  { match: /^(search_web|websearch|search_marketplace)/i, meta: { icon: '🔎', label: '联网搜索' } },
  { match: /^(webfetch|read_url_content|fetch|http|curl)/i, meta: { icon: '🌐', label: '网页抓取' } },
  { match: /^(run_command|bash|powershell|shell|terminal|exec|execute|cmd|command)/i, meta: { icon: '💻', label: '终端命令' } },
  { match: /^(read|view|cat|open|use_file|present)/i, meta: { icon: '📖', label: '查阅文件' } },
  { match: /^(write|create_file|edit|apply_patch|str_replace|multi_edit|multi_replace|replace_file_content|notebook_edit)/i, meta: { icon: '✍️', label: '写入文件' } },
  { match: /^(grep|search|find|glob|list_dir|list_files|ls$|codebase_search|file_search)/i, meta: { icon: '🔍', label: '检索定位' } },
  { match: /^(show_widget|widget)/i, meta: { icon: '🧱', label: '交互组件' } },
  { match: /^(generate_image|viewimage|screenshot|save_screenshots|image)/i, meta: { icon: '🖼️', label: '图像处理' } },
  { match: /^(set_|create_frame|create_text|create_variable|get_node|get_nodes|get_selection|get_variable|delete_nodes|rename_node|update_variable|get_reactions|get_viewport|get_document|get_pages)/i, meta: { icon: '🎨', label: '设计操作' } },
  { match: /^(schedule|automation)/i, meta: { icon: '⏰', label: '定时任务' } },
  { match: /^batch/i, meta: { icon: '📚', label: '批量调用' } },
];

export function toolMeta(name: string): ToolMeta {
  const n = (name || '').trim();
  const exact = EXACT_LABELS[n.toLowerCase()];
  if (exact) return exact;
  for (const r of RULES) {
    if (r.match.test(n)) return r.meta;
  }
  return { icon: '🔧', label: '工具调用' };
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
