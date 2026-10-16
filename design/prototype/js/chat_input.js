/* ═══════════════════════════════════════════════════════════════
 * MatLens前端 · chat_input.js
 *
 * 2026-10-15 从 chat.js 抽离：输入框增强
 *
 * 修掉的实测缺陷（都是 playwright量出来的，不是推测）：
 *   P0-1自动增高完全失效——8 行文本高度恒为 22px。原代码只在
 *         「@工具选中后」执行增高（chat.js旧 118 行），普通 input 事件不调。
 *   P0-2 @ 选择器只搜材料工具（23 个），186 个 skill 完全搜不到；
 *         且硬编码slice(0,12) 截断且无提示。
 *   N1   输入框不支持粘贴 / 拖入图片（科研场景：截图 XRD 直接问）
 *   N3   草稿不持久化 —— 切会话/切页/误刷新就没了
 *   N4   无输入历史 —— 科研常重复问同类问题
 *
 * 设计原则：全部为**附加能力**，不改变原有 sendMsg / @插入语义；
 * 任一能力初始化失败都不影响输入框基本使用。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, S } from './core.js';

const MAX_H = 150;          // textarea 最大高度（与 CSS max-height 一致）
const DRAFT_KEY = 'matlens.chat.drafts';
const HIST_KEY = 'matlens.chat.history';
const HIST_MAX = 30;

/* ══════════════════════════════════════════════════════════
 * P0-1 自动增高
 * ══════════════════════════════════════════════════════════ */
/** 按内容调整 textarea 高度（矮→高，超出封顶后由 textarea 内部滚动）。 */
export function autoGrow(input) {
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, MAX_H) + 'px';
  // 贴到上限时给父级加个标记，便于样式提示"还能继续滚"
  const box = input.closest('.input-box');
  if (box) box.classList.toggle('at-max', input.scrollHeight > MAX_H);
}

/* ══════════════════════════════════════════════════════════
 * N3 草稿持久化（按会话隔离）
 * ══════════════════════════════════════════════════════════ */
function _draftKey() {
  const sid = (S.session && S.session.id) || '_new';
  return sid;
}
function _readAllDrafts() {
  try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') || {}; }
  catch (_) { return {}; }
}
export function saveDraft() {
  const inp = $id('input');
  if (!inp) return;
  try {
    const all = _readAllDrafts();
    const v = inp.value;
    if (v && v.trim()) all[_draftKey()] = { text: v, at: Date.now() };
    else delete all[_draftKey()];
    localStorage.setItem(DRAFT_KEY, JSON.stringify(all));
  } catch (_) { /* 隐私模式/ 超额：静默 */ }
}
export function restoreDraft() {
  const inp = $id('input');
  if (!inp) return;
  try {
    const all = _readAllDrafts();
    const d = all[_draftKey()];
    // 仅在用户没开始输入时恢复，避免覆盖现场
    if (d && d.text && !inp.value.trim()) {
      inp.value = d.text;
      autoGrow(inp);
    }
  } catch (_) { /* ignore */ }
}

/* ══════════════════════════════════════════════════════════
 * N4 输入历史（↑↓ 调回）
 * ══════════════════════════════════════════════════════════ */
function _readHistory() {
  try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]') || []; }
  catch (_) { return []; }
}
export function pushHistory(text) {
  const t = (text || '').trim();
  if (!t) return;
  try {
    let h = _readHistory().filter(x => x !== t);   // 去重 + 最新的在后
    h.push(t);
    if (h.length > HIST_MAX) h = h.slice(-HIST_MAX);
    localStorage.setItem(HIST_KEY, JSON.stringify(h));
  } catch (_) { /* ignore */ }
}
function _histStep(input, dir) {
  const h = _readHistory();
  if (!h.length) return false;
  const cur = input.value;
  // 首次按 ↑ 且当前不在历史里 → 从最后一条开始
  let idx = h.indexOf(cur);
  idx = idx < 0 ? (dir < 0 ? h.length : 0) : idx + dir;
  if (idx < 0) idx = 0;
  if (idx >= h.length) idx = h.length - 1;
  input.value = h[idx] || '';
  autoGrow(input);
  // 光标移到末尾
  const n = input.value.length;
  try { input.setSelectionRange(n, n); } catch (_) { /* ignore */ }
  return true;
}

/* ══════════════════════════════════════════════════════════
 * N1 图片粘贴 / 拖入
 * ══════════════════════════════════════════════════════════ */
const IMG_EXT = /\.(png|jpe?g|gif|webp|bmp)$/i;

function _attachFiles(files) {
  if (!files || !files.length) return;
  const list = Array.from(files);
  const imgs = list.filter(f => (f.type || '').startsWith('image/') || IMG_EXT.test(f.name || ''));
  if (!imgs.length) {
    toast('仅支持粘贴图片（如 XRD/SEM 截图）', 'warn');
    return;
  }
  const uploader = window.ML && window.ML.uploadAttachment;
  if (typeof uploader !== 'function') {
    toast('附件上传未就绪', 'err');
    return;
  }
  imgs.slice(0, 4).forEach(f => uploader(f));   // 一次最多 4 张，避免刷屏
}

export function initImageDrop() {
  const wrap = document.querySelector('.input-box-wrap') || document.querySelector('.chat-input');
  const inp = $id('input');
  if (!wrap || !inp) return;

  // 拖入
  ['dragenter', 'dragover'].forEach(ev =>
    wrap.addEventListener(ev, e => {
      if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes('Files')) return;
      e.preventDefault();
      wrap.classList.add('drop-active');
    }));
  ['dragleave', 'drop'].forEach(ev =>
    wrap.addEventListener(ev, e => {
      if (e.target === wrap || wrap.contains(e.target)) { /*内部移动不取消 */ }
      else wrap.classList.remove('drop-active');
    }));
  wrap.addEventListener('drop', e => {
    e.preventDefault();
    wrap.classList.remove('drop-active');
    _attachFiles(e.dataTransfer && e.dataTransfer.files);
  });

  // 粘贴：仅当焦点在输入框内才拦截，避免抢走别处的复制
  inp.addEventListener('paste', e => {
    const dt = e.clipboardData;
    if (!dt) return;
    const hasFile = Array.from(dt.items || []).some(i => i.kind === 'file');
    if (!hasFile) return;
    e.preventDefault();
    const files = Array.from(dt.files || []);
    if (files.length) _attachFiles(files);
  });
}

/* ══════════════════════════════════════════════════════════
 * 键盘：↑↓ 历史 · 其余交给原有绑定
 * ══════════════════════════════════════════════════════════ */
export function initInputKeys() {
  const inp = $id('input');
  if (!inp) return;

  // @ 选择器打开时，先让它吃 ↑↓/Enter/Esc（否则这些键会被"发送消息"抢走）
  inp.addEventListener('keydown', e => {
    try {
      if (window.ML && typeof window.ML.toolPickerKey === 'function'
        && window.ML.toolPickerKey(e)) {
        return;
      }
    } catch (_) { /* 忽略 */ }
  }, true);   // 捕获阶段：必须早于 app.js 覆盖层的绑定

  inp.addEventListener('keydown', e => {
    // ↑↓ 仅在「光标在首/末行」且「本轮没输入过东西」时接管，否则用于移动光标
    const atStart = inp.selectionStart === 0 && inp.selectionEnd === 0;
    const atEnd = inp.selectionStart === inp.value.length;
    if (e.key === 'ArrowUp' && (atStart || !inp.value.trim())) {
      if (_histStep(inp, -1)) e.preventDefault();
    } else if (e.key === 'ArrowDown' && atEnd) {
      if (_histStep(inp, 1)) e.preventDefault();
    }
  });
  // 离开输入框即存草稿（切会话/切页都会触发 blur）
  inp.addEventListener('blur', saveDraft);
}

/* ══════════════════════════════════════════════════════════
 * 初始化
 * ══════════════════════════════════════════════════════════ */
export function initInputEnhance() {
  const inp = $id('input');
  if (!inp) return;

  // P0-1：把自动增高挂到 input 事件（这是修复的关键 —— 之前完全没有）
  inp.addEventListener('input', () => {
    autoGrow(inp);
    saveDraft();
  });

  initImageDrop();
  initInputKeys();
  autoGrow(inp);
  restoreDraft();
}

/** 供 sendMsg 成功后调用：清空输入 + 记入历史。 */
export function afterSend() {
  const inp = $id('input');
  if (!inp) return;
  pushHistory(inp.value);
  inp.value = '';
  autoGrow(inp);
  const box = inp.closest('.input-box');
  if (box) box.classList.remove('at-max');
  saveDraft();
}

/** 会话切换时调用：换草稿。 */
export function onSessionSwitch() {
  const inp = $id('input');
  if (!inp) return;
  inp.value = '';
  autoGrow(inp);
  restoreDraft();
}