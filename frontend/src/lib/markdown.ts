/**
 * 极简 Markdown 渲染器（零依赖）。
 * 安全策略：先转义 HTML，再只拼接自己生成的受控标签，不引入任何外部脚本或属性注入。
 */

const escapeHtml = (s: string): string =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

/** 把已转义文本中的命中词包成 <mark>，用于详情内搜索高亮 */
function markHits(escapedHtml: string, query?: string): string {
  if (!query) return escapedHtml;
  const needle = escapeHtml(query);
  if (!needle) return escapedHtml;
  const re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  return escapedHtml.replace(re, (m) => `<mark class="chat-hit">${m}</mark>`);
}

function inline(text: string, highlight?: string): string {
  let out = markHits(escapeHtml(text), highlight);
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  out = out.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
  out = out.replace(
    /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>'
  );
  return out;
}

export function renderMarkdown(source: string, highlight?: string): string {
  if (!source) return '';
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const out: string[] = [];
  let inCode = false;
  let codeLang = '';
  let codeBuf: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let i = 0;

  const closeList = () => {
    if (listType) {
      out.push(listType === 'ul' ? '</ul>' : '</ol>');
      listType = null;
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(/^\s*```(\w*)\s*$/);
    if (fence) {
      if (!inCode) {
        closeList();
        inCode = true;
        codeLang = fence[1] || '';
        codeBuf = [];
      } else {
        inCode = false;
        out.push(
          `<pre data-lang="${escapeHtml(codeLang)}"><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`
        );
      }
      i += 1;
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      i += 1;
      continue;
    }
    if (!line.trim()) {
      closeList();
      i += 1;
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 6);
      out.push(`<h${level}>${inline(heading[2], highlight)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      closeList();
      out.push('<hr/>');
      i += 1;
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      out.push(`<blockquote>${inline(quote[1], highlight)}</blockquote>`);
      i += 1;
      continue;
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      const want: 'ul' | 'ol' = ul ? 'ul' : 'ol';
      if (listType !== want) {
        closeList();
        out.push(want === 'ul' ? '<ul>' : '<ol>');
        listType = want;
      }
      out.push(`<li>${inline((ul || ol)![1], highlight)}</li>`);
      i += 1;
      continue;
    }

    closeList();
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^\s*[-*+]\s/.test(lines[i]) &&
      !/^\s*\d+[.)]\s/.test(lines[i]) &&
      !/^\s*>/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    out.push(`<p>${inline(para.join('\n'), highlight).replace(/\n/g, '<br/>')}</p>`);
  }

  closeList();
  if (inCode) out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`);
  return out.join('\n');
}
