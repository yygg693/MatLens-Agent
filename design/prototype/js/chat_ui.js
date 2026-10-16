/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat_ui.js
 *
 * 2026-10-15 新增：从 chat.js 抽出的「对话界面增强」模块。
 *
 * 为什么独立成文件：chat.js 已1160 行、单函数 startStream 近 500 行，
 * 继续往里塞会失控。本模块只做**界面增强**，不碰SSE 主循环，
 * 两者通过 DOM 与少量导出函数协作。
 *
 * 本模块负责五件事（对应 A2/A4/A5/A6/A7/A8）：
 *   1. 右侧栏折叠（A2）
 *   2. 空会话引导卡（A4）
 *   3. 状态指示器图标+ 动画（A5）
 *   4. 错误块的重试/ 换模型动作（A6）
 *   5. 工具结果区限高（A7）+ 输入框字数提示（A8）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, S } from './core.js';

/* ══════════════════════════════════════════════════════════
 * 1. 右侧栏折叠（A2）
 * ══════════════════════════════════════════════════════════ */
const SIDE_KEY = 'matlens.chat.sideCollapsed';

export function initSideCollapse() {
  const wrap = document.querySelector('.chat-wrap');
  if (!wrap) return;
  const btnCollapse = $id('chat-side-collapse');
  const btnHandle = $id('chat-side-handle');

  // 恢复上次状态（默认展开）
  let collapsed = false;
  try { collapsed = localStorage.getItem(SIDE_KEY) === '1'; } catch (_) { /* 隐私模式 */ }
  if (collapsed) wrap.classList.add('side-collapsed');

  const apply = (on) => {
    wrap.classList.toggle('side-collapsed', on);
    try { localStorage.setItem(SIDE_KEY, on ? '1' : '0'); } catch (_) { /* ignore */ }
    // 折叠后主线变宽，通知对话流重算（行内图表宽度依赖容器）
    window.dispatchEvent(new Event('resize'));
  };

  if (btnCollapse) btnCollapse.onclick = () => apply(true);
  if (btnHandle) btnHandle.onclick = () => apply(false);

  // 双击右栏边缘 = 快速切换（老用户肌肉记忆）
  wrap.addEventListener('dblclick', (e) => {
    if (!e.target.closest('.chat-right')) return;
    apply(!wrap.classList.contains('side-collapsed'));
  });
}

/* ══════════════════════════════════════════════════════════
 * 2. 空会话引导卡（A4）
 * ══════════════════════════════════════════════════════════ */
/* 示例问题按 MatLens 定位（材料化学科研）挑选，覆盖四类典型用法 */
const STARTERS = [
  { ic: '⚗️', title: '算个材料参数', q: '帮我算一下 LiCoO₂ 的摩尔质量和理论比容量' },
  { ic: '📊', title: '分析我的 XRD 数据', q: '我有一份 XRD 数据，帮我做背景扣除和峰识别' },
  { ic: '🧪', title: '规划实验方案', q: '为 NCM811  cathode 设计一个水热合成方案' },
  { ic: '📚', title: '查文献找依据', q: '在知识库里找钙钛矿稳定性的相关文献并总结' },
];

const CAPS = [
  { ic: '🧪', name: '材料计算', desc: '摩尔质量 / 带隙 / 热力学' },
  { ic: '📉', name: '数据处理', desc: 'XRD / 拟合 / 归一化' },
  { ic: '📄', name: '论文工坊', desc: '7 步生成学术成稿' },
  { ic: '🧠', name: '长期记忆', desc: '跨会话记住你的偏好' },
];

export function renderEmptyState() {
  const stream = $id('chat-stream');
  if (!stream) return;
  if (stream.querySelector('.msg')) return;   // 已有消息，不覆盖
  if (stream.querySelector('.empty-hero')) return; // 已渲染

  const starters = STARTERS.map((s, i) =>
    `<button class="st-card" data-q="${esc(s.q)}">
       <span class="st-ic">${s.ic}</span>
       <span class="st-tx"><b>${esc(s.title)}</b><em>${esc(s.q)}</em></span>
     </button>`).join('');

  const caps = CAPS.map(c =>
    `<button class="cap-card" data-page="${esc(c.ic === '📄' ? 'paper' : c.ic === '🧪' ? 'experiment' : c.ic === '📉' ? 'kb' : 'memory')}">
       <span class="cap-ic">${c.ic}</span><b>${esc(c.name)}</b><em>${esc(c.desc)}</em>
     </button>`).join('');

  stream.innerHTML =
    `<div class="empty-hero">
       <div class="eh-badge">MatLens · 材料之镜</div>
       <h2 class="eh-title">今天想从哪个问题开始？</h2>
       <p class="eh-sub">材料化学科研 Agent · 23 个材料工具 · 186 个技能 · 长期记忆</p>
       <div class="eh-sec">快速开始</div>
       <div class="st-grid">${starters}</div>
       <div class="eh-sec">能力导航</div>
       <div class="cap-grid">${caps}</div>
     </div>`;

  // 点示例 → 填入输入框并直接发送
  stream.querySelectorAll('.st-card').forEach(b => {
    b.onclick = () => {
      const q = b.getAttribute('data-q') || '';
      const inp = $id('input');
      if (inp) { inp.value = q; inp.dispatchEvent(new Event('input')); }
      _sendNow(q);
    };
  });
  // 点能力 → 切页
  stream.querySelectorAll('.cap-card').forEach(b => {
    b.onclick = () => {
      const p = b.getAttribute('data-page');
      const nav = document.querySelector(`.nav-item[data-page="${p}"]`);
      if (nav) nav.click();
    };
  });
}

/* 触发发送：优先用全局 sendMsg，避免与 chat.js 内部状态脱节 */
function _sendNow(text) {
  const inp = $id('input');
  if (inp) inp.value = text;
  if (typeof window.__matlensSend === 'function') window.__matlensSend();
  else {
    // 兜底：派发 Ctrl+Enter 无法直接触发，退化为填入即可
    const s = document.getElementById('btn-send');
    if (s) s.click();
  }
}

/* ══════════════════════════════════════════════════════════
 * 3. 状态指示器（A5）
 * ══════════════════════════════════════════════════════════ */
/* 把纯文字状态升级为「图标 + 呼吸动画 + 颜色」三重编码 */
const STATUS_META = {
  '正在理解问题': { ic: '◎', cls: 'st-think' },
  '思考中': { ic: '✳', cls: 'st-think' },
  '正在生成回答': { ic: '✎', cls: 'st-write' },
  '工具完成，继续分析': { ic: '↻', cls: 'st-write' },
  '就绪': { ic: '●', cls: 'st-idle' },
  '出错了': { ic: '!', cls: 'st-err' },
};

/** 供 chat.js 调用：设置状态并套用图标/动画。 */
export function setChatStatus(text, colorVar) {
  const st = $id('chat-status');
  if (!st) return;
  const meta = STATUS_META[text];
  if (meta) {
    st.innerHTML = `<span class="st-ic ${meta.cls}">${meta.ic}</span><span class="st-tx">${esc(text)}</span>`;
  } else {
    // 未登记的动态文本（如「调用工具：xxx」）——保留纯文本
    st.innerHTML = `<span class="st-ic st-generic">▸</span><span class="st-tx">${esc(text)}</span>`;
  }
  if (colorVar) st.style.color = colorVar;
}

export function initStatus() {
  const st = $id('chat-status');
  if (st) st.innerHTML = '<span class="st-ic st-idle">●</span><span class="st-tx">就绪</span>';
}

/* ══════════════════════════════════════════════════════════
 * 4. 错误块动作按钮（A6）
 * ══════════════════════════════════════════════════════════ */
/** 给错误块挂上「重试 / 换模型」按钮。由 chat.js 的 error 分支调用。 */
export function decorateError(container, rawMsg) {
  if (!container) return;
  const bar = document.createElement('div');
  bar.className = 'err-actions';
  const retry = document.createElement('button');
  retry.className = 'btn btn-ghost btn-sm';
  retry.textContent = '↻ 重试';
  retry.onclick = () => {
    if (typeof window.__matlensRetry === 'function') window.__matlensRetry(rawMsg);
  };
  const sw = document.createElement('button');
  sw.className = 'btn btn-ghost btn-sm';
  sw.textContent = '⇄ 换模型';
  sw.onclick = () => {
    const chip = $id('chip-model');
    if (chip) chip.click();
  };
  bar.appendChild(retry);
  bar.appendChild(sw);
  container.appendChild(bar);
}

/* ══════════════════════════════════════════════════════════
 * 5. 工具结果限高（A7）+ 输入字数提示（A8）
 * ══════════════════════════════════════════════════════════ */
export function initInputCounter() {
  const inp = $id('input');
  if (!inp) return;
  const host = inp.closest('.input-box') || inp.parentElement;
  if (!host || host.querySelector('.input-count')) return;

  const cnt = document.createElement('span');
  cnt.className = 'input-count';
  host.appendChild(cnt);

  const LIMIT = 8000;              // 超过给出视觉提示（后端另有context 检查）
  const WARN = 6000;
  const upd = () => {
    const n = inp.value.length;
    if (!n) { cnt.textContent = ''; cnt.className = 'input-count'; return; }
    cnt.textContent = n > WARN ? `${n} / ${LIMIT}` : String(n);
    cnt.className = 'input-count' + (n > LIMIT ? ' over' : n > WARN ? ' warn' : '');
  };
  inp.addEventListener('input', upd);
  upd();
}

/* ══════════════════════════════════════════════════════════
 * 初始化总入口
 * ══════════════════════════════════════════════════════════ */
export function initChatUI() {
  initSideCollapse();
  initStatus();
  initInputCounter();
  renderEmptyState();
  // 切到对话页时若为空，重渲染引导卡
  document.addEventListener('click', (e) => {
    const nav = e.target.closest && e.target.closest('.nav-item[data-page="chat"]');
    if (nav) setTimeout(renderEmptyState, 120);
  }, true);
}