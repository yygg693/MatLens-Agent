/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat_right.js
 *
 * 2026-10-15 重写：对话页右侧辅助栏（记忆 / 引用 / 文件 / 时间线）
 *
 * 重写前的三个问题（均为实测，非观感）：
 *  1. 四个 tab 里**只有「记忆」有真实数据**，另三个是 index.html 里
 *     硬编码的死文案「XX 将显示在此」，永远不变。
 *  2. 记忆条目没有时间、没有来源、不能搜索、不能删除 ——
 *     记忆抽取错了根本无从排查，也没法纠正。
 *  3. 类名冲突：`.mem-cat` 既被本栏当分类徽章（690行）、
 *     又被记忆图谱页当分类标签（824 行，display:flex），
 *     两套样式互相覆盖。本模块统一用 `.rm-cat` 前缀避开。
 *
 * 设计取向：
 *  - 每个 tab 都有**真实数据源**，空态给出「怎么才能有内容」而非一句占位
 *  - 记忆条可展开全文 / 可删除（DELETE /api/memory/{id} 已存在）
 *  - 时间线复用 chat_toolcards 已有的 S.execLog，不重复造数据
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jdel, S } from './core.js';

const TABS = ['mem', 'cite', 'files', 'tl'];
let _active = 'mem';
let _memCache = [];

/** 右栏面板显示的时间格式：今天只显示时刻，跨天才带日期。 */
function _fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (sameDay) return hh + ':' + mm;
  return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hh + ':' + mm;
}

function _catClass(cat) {
  return ({ 'Agent': 'agent', '实验': 'exp', '材料': 'mat', '结论': 'con' })[cat] || 'user';
}

/** 空态 SVG 线性图标表（与右栏 tab、加号菜单同风格，不用 emoji）。 */
const _EMPTY_ICON = {
  mem:   '<path d="M9 2h6a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M9 2v3a2 2 0 0 0 2 2h2"/><path d="M9 2a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2"/><path d="M11 11h2M11 15h2"/>',
  cite:  '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M9 13h6M9 17h4"/>',
  files: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  tl:    '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  off:   '<path d="M9 18l6-6-6-6"/>',
  warn:  '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
};

function _empty(kind, title, hint) {
  const d = _EMPTY_ICON[kind] || _EMPTY_ICON.off;
  return '<div class="rm-empty">' +
    '<svg class="rm-empty-ic" viewBox="0 0 24 24">' + d + '</svg>' +
    '<div class="rm-empty-tx">' + esc(title) + '</div>' +
    (hint ? '<div class="rm-empty-hint">' + esc(hint) + '</div>' : '') +
    '</div>';
}

/* ── 记忆 ─────────────────────────────────────────────── */

/** 从对话流文本里抽取 [n] / {A-n} 形式的引用编号。 */
function _collectCitations() {
  const map = new Map();
  document.querySelectorAll('#chat-stream .msg.agent .rf-text').forEach(el => {
    const txt = el.textContent || '';
    // [12] 与 {A-3} 两种格式（与 enforce_refs 的白名单一致）
    const re = /\[(\d{1,3})\]|\{A-(\d{1,3})\}/g;
    let m;
    while ((m = re.exec(txt)) !== null) {
      const n = m[1] || m[2];
      if (!map.has(n)) map.set(n, { num: n, count: 0, snippet: '' });
      const it = map.get(n);
      it.count++;
      if (!it.snippet) {
        const s = Math.max(0, m.index - 40);
        it.snippet = txt.slice(s, m.index + 60).trim().replace(/\s+/g, ' ');
      }
    }
  });
  return Array.from(map.values()).sort((a, b) => (+a.num) - (+b.num));
}

async function renderMem() {
  const el = $id('right-mem');
  if (!el) return;
  el.innerHTML = '<div class="rm-loading">加载记忆…</div>';
  let d;
  try { d = await jget('/api/memory?top_k=40'); }
  catch (e) { el.innerHTML = _empty('warn', '记忆服务不可用', (e && e.message) || '请检查后端'); return; }
  if (!d || !d.ok) { el.innerHTML = _empty('warn', '记忆服务返回异常', ''); return; }
  _memCache = d.memories || [];
  S.memCount = _memCache.length;
  if (d.disabled) {
    el.innerHTML = _empty('off', '记忆功能已关闭', '设置 → 记忆 → 开启后自动积累');
    return;
  }
  if (!_memCache.length) {
    el.innerHTML = _empty('mem', '还没有记忆', '对话几轮后 Agent 会自动提取，也可在「记忆图谱」手动添加');
    return;
  }
  // 头部汇总：后端 mem0_search 只返回 id/memory/score（无时间戳），
  // 故汇总只给条数与来源，不编造「N 分钟前」。
  el.innerHTML = '<div class="rm-sum">共 ' + _memCache.length + ' 条 · 按相关度排序' +
    (d.query ? (' · 检索词「' + d.query + '」') : '') + '</div>' +
    _memCache.map((m, i) => {
      const cat = m.category || '记忆';
      const full = String(m.memory || m.text || '');
      const brief = full.length > 110 ? full.slice(0, 110) + '…' : full;
      const meta = _fmtTime(m.created_at) || ('#' + (i + 1));
      return '<div class="rm-item" data-id="' + esc(m.id || '') + '" data-full="' + esc(full) + '">' +
        '<div class="rm-head">' +
          '<span class="rm-cat ' + _catClass(cat) + '">' + esc(cat) + '</span>' +
          '<span class="rm-time">' + esc(meta) + '</span>' +
          '<button class="rm-del" title="删除这条记忆">✕</button>' +
        '</div>' +
        '<div class="rm-body">' + esc(brief) + '</div>' +
        '</div>';
    }).join('');
}

/* ── 引用 ─────────────────────────────────────────────── */
function renderCite() {
  const el = $id('right-cite');
  if (!el) return;
  const items = _collectCitations();
  const nAgent = document.querySelectorAll('#chat-stream .msg.agent').length;
  if (!nAgent) {
    el.innerHTML = _empty('cite', '本轮还没有回答', 'Agent 回答中引用的文献编号会汇总到这里');
    return;
  }
  if (!items.length) {
    el.innerHTML = _empty('cite', '回答里没有引用标记', '提示词要求正文用 [n] 标注文献，可引导 Agent 补充');
    return;
  }
  el.innerHTML = '<div class="rm-sum">共引用 ' + items.length + ' 条文献</div>' +
    items.map(it =>
      '<div class="rm-item rm-cite">' +
        '<div class="rm-head"><span class="rm-cat user">[' + esc(it.num) + ']</span>' +
        '<span class="rm-time">引用 ' + it.count + ' 次</span></div>' +
        '<div class="rm-body">…' + esc(it.snippet) + '…</div>' +
      '</div>').join('');
}

/* ── 文件 ─────────────────────────────────────────────── */
function renderFiles() {
  const el = $id('right-files');
  if (!el) return;
  const atts = S.attachments || [];
  // 从回答里找文件路径引用（[附件：xxx → path] 或工具返回的路径）
  const paths = [];
  document.querySelectorAll('#chat-stream .msg').forEach(el2 => {
    const txt = el2.textContent || '';
    const re = /[A-Za-z]:\\[^\s，。；;）)]+|\/[^\s，。；;）)]+\.(?:csv|xlsx?|pdf|png|json|txt|py|md|docx?)/g;
    let m;
    while ((m = re.exec(txt)) !== null) {
      if (!paths.includes(m[0])) paths.push(m[0]);
    }
  });
  const kbName = S.kb && S.kb.name;
  if (!atts.length && !paths.length && !kbName) {
    el.innerHTML = _empty('files', '本轮没有文件', '用「+」上传 XRD 图谱 / PDF / CSV，或先选一个知识库');
    return;
  }
  let html = '';
  if (kbName) {
    html += '<div class="rm-item"><div class="rm-head"><span class="rm-cat mat">知识库</span>' +
      '<span class="rm-time">检索来源</span></div><div class="rm-body">' + esc(kbName) + '</div></div>';
  }
  if (atts.length) {
    html += '<div class="rm-sum">本轮附件 ' + atts.length + ' 个</div>' +
      atts.map(a => '<div class="rm-item"><div class="rm-head">' +
        '<span class="rm-cat exp">附件</span>' +
        '<span class="rm-time">' + esc(a.name.length > 22 ? a.name.slice(0, 22) + '…' : a.name) + '</span>' +
        '</div><div class="rm-body rm-path">' + esc(a.path || '') + '</div></div>').join('');
  }
  if (paths.length) {
    html += '<div class="rm-sum">对话中出现的文件路径 ' + paths.length + ' 处</div>' +
      paths.slice(0, 20).map(p => '<div class="rm-item"><div class="rm-body rm-path">' + esc(p) + '</div></div>').join('');
  }
  el.innerHTML = html;
}

/* ── 时间线 ───────────────────────────────────────────── */
function renderTimeline() {
  const el = $id('right-tl');
  if (!el) return;
  const log = S.execLog || [];
  if (!log.length) {
    el.innerHTML = _empty('tl', '还没有工具调用', 'Agent 调用材料工具时会在此留下时间线');
    return;
  }
  const rows = [];
  log.forEach((turn, ti) => {
    const steps = turn.steps || [];
    if (!steps.length) return;
    rows.push('<div class="rm-turn">第 ' + (ti + 1) + ' 轮 · ' +
      esc(_fmtTime(new Date(turn.t0).toISOString())) + ' · ' + steps.length + ' 次调用</div>');
    steps.forEach(st => {
      const cls = st.status === 'ok' ? 'ok' : (st.status === 'fail' ? 'fail' : 'run');
      const dur = st.t1 ? (' · ' + Math.max(0, Math.round((st.t1 - st.t0) / 100) / 10) + 's') : '';
      rows.push('<div class="rm-tl-row ' + cls + '" title="' + esc(st.friendly || st.name) + '">' +
        '<span class="rm-tl-dot"></span>' +
        '<span class="rm-tl-name">' + esc(st.name) +
        (st.count > 1 ? (' ×' + st.count) : '') + '</span>' +
        '<span class="rm-tl-dur">' + dur + '</span>' +
        '</div>');
    });
  });
  el.innerHTML = rows.length ? rows.join('') : _empty('tl', '还没有工具调用', '');
}

/* ── 切换与绑定 ───────────────────────────────────────── */

export function switchRightTab(tab) {
  if (!TABS.includes(tab)) tab = 'mem';
  _active = tab;
  TABS.forEach(k => {
    const t = document.querySelector('.right-tab[data-tab="' + k + '"]');
    if (t) t.classList.toggle('active', k === tab);
    const body = $id('right-' + k);
    if (body) body.style.display = (k === tab) ? 'block' : 'none';
  });
  // 惰性渲染：切到哪个才拉哪个
  if (tab === 'mem') renderMem();
  else if (tab === 'cite') renderCite();
  else if (tab === 'files') renderFiles();
  else renderTimeline();
}

export function refreshRightPanel() {
  if (_active === 'mem') renderMem();
  else if (_active === 'cite') renderCite();
  else if (_active === 'files') renderFiles();
  else if (_active === 'tl') renderTimeline();
}

export function initRightPanel() {
  document.querySelectorAll('.right-tab').forEach(t => {
    t.addEventListener('click', () => switchRightTab(t.dataset.tab));
  });
  // 记忆条目：点击展开全文（省略号截断的才需要展开）
  const mem = $id('right-mem');
  if (mem) {
    mem.addEventListener('click', async (e) => {
      const del = e.target.closest('.rm-del');
      if (del) {
        e.stopPropagation();
        const item = del.closest('.rm-item');
        const id = item && item.dataset.id;
        if (!id) { toast('这条记忆没有 ID，无法删除', 'err'); return; }
        if (!confirm('确定删除这条记忆？')) return;
        try {
          await jdel('/api/memory/' + encodeURIComponent(id));
          item.style.transition = 'opacity .2s,transform .2s';
          item.style.opacity = '0'; item.style.transform = 'translateX(12px)';
          setTimeout(() => { S.memCount = Math.max(0, (S.memCount || 1) - 1); renderMem(); }, 220);
          toast('已删除记忆');
        } catch (err) { toast('删除失败：' + (err.message || err), 'err'); }
        return;
      }
      const row = e.target.closest('.rm-item');
      if (!row) return;
      const body = row.querySelector('.rm-body');
      const full = row.dataset.full;
      if (body && full && body.textContent.length < full.length) {
        body.textContent = full;
        row.classList.add('expanded');
      } else if (row.classList.contains('expanded')) {
        row.classList.remove('expanded');
        renderMem();
      }
    });
  }
  renderMem();
}
