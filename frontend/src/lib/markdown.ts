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
  // 裸链接：避免匹配已生成的 href
  out = out.replace(
    /(^|[^"'=>])(https?:\/\/[^\s<"]+)/g,
    (m, pre, url) => `${pre}<a href="${url}" target="_blank" rel="noreferrer noopener">${url}</a>`
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
          `<pre data-lang="${escapeHtml(codeLang)}"><code>${markHits(escapeHtml(codeBuf.join('\n')), highlight)}</code></pre>`
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

    // GFM 表格：当前行含 |，下一行是分隔行 |---|
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
      closeList();
      const splitRow = (row: string): string[] => {
        let t = row.trim();
        if (t.startsWith('|')) t = t.slice(1);
        if (t.endsWith('|')) t = t.slice(0, -1);
        return t.split('|').map((c) => c.trim());
      };
      const head = splitRow(line);
      const aligns = splitRow(lines[i + 1]).map((c) => {
        const l = c.startsWith(':');
        const r = c.endsWith(':');
        if (l && r) return 'center';
        if (r) return 'right';
        if (l) return 'left';
        return '';
      });
      const alignAttr = (idx: number) => {
        const a = aligns[idx];
        return a ? ` style="text-align:${a}"` : '';
      };
      const body: string[][] = [];
      let j = i + 2;
      while (j < lines.length && lines[j].includes('|') && lines[j].trim()) {
        body.push(splitRow(lines[j]));
        j += 1;
      }
      const thead = head.map((c, idx) => `<th${alignAttr(idx)}>${inline(c, highlight)}</th>`).join('');
      const tbody = body
        .map(
          (r) =>
            `<tr>${r.map((c, idx) => `<td${alignAttr(idx)}>${inline(c, highlight)}</td>`).join('')}</tr>`
        )
        .join('');
      out.push(`<div class="md-table-wrap"><table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table></div>`);
      i = j;
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
