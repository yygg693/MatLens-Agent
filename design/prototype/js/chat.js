/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat.js（聊天主循环 / SSE 流式 / 工具卡 / 计划卡 /
 * 审批卡 / 输入区 / 功能标签面板 / 执行日志）
 * ═══════════════════════════════════════════════════════════════ */
import {
  esc, $id, toast, renderMarkdown, jget, jpost, jput,
  S, TOOL_ICON, friendlyToolArgs, toolCatColor,
} from './core.js';
import { loadSessions } from './sessions.js';
import { loadMemory } from './graph.js';
// 2026-10-15 拆分：功能标签面板
import { loadContextChip, loadModelChip } from './chat_panels.js';
// 2026-10-15 拆分：工具卡 / 计划卡 / 执行日志
import {
  appendToolCard, resolveToolCard, collectToolLog, updateToolLog,
  appendApprovalCard, renderExecLog, _planSetStatus, injectChatDeps,
} from './chat_toolcards.js';
// 2026-10-15 拆分：SSE 流式主循环（sendMsg / startStream / stop）
import { sendMsg, startStream, stop, injectSSEDeps } from './chat_sse.js';
// 2026-10-15 拆分：输入框增强（自动增高/ 草稿 / 历史 / 图片拖入）
import { autoGrow, initInputEnhance, afterSend } from './chat_input.js';

// 注入工具卡模块所需的回调（避免 chat.js ↔ chat_toolcards.js 循环依赖）。
// 放在 initInputTools() 里做而非模块顶层：ESM 的 import 声明会被提升，
// 顶层代码先于函数体执行虽因函数声明提升而可用，但显式延后更清晰、也避免
// 将来有人把回调改成 const 箭头函数时静默失效。
function _injectToolcardDeps() {
  injectChatDeps({
    autoScroll: _autoScroll,
    flushStreamRender: _flushStreamRender,
    setBusy: setBusy,
  });
  // 2026-10-15：SSE 模块同样需要这些 UI 回调（滚动/ 冲刷 / 忙碌态 / 工具面板 / 清附件）
  injectSSEDeps({
    autoScroll: _autoScroll,
    scheduleStreamRender: _scheduleStreamRender,
    flushStreamRender: _flushStreamRender,
    setBusy: setBusy,
    hideToolPicker: _hideToolPicker,
    clearAttachments: clearAttachments,
  });
}

/* ── 流式自动滚动 ─────────────────────────────────────── */
export function _autoScroll() {
  const el = $id('chat-stream');
  if (!el) return;
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 120) {
    el.scrollTop = el.scrollHeight;
  }
}

/* ── 流式渲染：rAF 节流 + 未闭合代码块补全 + 闪烁光标 ── */
function _streamRender() {
  S._streamRaf = null;
  if (!S.curText || !document.body.contains(S.curText)) return;
  let buf = S.curTextBuf || '';
  const fenceCount = (buf.match(/```/g) || []).length;
  if (fenceCount % 2 === 1) buf += '\n```';
  let html = renderMarkdown(buf);
  if (S._streaming) html += '<span class="stream-cursor">\u258b</span>';
  S.curText.innerHTML = html;
  _autoScroll();
}
function _scheduleStreamRender() {
  if (S._streamRaf) return;
  S._streamRaf = requestAnimationFrame(_streamRender);
}
function _flushStreamRender() {
  if (S._streamRaf) { cancelAnimationFrame(S._streamRaf); S._streamRaf = null; }
  _streamRender();
}
export function setBusy(b) {
  S.streaming = b;
  const stopBtn = $id('btn-stop'); if (stopBtn) stopBtn.style.display = b ? 'flex' : 'none';
  const sendBtn = $id('btn-send'); if (sendBtn) sendBtn.style.display = b ? 'none' : 'flex';
  const st = $id('chat-status'); if (!st) return;
  st.textContent = b ? '思考中…' : '就绪';
  st.style.color = b ? 'var(--ml-warn)' : 'var(--ml-text-faint)';
  if (b) st.classList.add('thinking-pulse'); else st.classList.remove('thinking-pulse');
}

/* ── @工具 选择器 ────────────────────────────────────── */
let _tpActive = false;
function _syncTp() { if (window.ML) window.ML._tpActive = _tpActive; }
function _showToolPicker() {
  const picker = $id('tool-picker');
  if (!picker) return;
  _tpActive = true; _syncTp();
  _renderToolPicker('');
  picker.style.display = 'flex';
}
export function _hideToolPicker() {
  const picker = $id('tool-picker');
  if (picker) picker.style.display = 'none';
  _tpActive = false; _syncTp();
}
function _renderToolPicker(filter) {
  const list = $id('tp-list');
  if (!list) return;
  const f = (filter || '').toLowerCase().trim();

  // 2026-10-15：并入 skill + 通用工具。
  // 此前只遍历 material（23 个），186 个 skill 完全搜不到 —— 实测 @论文 → 0 条。
  //
  // ⚠️ **同名去重**（实测踩坑）：`arxiv` 同时是 skill 名和通用工具名，
  // 直接 concat 会产生两条同名 .tp-item，浏览器把它们叠在一起 →
  // 首项被压成 18×28 的窄条（截图里表现为"文字竖排"）。故按name 去重，
  // 优先级：材料 > 通用 > 技能（材料工具最具体，skill 作为兜底补充）。
  const pool = [];
  const seen = new Set();
  const push = (t, kind) => {
    if (!t || !t.name) return;
    const key = String(t.name);
    if (seen.has(key)) return;
    seen.add(key);
    pool.push({ ...t, _k: kind });
  };
  (TOOL_DATA.material || []).forEach(t => push(t, '材料'));
  ((TOOL_DATA.general && TOOL_DATA.general.items) || []).forEach(t => push(t, '通用'));
  (TOOL_DATA.skills || []).forEach(s => push({
    name: s.name, cn: s.cn || s.name,
    desc: s.desc_cn || s.desc || '',
    cat: s.category_cn || s.category || '技能',
  }, '技能'));

  // 匹配范围含中英名+ 中英描述 + 分类（skill 走中文分类名）
  const hay = t => [t.name, t.cn, t.desc, t.cat, t._k].filter(Boolean).join(' ').toLowerCase();
  const hits = f ? pool.filter(t => hay(t).includes(f)) : pool;

  const MAX = 40;                       // 40 = 一屏多一点，且下方明确显示剩余数
  const shown = hits.slice(0, MAX);
  const rest = hits.length - shown.length;

  const html = shown.map((t, i) => {
    const c = toolCatColor(t.cat) || '#64748b';
    return '<div class="tp-item" data-name="' + esc(t.name) + '" data-kind="' + esc(t._k) + '" data-idx="' + i + '">' +
      '<span class="tp-icon" style="background:' + c + '22;color:' + c + '">' + esc((t.cn || t.name)[0]) + '</span>' +
      '<span class="tp-info"><span class="tp-name">' + esc(t.cn || t.name) +
      '<em class="tp-kind">' + esc(t._k) + '</em></span>' +
      '<span class="tp-desc">' + esc(t.desc || '').slice(0, 46) + '</span></span>' +
      '<span class="tp-key">' + esc(t.name) + '</span></div>';
  }).join('') || '<div class="tp-empty">无匹配条目<br><span>可试「XRD」「论文」「比容量」或工具名</span></div>';

  // 剩余提示：此前硬编码 slice(0,12) 且无任何提示，用户不知道还有更多
  const more = rest > 0
    ? '<div class="tp-more">还有 ' + rest + ' 个匹配项，继续输入以缩小范围 ↑↓ 选择 · Enter 确认</div>' : '';
  list.innerHTML = html + more;

  const items = list.querySelectorAll('.tp-item');
  const pick = (idx) => {
    const it = items[idx];
    if (!it) return;
    const name = it.getAttribute('data-name');
    const input = $id('input');
    const val = input.value;
    const atIdx = val.lastIndexOf('@');
    input.value = atIdx >= 0 ? val.slice(0, atIdx) + '@' + name + ' ' : val + '@' + name + ' ';
    input.focus();
    _hideToolPicker();
    autoGrow(input);
  };
  items.forEach((item, i) => {
    item.onclick = () => pick(i);
    item.onmouseenter = () => _setTpCursor(i);
  });
  _setTpCursor(0);
}

// 键盘导航光标（↑↓ + Enter），纯键盘用户不再必须用鼠标
let _tpCursor = 0;
function _setTpCursor(i) {
  const items = document.querySelectorAll('#tp-list .tp-item');
  if (!items.length) return;
  _tpCursor = Math.max(0, Math.min(i, items.length - 1));
  items.forEach((el, k) => el.classList.toggle('tp-sel', k === _tpCursor));
  const cur = items[_tpCursor];
  if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' });
}

/** @ 选择器打开时的键盘处理，返回 true 表示已消费该按键。 */
export function _toolPickerKey(e) {
  const picker = $id('tool-picker');
  if (!picker || picker.style.display === 'none') return false;
  const n = document.querySelectorAll('#tp-list .tp-item').length;
  if (!n) return false;
  if (e.key === 'ArrowDown') { _setTpCursor(_tpCursor + 1); return true; }
  if (e.key === 'ArrowUp') { _setTpCursor(_tpCursor - 1); return true; }
  if (e.key === 'Enter') {
    const it = document.querySelectorAll('#tp-list .tp-item')[_tpCursor];
    if (it) {
      const name = it.getAttribute('data-name');
      const input = $id('input');
      const val = input.value;
      const atIdx = val.lastIndexOf('@');
      input.value = atIdx >= 0 ? val.slice(0, atIdx) + '@' + name + ' ' : val + '@' + name + ' ';
      input.focus();
      _hideToolPicker();
      autoGrow(input);
    }
    return true;
  }
  if (e.key === 'Escape') { _hideToolPicker(); return true; }
  return false;
}
export function _handleAtInput(input) {
  const val = input.value;
  const cursorPos = input.selectionStart;
  const beforeCursor = val.slice(0, cursorPos);
  const atMatch = beforeCursor.match(/@([^\s@]*)$/);
  if (atMatch) {
    const filter = atMatch[1];
    if (!_tpActive) { _tpActive = true; _syncTp(); const p = $id('tool-picker'); if (p) p.style.display = 'flex'; }
    _renderToolPicker(filter);
  } else if (_tpActive) {
    _hideToolPicker();
  }
}

/* ── 输入区：加号菜单 / 附件 / 模式徽标 ───────────────── */
let _addMenuOpen = false;

/* ── 截图提问 ─────────────────────────────────────────── */
export async function captureScreenshot() {
  try {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      toast('当前浏览器不支持屏幕捕获，请用「添加文件或图片」上传截图'); return;
    }
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement('video');
    video.srcObject = stream; video.muted = true;
    await video.play();
    await new Promise(r => setTimeout(r, 350));
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    stream.getTracks().forEach(t => t.stop());
    const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
    if (!blob) { toast('截图失败'); return; }
    const file = new File([blob], 'screenshot_' + Date.now() + '.png', { type: 'image/png' });
    uploadAttachment(file);
    const ta = $id('input'); if (ta) ta.focus();
  } catch (e) { toast('截图取消或失败：' + (e.message || e)); }
}

export function initInputTools() {
  _injectToolcardDeps();
  // 2026-10-15 拆分后在此注入工具卡模块依赖
  initInputEnhance();   // 自动增高 / 草稿 / 历史 / 图片拖入
  const addBtn = $id('btn-add'), menu = $id('add-menu');
  if (addBtn && menu) {
    addBtn.onclick = (e) => {
      e.stopPropagation();
      _addMenuOpen = !_addMenuOpen;
      if (_addMenuOpen) refreshAddMenu();
      menu.style.display = _addMenuOpen ? 'block' : 'none';
    };
    menu.addEventListener('click', (e) => {
      const item = e.target.closest('.am-item');
      if (!item || item.hasAttribute('disabled')) return;
      const act = item.dataset.action;
      menu.style.display = 'none'; _addMenuOpen = false;
      // 2026-10-15 重做：action 值与 HTML data-action 严格对齐。
      // 原版 HTML 用 file/cloud/screen/shot/skills/conn，JS 判 upload/screenshot/tools，
      // 两边**没有任何交集** → 点任何一项都只是静默关菜单。
      switch (act) {
        case 'file':
          // 走会话附件通道（/api/chat/upload），不是知识库导入 —— 后者要选库
          { const fi = $id('file-input'); if (fi) fi.click(); }
          break;
        case 'screenshot': captureScreenshot(); break;
        case 'kb': queryKbGlobal(); break;
        case 'memory': openMemoryPanelGlobal(); break;
        case 'tools': openToolCatalogGlobal(); break;
        default: toast('未识别的操作：' + act, 'err');
      }
    });
    document.addEventListener('click', () => { if (_addMenuOpen) { menu.style.display = 'none'; _addMenuOpen = false; } });
  }
  const fi = $id('file-input');
  if (fi) fi.onchange = () => {
    const files = Array.from(fi.files || []);
    files.forEach(f => uploadAttachment(f));
    fi.value = '';
  };
}

/* 由 main.js 注入的全局引用（避免循环依赖） */
let pickUploadGlobal = () => toast('请先选择知识库');
let openToolCatalogGlobal = () => {};
let queryKbGlobal = () => toast('知识库检索暂未接入');
let openMemoryPanelGlobal = () => toast('记忆面板暂未接入');
// 注：_addMenuOpen 已在 222 行声明（紧邻 add-menu 相关代码），此处不再重复。

/** 加号菜单描述行回填真实状态（每次打开菜单时调用）。
 *  原版描述是死文案（如「本地测试环境未接入云盘」），用户无法判断哪项真能用。 */
export function refreshAddMenu() {
  const kbDesc = $id('am-kb-desc'), memDesc = $id('am-mem-desc'), toolDesc = $id('am-tools-desc');
  const kbItem = document.querySelector('.am-item[data-action="kb"]');
  if (kbDesc) {
    const name = S.kb && S.kb.name;
    kbDesc.textContent = name ? ('当前库：' + name) : '先在「知识库」页选一个库';
    if (kbItem) { if (name) kbItem.removeAttribute('disabled'); else kbItem.setAttribute('disabled', ''); }
  }
  if (memDesc) {
    const n = (S.memCount != null ? S.memCount : null);
    memDesc.textContent = n == null ? '点开查看 Agent 记住了什么' : (n + ' 条记忆 · 点开翻阅');
  }
  if (toolDesc) {
    const m = (TOOL_DATA.material || []).length;
    const s = (TOOL_DATA.skills || []).length;
    toolDesc.textContent = m ? (m + ' 材料工具' + (s ? (' · ' + s + ' 技能') : '')) : '材料工具 · 技能库';
  }
}

export function _bindChatGlobals(opts) {
  if (opts.pickUpload) pickUploadGlobal = opts.pickUpload;
  if (opts.openToolCatalog) openToolCatalogGlobal = opts.openToolCatalog;
  if (opts.queryKb) queryKbGlobal = opts.queryKb;
  if (opts.openMemoryPanel) openMemoryPanelGlobal = opts.openMemoryPanel;
}


/* ── 附件 ─────────────────────────────────────────────── */
export function uploadAttachment(file) {
  const fd = new FormData();
  fd.append('file', file);
  const sid = (S.session && S.session.id) || '';
  fetch('/api/chat/upload?session_id=' + encodeURIComponent(sid), { method: 'POST', body: fd })
    .then(r => r.json())
    .then(d => {
      if (!d || !d.ok) { toast('上传失败：' + ((d && d.detail) || '未知错误'), 'err'); return; }
      if (!S.attachments) S.attachments = [];
      S.attachments.push({ name: d.name, path: d.path, url: d.url });
      renderAttachPreview();
      toast('已添加附件：' + d.name);
    })
    .catch(() => toast('上传失败，请检查服务', 'err'));
}
export function renderAttachPreview() {
  const box = $id('attach-preview'); if (!box) return;
  const atts = S.attachments || [];
  box.style.display = atts.length ? 'flex' : 'none';
  box.innerHTML = atts.map((a, i) =>
    '<div class="attach-pill"><span class="ap-ic">📎</span><span class="ap-name" title="' + esc(a.path) + '">' + esc(a.name) + '</span>' +
    '<span class="ap-x" data-i="' + i + '">✕</span></div>').join('');
  box.querySelectorAll('.ap-x').forEach(x => {
    x.onclick = () => {
      S.attachments.splice(parseInt(x.dataset.i, 10), 1);
      renderAttachPreview();
    };
  });
}
function clearAttachments() {
  S.attachments = [];
  renderAttachPreview();
}


/* ── TOOL_DATA 全局（工具选择器 / 工具中心共享） ──────── */
export let TOOL_DATA = { material: [], general: null, skills: [] };
export function setToolData(d) { TOOL_DATA = d; }
