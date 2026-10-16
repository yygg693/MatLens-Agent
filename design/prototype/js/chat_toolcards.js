/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat_toolcards.js
 *
 * 2026-10-15 从 chat.js 抽离：工具结果渲染 / 执行计划卡 / 工具卡 /
 * 审批卡 / 执行日志侧栏
 *
 * 为什么抽这块：这三块共享同一套视觉语言（步骤条、状态徽标、结果区），
 * 放在一起便于统一改样式；且它们**不参与 SSE 事件分发**——
 * onChatEvent 只调用它们，不被它们调用，抽离不触碰流式主循环。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, S, TOOL_ICON, friendlyToolArgs } from './core.js';
import { setChatStatus } from './chat_ui.js';

/* ══════════════════════════════════════════════════════════
 * 依赖注入：避免与 chat.js 形成循环依赖
 * ══════════════════════════════════════════════════════════
 * 本模块需要 chat.js 的 4 个东西（滚动到底部 / 冲刷流式缓冲 / 结束忙碌态 /
 * 从执行日志跳回对话流定位工具卡）。直接 import 会造成
 * chat.js ↔ chat_toolcards.js 循环依赖（ESM 下会拿到 undefined）。
 *
 * 解决：chat.js 在import 本模块后调用 :func:`injectChatDeps` 注入这些引用。
 * 未注入时全部退化为安全空操作 —— 保证模块可独立加载、不因顺序出错。
 */
let _deps = {
  autoScroll: () => {},
  flushStreamRender: () => {},
  setBusy: () => {},
  onLogLocate: () => {},
};

export function injectChatDeps(d) {
  _deps = { ..._deps, ...(d || {}) };
}

/* ── 工具结果渲染 ─────────────────────────────────────── */
function _renderToolResult(container, result, status) {
  const isOk = status !== 'fail';
  const resultText = String(result || '');
  const isJson = resultText.trim().startsWith('{') || resultText.trim().startsWith('[');
  let displayText = resultText;
  if (isJson) {
    try { displayText = JSON.stringify(JSON.parse(resultText), null, 2); } catch (_) {}
  }
  const TRUNC = 600;
  const truncated = displayText.length > TRUNC;
  const shown = truncated ? displayText.slice(0, TRUNC) : displayText;
  const statusHtml = '<div class="run-result ' + (isOk ? 'ok' : 'fail') + '">' + (isOk ? '✓ 执行成功' : '✕ 执行失败') + '</div>';
  const labelHtml = '<div class="t-label" style="margin-top:4px">执行结果 · Observation' + (truncated ? '（共 ' + displayText.length + ' 字符）' : '') + '</div>';
  const preHtml = '<pre class="tool-result-pre">' + esc(shown) + '</pre>';
  const moreHtml = truncated
    ? '<button class="btn btn-ghost btn-sm tool-result-more" style="margin-top:6px">查看全部 ' + displayText.length + ' 字符</button>'
    : '';
  container.insertAdjacentHTML('beforeend', statusHtml + labelHtml + preHtml + moreHtml);
  if (truncated) {
    const btn = container.querySelector('.tool-result-more');
    const pre = container.querySelector('.tool-result-pre');
    if (btn && pre) {
      btn.onclick = () => {
        if (pre.dataset.expanded === '1') {
          pre.textContent = shown;
          pre.dataset.expanded = '0';
          btn.textContent = '查看全部 ' + displayText.length + ' 字符';
        } else {
          pre.textContent = displayText;
          pre.dataset.expanded = '1';
          btn.textContent = '收起';
        }
      };
    }
  }
}

/* ── 执行计划卡 ───────────────────────────────────────── */
function _ensurePlanCard() {
  if (S.plan && S.plan.card && document.body.contains(S.plan.card)) return S.plan.card;
  const flow = $id('run-flow');
  if (!flow) return null;
  const card = document.createElement('div');
  card.className = 'plan-track';
  card.innerHTML = '<div class="plan-head"><span class="pl-ic">📋</span><span class="pl-title">任务计划</span>' +
    '<span class="pl-summary">正在规划…</span><span class="pl-progress"></span><span class="pl-arrow">▸</span></div>' +
    '<div class="plan-body"></div>';
  card.querySelector('.plan-head').onclick = () => {
    card.classList.toggle('open');
    const ar = card.querySelector('.pl-arrow');
    if (ar) ar.textContent = card.classList.contains('open') ? '▾' : '▸';
  };
  flow.insertBefore(card, flow.firstChild);
  S.plan = { card: card, steps: [] };
  return card;
}
function _planAddStep(name, friendly) {
  const card = _ensurePlanCard();
  if (!card) return -1;
  const idx = S.plan.steps.length;
  const body = card.querySelector('.plan-body');
  const step = document.createElement('div');
  step.className = 'plan-step running';
  step.innerHTML = '<span class="pl-idx">' + (idx + 1) + '</span>' +
    '<span class="pl-name" title="' + esc(friendly) + '">' + esc(friendly) + '</span>' +
    '<span class="pl-status">运行中</span>';
  body.appendChild(step);
  S.plan.steps.push({ name: name, friendly: friendly, status: 'running', el: step });
  _planUpdateSummary();
  return idx;
}
export function _planSetStatus(idx, status, label) {
  if (!S.plan || !S.plan.steps[idx]) return;
  const s = S.plan.steps[idx];
  s.status = status;
  s.el.className = 'plan-step ' + status;
  const stx = s.el.querySelector('.pl-status');
  if (stx) stx.textContent = label || (status === 'ok' ? '✓ 完成' : status === 'fail' ? '✕ 失败' : status === 'stopped' ? '已停止' : '运行中');
  _planUpdateSummary();
}
function _planUpdateSummary() {
  if (!S.plan || !S.plan.card) return;
  const steps = S.plan.steps;
  const sum = S.plan.card.querySelector('.pl-summary');
  const prog = S.plan.card.querySelector('.pl-progress');
  if (!steps.length) {
    if (sum) sum.textContent = '正在规划…';
    if (prog) prog.textContent = '';
    return;
  }
  const done = steps.filter(s => s.status !== 'running').length;
  const running = steps.filter(s => s.status === 'running').length;
  if (sum) sum.textContent = '已完成 ' + done + ' / ' + steps.length + ' 步' + (running ? ' · ' + running + ' 进行中' : '');
  if (prog) prog.textContent = steps.length + ' 步';
}

/* ── 工具卡 ───────────────────────────────────────────── */
export function appendToolCard(data) {
  const name = data && data.name || 'tool';
  const args = data && data.args || {};
  const callId = data && data.call_id || '';
  const argsJson = JSON.stringify(args);
  const argsHtml = esc(argsJson);
  const flow = $id('run-flow');
  if (!flow) return;
  if (!callId) {
    const merged = [...flow.querySelectorAll('.run-step.running')]
      .find(s => s.dataset.tname === name && s.dataset.targs === argsJson);
    if (merged) {
      const n = (parseInt(merged.dataset.count || '1', 10) || 1) + 1;
      merged.dataset.count = n;
      const nm = merged.querySelector('.rs-name');
      if (nm) nm.textContent = name + ' ×' + n;
      return;
    }
  }
  const i = ++S.toolSeq;
  S.toolNames.push(name);
  const step = document.createElement('div');
  step.className = 'run-step running';
  step.dataset.toolcard = i;
  step.dataset.tname = name;
  step.dataset.targs = argsJson;
  step.dataset.count = '1';
  if (callId) step.dataset.callId = callId;
  const friendly = friendlyToolArgs(name, args);
  step.dataset.t0 = String(Date.now());
  step.dataset.planIdx = String(_planAddStep(name, friendly));
  step.innerHTML = '<span class="rs-icon">' + (TOOL_ICON[name] || '⚙') + '</span>' +
    '<span class="rs-name" title="' + esc(friendly) + '">' + esc(friendly) + '</span>' +
    '<span class="rs-status">运行中</span>' +
    '<span class="rs-arrow">▸</span>';
  step.onclick = () => {
    const detail = step.querySelector('.run-step-detail');
    const arrow = step.querySelector('.rs-arrow');
    if (detail) { detail.remove(); step.classList.remove('open'); if (arrow) arrow.textContent = '▸'; return; }
    step.classList.add('open'); if (arrow) arrow.textContent = '▾';
    const dd = document.createElement('div');
    dd.className = 'run-step-detail';
    const n = parseInt(step.dataset.count || '1', 10);
    dd.innerHTML = '<div class="t-label">操作描述</div><div style="font-size:12.5px;color:var(--ml-text);margin-bottom:8px">' + esc(friendlyToolArgs(name, JSON.parse(step.dataset.targs || '{}'))) + '</div>' +
      '<div class="t-label">原始参数 · Action</div><pre>' + argsHtml.slice(0, 400) + '</pre>' +
      (n > 1 ? '<div class="t-label" style="margin-top:7px">重试 ' + n + ' 次</div>' : '');
    const res = step.dataset.result;
    if (res) _renderToolResult(dd, res, step.classList.contains('fail') ? 'fail' : 'ok');
    step.appendChild(dd);
  };
  flow.appendChild(step);
  _deps.autoScroll();
}

export function resolveToolCard(data) {
  const callId = data && data.call_id || '';
  const steps = document.querySelectorAll('.run-step.running');
  let target = null;
  if (callId) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].dataset.callId === callId) { target = steps[i]; break; }
    }
  }
  if (!target) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].dataset.tname === data.name) { target = steps[i]; break; }
    }
  }
  if (!target) return;
  const s = target;
  const st = s.querySelector('.rs-status');
  if (data.status === 'error') {
    const failCount = (parseInt(s.dataset.failCount || '0', 10) || 0) + 1;
    s.dataset.failCount = String(failCount);
    let errMsg = String(data.result || '').replace(/^ERROR:\s*/, '').slice(0, 80);
    if (st) st.innerHTML = '<span style="color:var(--ml-danger)">重试中…(' + failCount + ')</span>';
    const detail = s.querySelector('.run-step-detail');
    if (detail && !detail.querySelector('.tool-error')) {
      detail.insertAdjacentHTML('beforeend',
        '<div class="tool-error" style="color:var(--ml-danger);font-size:11.5px;margin-top:6px">⚠ ' + esc(errMsg) + '</div>');
    }
    if (failCount >= 3) {
      s.classList.remove('running');
      s.classList.add('fail');
      if (st) st.textContent = '✕ 失败';
      s.dataset.result = 'ERROR: ' + errMsg;
      if (s.dataset.planIdx) _planSetStatus(parseInt(s.dataset.planIdx, 10), 'fail');
    }
    return;
  }
  s.dataset.failCount = '0';
  s.classList.remove('running');
  s.classList.add('ok');
  const t0 = parseInt(s.dataset.t0 || '0', 10);
  const dur = t0 ? ((Date.now() - t0) / 1000).toFixed(1) + 's' : '';
  if (st) {
    st.textContent = (['memory', 'mem0_add'].indexOf(s.dataset.tname || '') > -1 ? '✓ 已写入记忆' : '✓ 完成') + (dur ? ' · ' + dur : '');
  }
  if (s.dataset.planIdx) _planSetStatus(parseInt(s.dataset.planIdx, 10), 'ok', '✓ 完成' + (dur ? ' · ' + dur : ''));
  const fullResult = String(data.result || '').slice(0, 5000);
  s.dataset.result = fullResult;
  const detail = s.querySelector('.run-step-detail');
  if (detail) _renderToolResult(detail, fullResult, 'ok');
  _deps.autoScroll();
}

export function appendApprovalCard(data) {
  const rid = data.request_id, tool = data.tool, args = data.args || {};
  const friendly = friendlyToolArgs(tool, args);
  let argsPretty = JSON.stringify(args, null, 2);
  if (argsPretty.length > 500) argsPretty = argsPretty.slice(0, 500) + '\n…(截断)';
  const argsHtml = esc(argsPretty);
  $id('chat-stream').insertAdjacentHTML('beforeend',
    '<div class="msg agent"><div class="avatar">ML</div><div class="msg-body">' +
    '<div class="approval-card" data-rid="' + rid + '">' +
    '<div class="approval-head">' +
    '<svg viewBox="0 0 24 24"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>' +
    '需要审批 · ' + esc(friendly) +
    '<span class="approval-timer" style="margin-left:auto;font-size:11px;color:var(--ml-warn)">60s</span></div>' +
    '<div class="approval-detail"><pre style="margin:0;font-size:11.5px;white-space:pre-wrap;word-break:break-word">' + argsHtml + '</pre></div>' +
    '<div style="font-size:12px;color:var(--ml-text-dim)">该工具调用需要您确认后才会执行，<span class="approval-timeout-hint">60 秒</span>后自动拒绝。</div>' +
    '<div class="approval-risk">风险：中 · 请确认工具与参数</div>' +
    '<div class="approval-actions">' +
    '<button class="btn btn-primary" data-approve="' + rid + '">✓ 批准执行</button>' +
    '<button class="btn btn-danger" data-deny="' + rid + '">✕ 拒绝</button>' +
    '</div></div></div></div>');
  const card = document.querySelector('.approval-card[data-rid="' + rid + '"]');
  if (card) {
    card.querySelector('[data-approve]').addEventListener('click', () => respondApproval(rid, 'approve', card));
    card.querySelector('[data-deny]').addEventListener('click', () => respondApproval(rid, 'deny', card));
    let remain = 60;
    const timerEl = card.querySelector('.approval-timer');
    const hintEl = card.querySelector('.approval-timeout-hint');
    const tick = setInterval(() => {
      remain--;
      if (timerEl) timerEl.textContent = remain + 's';
      if (hintEl) hintEl.textContent = remain + ' 秒';
      if (remain <= 10) {
        card.classList.add('approval-urgent');
        if (timerEl) timerEl.style.color = 'var(--ml-danger)';
      }
      if (remain <= 0) {
        clearInterval(tick);
        if (timerEl) timerEl.textContent = '已超时';
      }
    }, 1000);
    card._approvalTimer = tick;
  }
  _deps.autoScroll();
}

async function respondApproval(rid, decision, card) {
  if (card && card._approvalTimer) { clearInterval(card._approvalTimer); card._approvalTimer = null; }
  const d = await jpost('/api/approvals/' + rid + '/respond', { decision: decision });
  if (card) {
    const btns = card.querySelectorAll('.approval-actions button');
    btns.forEach(b => b.disabled = true);
    card.classList.remove('approval-urgent');
    const head = card.querySelector('.approval-head');
    if (head) {
      const timer = head.querySelector('.approval-timer');
      if (timer) timer.remove();
      head.textContent = (decision === 'approve' ? '✓ 已批准' : '✕ 已拒绝') + ' · ' + (head.textContent || '').replace(/^.*?·\s*/, '');
    }
  }
  toast(d && d.ok ? (decision === 'approve' ? '已批准执行' : '已拒绝执行') : '回传失败：' + (d && d.detail || ''), d && d.ok ? '' : 'err');
}

/* ── 执行日志侧栏 ─────────────────────────────────────── */
export function collectToolLog(data) {
  if (!S.curTurn) return;
  const name = (data && data.name) || 'tool';
  const args = (data && data.args) || {};
  const callId = (data && data.call_id) || '';
  const steps = S.curTurn.steps;
  if (!callId && steps.length) {
    const last = steps[steps.length - 1];
    if (last.name === name && last.status === 'running' && JSON.stringify(last.args) === JSON.stringify(args)) {
      last.count = (last.count || 1) + 1;
      return;
    }
  }
  steps.push({
    name: name, args: args, call_id: callId,
    friendly: friendlyToolArgs(name, args),
    t0: Date.now(), status: 'running', count: 1,
    toolcardId: S.toolSeq
  });
  if (S.execPanelOpen) renderExecLog();
}
export function updateToolLog(data) {
  if (!S.curTurn) return;
  const name = (data && data.name) || 'tool';
  const callId = (data && data.call_id) || '';
  const steps = S.curTurn.steps;
  let t = null;
  if (callId) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].call_id === callId && steps[i].status === 'running') { t = steps[i]; break; }
    }
  }
  if (!t) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].name === name && steps[i].status === 'running') { t = steps[i]; break; }
    }
  }
  if (!t) return;
  t.status = (data && data.status === 'error') ? 'fail' : 'ok';
  t.dur = t.t0 ? ((Date.now() - t.t0) / 1000).toFixed(1) : '';
  t.result = String((data && data.result) || '').slice(0, 4000);
  if (data && data.status === 'error') t.error = String(data.result || '').replace(/^ERROR:\s*/, '').slice(0, 200);
  if (S.execPanelOpen) renderExecLog();
}
export function openExecLog() {
  S.execPanelOpen = true;
  const p = $id('exec-panel'); if (p) p.classList.add('show');
  const m = $id('exec-mask'); if (m) m.classList.add('show');
  const b = $id('btn-exec-log'); if (b) b.classList.add('active');
  renderExecLog();
}
export function closeExecLog() {
  S.execPanelOpen = false;
  const p = $id('exec-panel'); if (p) p.classList.remove('show');
  const m = $id('exec-mask'); if (m) m.classList.remove('show');
  const b = $id('btn-exec-log'); if (b) b.classList.remove('active');
}
export function renderExecLog() {
  const body = $id('exec-body'); if (!body) return;
  const log = S.execLog || [];
  let tot = 0; log.forEach(tr => { tot += (tr.steps || []).length; });
  const sum = $id('exec-summary');
  if (sum) sum.textContent = log.length + ' 轮 · ' + tot + ' 次调用';
  if (!log.length) {
    body.innerHTML = '<div class="ep-empty">暂无执行日志 — 发送问题后，Agent 的工具调用会实时记录在这里。</div>';
    return;
  }
  body.innerHTML = '';
  log.forEach(tr => {
    const turn = document.createElement('div');
    turn.className = 'ep-turn open';
    let okc = 0, runc = 0, failc = 0;
    tr.steps.forEach(st => { if (st.status === 'ok') okc++; else if (st.status === 'fail') failc++; else runc++; });
    const t = new Date(tr.t0 || Date.now());
    turn.innerHTML = '<div class="ep-turn-head"><span class="eth-arrow">▸</span><span class="eth-t">第 ' + tr.turn + ' 轮</span>' +
      '<span class="eth-meta">' + okc + '✓ ' + failc + '✕ ' + (runc ? runc + '…' : '') + ' · ' + t.toTimeString().slice(0, 8) + '</span></div>' +
      '<div class="ep-turn-body"></div>';
    const tbody = turn.querySelector('.ep-turn-body');
    turn.querySelector('.ep-turn-head').addEventListener('click', () => turn.classList.toggle('open'));
    tr.steps.forEach(st => tbody.appendChild(_execStepEl(st)));
    body.appendChild(turn);
  });
}
function _execStepEl(st) {
  const el = document.createElement('div');
  el.className = 'ep-step ' + st.status;
  const statusTxt = st.status === 'ok' ? ('✓ 完成' + (st.dur ? ' · ' + st.dur + 's' : ''))
    : st.status === 'fail' ? '✕ 失败' : '运行中…';
  el.innerHTML = '<div class="ep-step-head"><span class="es-ic">' + (TOOL_ICON[st.name] || '⚙') + '</span>' +
    '<span class="es-name" title="' + esc(st.friendly || st.name) + '">' + esc(st.friendly || st.name) + '</span>' +
    '<span class="es-status">' + statusTxt + '</span>' +
    '<span class="es-loc" title="在对话流中定位该调用" style="flex:none;font-size:11px;cursor:pointer;color:var(--ml-text-faint);padding:2px 4px;border-radius:5px">⌖</span></div>' +
    '<div class="ep-step-detail"></div>';
  const head = el.querySelector('.ep-step-head');
  const det = el.querySelector('.ep-step-detail');
  head.addEventListener('click', (ev) => {
    if (ev.target.classList.contains('es-loc')) return;
    const open = el.classList.toggle('open');
    if (open) {
      det.innerHTML = '<div class="ep-dl">入参 · Action</div><pre class="ep-pre">' + esc(JSON.stringify(st.args, null, 2).slice(0, 800)) + '</pre>' +
        (st.result ? '<div class="ep-dl" style="margin-top:5px">出参 · Observation</div><pre class="ep-pre">' + esc(st.result.slice(0, 800)) + '</pre>' : '') +
        (st.error ? '<div class="ep-dl" style="margin-top:5px;color:var(--ml-danger)">错误</div><pre class="ep-pre" style="color:var(--ml-danger)">' + esc(st.error) + '</pre>' : '') +
        (st.count > 1 ? '<div class="ep-dl" style="margin-top:5px">自动重试 ' + st.count + ' 次</div>' : '');
    }
  });
  el.querySelector('.es-loc').addEventListener('click', (ev) => {
    ev.stopPropagation();
    const card = document.querySelector('.run-step[data-toolcard="' + st.toolcardId + '"]');
    if (card) {
      closeExecLog();
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.add('hl');
      setTimeout(() => card.classList.remove('hl'), 1600);
    }
  });
  return el;
}

