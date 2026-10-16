/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · core.js（零构建原生 ESM）
 * 共享工具：esc / $id / toast / renderMarkdown / jget·jpost·jput·jdel
 * 全局状态 S、TOOL_ICON、psCard、friendlyToolArgs、_cssVar
 * 全局错误边界 + 响应式抽屉汉堡
 * ═══════════════════════════════════════════════════════════════ */

/* ── HTML 转义 ─────────────────────────────────────────── */
export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function $id(id) { return document.getElementById(id); }

/* ── toast 通知 ───────────────────────────────────────── */
export function toast(msg, type) {
  const box = $id('toast');
  if (!box) { console.warn('[toast]', msg); return; }
  const t = document.createElement('div');
  t.className = 'toast-item ' + (type || '');
  t.textContent = msg;
  t.onclick = () => t.remove();
  box.appendChild(t);
  setTimeout(() => t.remove(), 8000);
}

/* ── 全局状态（跨模块共享，对象引用，变异可见） ─────────── */
export const S = {
  session: null, kb: null, streaming: false, es: null,
  toolSeq: 0, toolNames: [], plan: null,
  attachments: [], execLog: [], curTurn: null, turnSeq: 0,
  execPanelOpen: false, memHinted: false,
};

/* ── 工具图标表 ───────────────────────────────────────── */
export const TOOL_ICON = {
  web_search: '🔍', web_search_merged: '🔍', browser_exec: '🌐', browser_navigate: '🌐',
  read_file: '📄', write_file: '✍️', patch: '🛠', terminal: '⌨️', execute_code: '🧮',
  web_fetch: '🔗', web_extract: '🔗', kb_search: '📚', pdf_extract: '📄', image_gen: '🎨',
  todo: '✅', memory: '🧠', delegate_task: '🤝', cronjob: '⏰', clarify: '❓',
  molar_mass: '⚖️', xrd_dspacing: '🔬', xrd_preprocess: '📊', tauc_bandgap: '🌈',
  thermo_gibbs: '🔥', solution_prep: '🧪', experiment_protocol: '📋', experiment_plot: '📈',
  chemical_safety: '⚠️', energy_convert: '🔄', lever_rule: '⚖️', citation_format: '📝',
  lab_notebook_template: '📓', data_normalize: '📏', matlens_kb: '📚', rag_search: '🔎',
  mem0_search: '🧠', mem0_add: '🧠', mem0_update: '✏️', mem0_delete: '🗑️',
};

export function toolCatColor(cat) {
  return ({ '材料计算': '#38bdf8', '实验辅助': '#34d399', '数据处理': '#a5b4fc', '写作': '#fbbf24', '知识库': '#f472b6' })[cat] || '#94a3b8';
}

/* 右侧辅助栏卡片壳 */
export function psCard(title, iconPath, inner) {
  return `<div class="ps-card"><div class="ps-title"><svg viewBox="0 0 24 24"><path d="${iconPath}"/></svg>${title}</div>${inner}</div>`;
}

export function _cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* ── 工具入参友好化 ──────────────────────────────────── */
export function friendlyToolArgs(name, args) {
  args = args || {};
  const a = args;
  try {
    switch (name) {
      case 'molar_mass':
        return '计算摩尔质量：' + (a.formula || a.compound || '未知化学式');
      case 'xrd_dspacing':
        return 'XRD 晶面间距：λ=' + (a.wavelength || '?') + 'Å, 2θ=' + (a.two_theta || a.theta2 || '?') + '°';
      case 'xrd_preprocess':
        return 'XRD 数据预处理' + ((a.data && a.data.length) ? '（' + a.data.length + ' 个点）' : '');
      case 'tauc_bandgap':
        return 'Tauc 带隙拟合' + ((a.energy && a.energy.length) ? '（' + a.energy.length + ' 个点）' : '');
      case 'thermo_gibbs':
        return '热力学计算：' + (a.reaction || a.formula || '吉布斯自由能');
      case 'solution_prep':
        return '溶液配制：' + (a.solute || a.chemical || '') + (a.concentration ? '，浓度 ' + a.concentration : '');
      case 'experiment_protocol':
        return '生成实验方案：' + (a.goal || a.title || '未指定目标');
      case 'experiment_plot':
        return '实验数据绘图：' + (a.chart_type || a.type || '默认图表');
      case 'chemical_safety':
        return '安全查询：' + (a.chemical || a.name || '未知化学品');
      case 'energy_convert':
        return '能量换算：' + (a.value || '?') + ' ' + (a.from_unit || a.from || '') + ' → ' + (a.to_unit || a.to || '');
      case 'lever_rule':
        return '杠杆规则计算：' + (a.phase || a.system || '二元体系');
      case 'citation_format':
        return '格式化引用：' + (a.style || a.format || '默认格式');
      case 'web_search':
      case 'web_search_merged':
        return '搜索：' + ((a.query || a.keyword || '').slice(0, 50) || '无关键词');
      case 'kb_search':
      case 'rag_search':
      case 'matlens_kb':
        return '知识库检索：' + ((a.query || a.keyword || '').slice(0, 50) || '无关键词');
      case 'read_file':
        return '读取文件：' + (a.file_path || a.path || '?');
      case 'write_file':
        return '写入文件：' + (a.file_path || a.path || '?');
      case 'patch':
        return '编辑文件：' + (a.file_path || a.path || '?');
      case 'terminal':
        return '执行命令：' + ((a.command || '').slice(0, 50) || '?');
      case 'execute_code':
        return '执行代码' + ((a.code || '').split('\n').length > 1 ? '（' + (a.code || '').split('\n').length + ' 行）' : '');
      case 'delegate_task':
        return '委派子任务：' + ((a.goal || '').slice(0, 50) || '?');
      case 'memory': {
        const act = a.action || a.operation || (a.operations ? 'batch' : '?');
        const targetTag = a.target === 'user' ? '（用户画像）' : '';
        if (act === 'add') return '🧠 记住：' + String(a.content || a.memory || a.text || '').slice(0, 36) + targetTag;
        if (act === 'replace') return '🧠 更新记忆：' + String(a.old_text || '').slice(0, 18) + ' → ' + String(a.content || a.new_text || '').slice(0, 18);
        if (act === 'remove') return '🧠 删除记忆：' + String(a.old_text || a.memory_id || '').slice(0, 18);
        if (act === 'batch') return '🧠 记忆批量更新（' + (Array.isArray(a.operations) ? a.operations.length : '?') + ' 项）';
        return '记忆操作：' + (act || '?');
      }
      case 'mem0_search':
        return '🧠 记忆检索：' + ((a.query || '').slice(0, 50) || '无关键词');
      case 'mem0_add':
        return '🧠 记住：' + String(a.content || '').slice(0, 40) + '（Mem0）';
      case 'mem0_update':
        return '🧠 更新记忆：' + String(a.text || '').slice(0, 30);
      case 'mem0_delete':
        return '🧠 删除记忆：' + String(a.memory_id || '?');
      case 'todo':
        return '待办事项：' + (a.action || '?');
      case 'clarify':
        return '请求澄清：' + ((a.question || '').slice(0, 50) || '?');
      case 'browser_navigate':
      case 'browser_exec':
        return '浏览器操作：' + ((a.url || a.action || '').slice(0, 50) || '?');
      default:
        const firstVal = Object.values(a)[0];
        return '调用 ' + name + (firstVal ? '：' + String(firstVal).slice(0, 40) : '');
    }
  } catch (e) {
    return '调用 ' + name;
  }
}

/* ── 轻量 Markdown 渲染（流式安全：先整体转义，再结构化） ── */
export function renderMarkdown(text) {
  const src = esc(String(text == null ? '' : text));
  const blocks = [];
  let s = src.replace(/```([\s\S]*?)```/g, (m, c) => {
    blocks.push('<pre class="md-code"><code>' + c.replace(/^\n/, '').replace(/\n$/, '') + '</code></pre>');
    return '\u0000' + (blocks.length - 1) + '\u0000';
  });
  const formulas = [];
  s = s.replace(/\$\$([\s\S]*?)\$\$/g, (m, formula) => {
    formulas.push({ type: 'block', tex: formula });
    return '\u0001F' + (formulas.length - 1) + '\u0001';
  });
  s = s.replace(/\$([^$\n]+?)\$/g, (m, formula) => {
    formulas.push({ type: 'inline', tex: formula });
    return '\u0001f' + (formulas.length - 1) + '\u0001';
  });
  const inline = t => t
    .replace(/&lt;br&gt;/g, '<br>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const renderTable = (rows) => {
    const split = r => r.trim().replace(/^\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
    const head = split(rows[0]);
    const dataRows = [];
    for (let i = 2; i < rows.length; i++) {
      if (/^\s*\|?[\s:|-]+\|?\s*$/.test(rows[i])) continue;
      dataRows.push(split(rows[i]));
    }
    const tableId = 'tbl_' + Math.random().toString(36).slice(2, 8);
    let h = '<div class="md-table-wrap"><div class="md-table-toolbar">' +
      '<span class="md-table-count">' + dataRows.length + ' 行 × ' + head.length + ' 列</span>' +
      '<div class="md-table-actions">' +
      '<button class="btn btn-ghost btn-sm md-table-copy" data-tid="' + tableId + '">复制表格</button>' +
      '<button class="btn btn-ghost btn-sm md-table-export" data-tid="' + tableId + '">导出 CSV</button>' +
      '</div></div>' +
      '<table class="md-table" id="' + tableId + '"><thead><tr>' +
      head.map((c, i) => '<th data-col="' + i + '" style="cursor:pointer">' + inline(c) + ' <span class="md-sort-icon">⇅</span></th>').join('') +
      '</tr></thead><tbody>';
    dataRows.forEach(cs => {
      h += '<tr>' + cs.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>';
    });
    h += '</tbody></table></div>';
    setTimeout(() => {
      const tbl = document.getElementById(tableId);
      if (!tbl) return;
      let sortCol = -1, sortAsc = true;
      tbl.querySelectorAll('thead th').forEach(th => {
        th.onclick = () => {
          const col = parseInt(th.dataset.col, 10);
          if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = true; }
          const tbody = tbl.querySelector('tbody');
          const trs = Array.from(tbody.querySelectorAll('tr'));
          trs.sort((a, b) => {
            const va = a.children[col]?.textContent || '';
            const vb = b.children[col]?.textContent || '';
            const na = parseFloat(va), nb = parseFloat(vb);
            let cmp;
            if (!isNaN(na) && !isNaN(nb)) cmp = na - nb;
            else cmp = va.localeCompare(vb, 'zh');
            return sortAsc ? cmp : -cmp;
          });
          trs.forEach(tr => tbody.appendChild(tr));
          tbl.querySelectorAll('thead th .md-sort-icon').forEach(ic => ic.textContent = '⇅');
          th.querySelector('.md-sort-icon').textContent = sortAsc ? '↑' : '↓';
        };
      });
      const copyBtn = document.querySelector('.md-table-copy[data-tid="' + tableId + '"]');
      if (copyBtn) copyBtn.onclick = () => {
        const rows = Array.from(tbl.querySelectorAll('tr')).map(tr =>
          Array.from(tr.children).map(td => td.textContent.trim()).join('\t'));
        const text = rows.join('\n');
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('表格已复制（Tab 分隔，可粘贴到 Excel）'));
        else toast('复制失败，请手动选择');
      };
      const exportBtn = document.querySelector('.md-table-export[data-tid="' + tableId + '"]');
      if (exportBtn) exportBtn.onclick = () => {
        const rows = Array.from(tbl.querySelectorAll('tr')).map(tr =>
          Array.from(tr.children).map(td => {
            const t = td.textContent.trim();
            return t.includes(',') || t.includes('"') ? '"' + t.replace(/"/g, '""') + '"' : t;
          }).join(','));
        const csv = '\uFEFF' + rows.join('\n');
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'table_export.csv'; a.click();
        URL.revokeObjectURL(url);
        toast('已导出 CSV');
      };
    }, 0);
    return h;
  };
  let html = '', inList = null;
  const para = [], tblRows = [];
  const flushPara = () => { if (para.length) { html += '<p>' + inline(para.join('\n')) + '</p>'; para.length = 0; } };
  const flushList = () => { if (inList) { html += '</' + inList + '>'; inList = null; } };
  const flushTable = () => { if (tblRows.length) { html += renderTable(tblRows.splice(0)); } };
  for (const line of s.split('\n')) {
    const codeIdx = line.trim().match(/^\u0000(\d+)\u0000$/);
    if (codeIdx) { flushPara(); flushList(); flushTable(); html += blocks[Number(codeIdx[1])]; continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) { flushPara(); flushList(); tblRows.push(line); continue; }
    if (tblRows.length) flushTable();
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { flushPara(); flushList(); html += '<h' + h[1].length + '>' + inline(h[2]) + '</h' + h[1].length + '>'; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) { if (inList !== 'ul') { flushPara(); flushList(); html += '<ul>'; inList = 'ul'; } html += '<li>' + inline(ul[1]) + '</li>'; continue; }
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ol) { if (inList !== 'ol') { flushPara(); flushList(); html += '<ol>'; inList = 'ol'; } html += '<li>' + inline(ol[1]) + '</li>'; continue; }
    const bq = line.match(/^\s*>\s?(.*)$/);
    if (bq) { flushPara(); flushList(); flushTable(); html += '<blockquote>' + inline(bq[1]) + '</blockquote>'; continue; }
    if (!line.trim()) { flushPara(); flushList(); flushTable(); continue; }
    if (inList) flushList();
    para.push(line);
  }
  flushPara(); flushList(); flushTable();
  if (formulas.length && window.katex) {
    html = html.replace(/\u0001([Ff])(\d+)\u0001/g, (m, kind, idx) => {
      const f = formulas[Number(idx)];
      if (!f) return m;
      try {
        const rendered = window.katex.renderToString(f.tex, {
          displayMode: f.type === 'block',
          throwOnError: false,
          output: 'html'
        });
        return f.type === 'block' ? '<div class="md-formula-block">' + rendered + '</div>' : '<span class="md-formula-inline">' + rendered + '</span>';
      } catch (e) {
        return '<code class="md-inline">' + esc(f.tex) + '</code>';
      }
    });
  }
  return html || '<p></p>';
}

/* ── HTTP 封装：统一错误处理，绝不抛 unhandled rejection ──
 * 自动处理 401/500/网络错误，错误走 toast + 返回 {ok:false}。
 * 调用方用 if (d && d.ok) 判断成功，失败已统一提示。 */
const _API_TIMEOUT = 30000;
let _suppressNextErrorToast = false;

/* ── S5：服务端鉴权 token（localStorage: matlens_token） ──
 * 有 token 就自动带 Authorization: Bearer <token>；没有就不加。 */
function _authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  try {
    const tok = localStorage.getItem('matlens_token');
    if (tok) h['Authorization'] = 'Bearer ' + tok;
  } catch (e) { /* localStorage 不可用时静默 */ }
  return h;
}

/* 401 时弹出的极简 token 输入浮层：确认后 resolve(输入的 token)；
 * 点遮罩 / Esc 取消时 resolve('')。 */
function _tokenOverlay() {
  return new Promise((resolve) => {
    const old = document.getElementById('matlens-token-modal');
    if (old) old.remove();
    const mask = document.createElement('div');
    mask.id = 'matlens-token-modal';
    mask.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.5);' +
      'display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;';
    const card = document.createElement('div');
    card.style.cssText = 'background:#1e293b;color:#e2e8f0;padding:22px 24px;border-radius:12px;' +
      'width:320px;box-shadow:0 12px 40px rgba(0,0,0,.4);';
    const title = document.createElement('div');
    title.style.cssText = 'font-size:15px;font-weight:600;margin-bottom:6px;';
    title.textContent = 'MatLens 需要访问令牌';
    const sub = document.createElement('div');
    sub.style.cssText = 'font-size:12px;color:#94a3b8;margin-bottom:14px;';
    sub.textContent = '服务端已开启鉴权，请输入 Bearer Token';
    const input = document.createElement('input');
    input.type = 'password';
    input.placeholder = '粘贴 token';
    input.style.cssText = 'width:100%;box-sizing:border-box;padding:8px 10px;border-radius:8px;' +
      'border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:13px;margin-bottom:14px;';
    const row = document.createElement('div');
    row.style.cssText = 'text-align:right;';
    const btn = document.createElement('button');
    btn.textContent = '确认';
    btn.style.cssText = 'padding:7px 18px;border-radius:8px;border:none;background:#38bdf8;' +
      'color:#0f172a;font-size:13px;cursor:pointer;';
    row.appendChild(btn);
    card.appendChild(title); card.appendChild(sub); card.appendChild(input); card.appendChild(row);
    mask.appendChild(card);
    document.body.appendChild(mask);
    input.focus();
    let done = false;
    const finish = (val) => { if (done) return; done = true; mask.remove(); resolve(val || ''); };
    btn.onclick = () => finish(input.value.trim());
    input.onkeydown = (e) => {
      if (e.key === 'Enter') finish(input.value.trim());
      else if (e.key === 'Escape') finish('');
    };
    mask.onclick = (e) => { if (e.target === mask) finish(''); };
  });
}

function _friendlyHttpError(status, detail) {
  if (status === 404) return '接口不存在（404）：请确认服务已启动';
  if (status === 401) return '未授权（401）：令牌无效或已过期';
  if (status === 403) return '禁止访问（403）';
  if (status >= 500) return '服务异常（' + status + '）：' + (detail || '请稍后重试');
  return '请求失败（' + status + '）：' + (detail || '未知错误');
}

/* 单次 fetch：自动注入 Authorization 头 */
async function _doFetch(url, opts) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), _API_TIMEOUT);
  try {
    return await fetch(url, Object.assign({}, opts, {
      headers: _authHeaders(opts && opts.headers),
      signal: ctrl.signal,
    }));
  } finally {
    clearTimeout(t);
  }
}

async function _fetchJson(url, opts) {
  let resp;
  try {
    resp = await _doFetch(url, opts);
  } catch (e) {
    const msg = e.name === 'AbortError' ? '请求超时，请检查网络或稍后重试' : ('网络错误：' + (e.message || '无法连接服务'));
    if (!_suppressNextErrorToast) toast(msg, 'err');
    return { ok: false, error: e.name === 'AbortError' ? 'timeout' : 'network', detail: msg };
  }
  /* S5：任一请求 401 → 弹 token 浮层，确认后存 localStorage 并重放该请求一次 */
  if (resp.status === 401) {
    const tok = await _tokenOverlay();
    if (tok) {
      try { localStorage.setItem('matlens_token', tok); } catch (e) {}
      try {
        resp = await _doFetch(url, opts);
      } catch (e) {
        const msg = '网络错误：' + (e.message || '无法连接服务');
        if (!_suppressNextErrorToast) toast(msg, 'err');
        return { ok: false, error: 'network', detail: msg };
      }
    } else {
      if (!_suppressNextErrorToast) toast('未授权：已取消输入令牌', 'err');
      return { ok: false, status: 401, detail: 'unauthorized' };
    }
  }
  if (!resp.ok) {
    let detail = '';
    try {
      const j = await resp.json();
      if (j) detail = j.detail ? (typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)) : (j.error || '');
    } catch (e) {}
    const friendly = _friendlyHttpError(resp.status, detail);
    if (!_suppressNextErrorToast) toast(friendly, 'err');
    return { ok: false, status: resp.status, detail };
  }
  try {
    return await resp.json();
  } catch (e) {
    return { ok: false, detail: '响应解析失败' };
  }
}

export async function jget(p) { return _fetchJson(p); }
export async function jpost(p, body) {
  return _fetchJson(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
}
export async function jput(p, body) {
  return _fetchJson(p, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
}
export async function jdel(p) { return _fetchJson(p, { method: 'DELETE' }); }

/* 静默请求（不弹错误 toast，由调用方自行处理） */
export async function jgetSilent(p) {
  _suppressNextErrorToast = true;
  try { return await _fetchJson(p); } finally { _suppressNextErrorToast = false; }
}

/* ── 全局错误边界：未捕获错误 / Promise rejection → 红色 toast ── */
export function initErrorBoundary() {
  window.addEventListener('error', (e) => {
    const msg = (e && e.message) ? ('页面错误：' + e.message) : '页面发生错误';
    console.error('[error boundary]', e.error || e.message);
    toast(msg, 'err');
  });
  window.addEventListener('unhandledrejection', (e) => {
    const reason = e && e.reason;
    const msg = reason && reason.message ? ('异步错误：' + reason.message) : '异步操作失败';
    console.error('[unhandledrejection]', reason);
    toast(msg, 'err');
    if (e) e.preventDefault();
  });
}

/* ── 响应式：窄屏侧边栏抽屉汉堡 ────────────────────────── */
export function initResponsiveDrawer() {
  // 若已存在汉堡按钮则复用，否则在 body 顶部注入一个
  let hamburger = document.getElementById('nav-hamburger');
  if (!hamburger) {
    hamburger = document.createElement('button');
    hamburger.id = 'nav-hamburger';
    hamburger.type = 'button';
    hamburger.setAttribute('aria-label', '打开菜单');
    hamburger.style.cssText = 'position:fixed;top:12px;left:12px;z-index:1200;display:none;' +
      'width:40px;height:40px;border-radius:10px;border:1px solid var(--ml-card-border);' +
      'background:var(--ml-card);color:var(--ml-text);font-size:18px;cursor:pointer;';
    hamburger.textContent = '☰';
    document.body.appendChild(hamburger);
  }
  const sidebar = document.querySelector('.sidebar') || document.querySelector('.side') || document.querySelector('aside');
  function applyBreakpoint() {
    const narrow = window.innerWidth < 768;
    hamburger.style.display = narrow ? 'flex' : 'none';
    if (sidebar) {
      sidebar.classList.toggle('drawer-open', false);
      sidebar.style.transition = 'transform .25s ease';
      if (narrow) {
        sidebar.style.transform = sidebar.classList.contains('drawer-open') ? 'translateX(0)' : 'translateX(-105%)';
      } else {
        sidebar.style.transform = '';
      }
    }
  }
  hamburger.onclick = () => {
    if (!sidebar) return;
    const open = !sidebar.classList.contains('drawer-open');
    sidebar.classList.toggle('drawer-open', open);
    sidebar.style.transform = open ? 'translateX(0)' : 'translateX(-105%)';
  };
  // 点击主内容区时关闭抽屉
  document.addEventListener('click', (e) => {
    if (window.innerWidth >= 768 || !sidebar || !sidebar.classList.contains('drawer-open')) return;
    if (e.target.closest('.sidebar') || e.target.closest('.side') || e.target.closest('aside') || e.target.closest('#nav-hamburger')) return;
    sidebar.classList.remove('drawer-open');
    sidebar.style.transform = 'translateX(-105%)';
  });
  window.addEventListener('resize', applyBreakpoint);
  applyBreakpoint();
}

/* ── 暴露给 index.html 内联脚本（内联 onclick / 事件处理器引用） ── */
export function exposeGlobals() {
  window.esc = esc;
  window.toast = toast;
  window.MODEL_CATALOG = window.MODEL_CATALOG || {};
}
