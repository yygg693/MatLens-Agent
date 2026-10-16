/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat_sse.js
 *
 * 2026-10-15 从 chat.js 抽离：SSE 流式主循环
 *   sendMsg（发送 / 插话）· startStream（建流）· onChatEvent（事件分发）
 *
 * 为什么单独成模块：事件分发是整个前端最长的函数（约 270 行、11 种事件
 * 类型），和输入区/ 工具选择器混在一起时，**任何输入框改动都要在这段里
 * 定位冲突**。抽出后「流式协议」与「输入交互」彻底分开。
 *
 * 依赖注入：滚动 / 冲刷流式缓冲 / 忙碌态 / 清附件 由 chat.js 注入，
 * 避免 chat.js ↔ chat_sse.js 循环依赖。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jpost, renderMarkdown, S, friendlyToolArgs } from './core.js';
import { loadSessions } from './sessions.js';
import { loadMemory } from './graph.js';
import { setChatStatus, decorateError } from './chat_ui.js';
import { loadContextChip, loadModelChip } from './chat_panels.js';
import {
  appendToolCard, resolveToolCard, collectToolLog, updateToolLog,
  appendApprovalCard, renderExecLog, _planSetStatus,
} from './chat_toolcards.js';

let _d = {
  autoScroll: () => {},
  scheduleStreamRender: () => {},
  flushStreamRender: () => {},
  setBusy: () => {},
  hideToolPicker: () => {},
  clearAttachments: () => {},
};

/** 由 chat.js 在initInputTools() 中调用，注入本模块所需的 UI 回调。 */
export function injectSSEDeps(deps) {
  _d = { ..._d, ...(deps || {}) };
}

/* ── 发送消息 / SSE 流式 ───────────────────────────────── */
export function sendMsg() {
  const v0 = $id('input').value.trim();
  const atts = (S.attachments || []).map(a => '[附件：' + a.name + ' → ' + a.path + ']');
  const v = v0 + (atts.length ? '\n\n' + atts.join('\n') : '');
  if (!v0) return;
  S.lastUserMsg = v;          // A6：错误块的「重试」要用
  _d.hideToolPicker();
  const empty = $id('chat-empty');
  if (empty) empty.remove();
  $id('input').value = ''; $id('input').style.height = 'auto';
  _d.clearAttachments();
  $id('chat-stream').insertAdjacentHTML('beforeend',
    '<div class="msg user"><div class="avatar">你</div><div class="msg-body"><div class="bubble">' + esc(v).replace(/\n/g, '<br>') + '</div></div></div>');
  $id('chat-stream').scrollTop = $id('chat-stream').scrollHeight;

  if (S.streaming && S.es && S.session) {
    jpost('/api/chat/redirect', { session_id: S.session.id, message: v }).then(d => {
      if (!(d && d.ok)) {
        if (S.es) { S.es.close(); S.es = null; }
        S._streaming = false;
        document.querySelectorAll('#chat-stream .run-step.running').forEach(s => {
          s.classList.remove('running'); s.classList.add('fail');
          const stx = s.querySelector('.rs-status'); if (stx) stx.textContent = '已打断';
        });
        startStream(v);
      } else {
        const _st = $id('chat-status');
        if (_st && _st.textContent.indexOf('插话') < 0) _st.textContent = '已收到插话，Agent 调整策略继续…';
      }
    });
    return;
  }

  if (!S.session) {
    jpost('/api/sessions', { title: v.slice(0, 18) }).then(d => {
      if (d && d.id) {
        S.session = { id: d.id, title: d.title || '新会话' };
        $id('chat-title').textContent = S.session.title;
        loadSessions(); startStream(v);
      } else { toast('会话创建失败，无法发送', 'err'); _d.setBusy(false); }
    });
  } else { startStream(v); }
}

export function startStream(v) {
  _d.setBusy(true);
  // A6：暴露给 chat_ui 的重试入口（错误块按钮调用）
  window.__matlensRetry = (msg) => {
    const m = (msg || S.lastUserMsg || '').trim();
    if (!m) return;
    const last = document.getElementById('msg-ans');
    if (last) last.remove();
    startStream(m);
  };
  window.__matlensSend = () => sendMsg();
  const oldAns = document.getElementById('msg-ans');
  if (oldAns) oldAns.remove();
  $id('chat-stream').insertAdjacentHTML('beforeend',
    '<div class="msg agent" id="msg-ans"><div class="avatar">ML</div><div class="msg-body"><div class="run-flow" id="run-flow">' +
    '<div class="think-block collapsed thinking" id="initial-think"><div class="think-head"><span class="th-ic th-ic-spin">💭</span><span class="th-label">思考中…</span><span class="th-arrow">▸</span></div><div class="think-body"></div></div>' +
    '</div></div></div>');
  S._initialThink = document.getElementById('initial-think');
  const url = '/api/chat/stream?message=' + encodeURIComponent(v) + '&session_id=' + encodeURIComponent(S.session.id);
  const es = new EventSource(url);
  S.es = es;
  S.toolSeq = 0; S.toolNames = []; S.curText = null; S.curThink = null; S.curTextBuf = ''; S.thinkBuf = ''; S._streaming = true; S._streamRaf = null;
  S.plan = null;
  S.turnSeq = (S.turnSeq || 0) + 1;
  S.curTurn = { turn: S.turnSeq, t0: Date.now(), steps: [] };
  S._recallBlock = null;
  if (!S.execLog) S.execLog = [];
  S.execLog.push(S.curTurn);
  es.onmessage = (e) => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    onChatEvent(d);
    if (d.type === 'done' || d.type === 'error') {
      es.close(); S.es = null;
      loadContextChip(); loadModelChip();
    }
  };
  es.onerror = () => { _d.setBusy(false); if (S.es) { S.es.close(); S.es = null; } toast('连接已断开，回答可能不完整，请重试', 'err'); };
}

function onChatEvent(d) {
  const st = $id('chat-status');
  switch (d.type) {
    case 'turn_start':
      if (st) { setChatStatus('正在理解问题', 'var(--ml-warn)'); }
      break;
    case 'memory_recall': {
      const raw = (d.data && d.data.message) || '';
      const m = /recalled\s*(\d+)/i.exec(raw);
      const n = m ? parseInt(m[1], 10) : 0;
      const flow = document.getElementById('run-flow');
      if (!flow) break;
      if (S._recallBlock && document.body.contains(S._recallBlock)) {
        const prev = parseInt(S._recallBlock.dataset.cnt || '0', 10) || 0;
        const tot = prev + n;
        S._recallBlock.dataset.cnt = String(tot);
        const lbl = S._recallBlock.querySelector('.th-label');
        if (lbl) lbl.textContent = '从记忆想起 ' + tot + ' 条相关内容';
        break;
      }
      const block = document.createElement('div');
      block.className = 'recall-block';
      block.dataset.cnt = String(n);
      const lbl = n > 0 ? ('从记忆想起 ' + n + ' 条相关内容') : '正在调用持久记忆';
      block.innerHTML = '<div class="think-head"><span class="th-ic">🧠</span>' +
        '<span class="th-label">' + lbl + '</span><span class="th-arrow">▸</span></div>' +
        '<div class="th-detail">' + esc(raw) + '</div>';
      block.querySelector('.think-head').onclick = () => {
        block.classList.toggle('open');
        const dd = block.querySelector('.th-detail');
        if (dd) dd.style.display = block.classList.contains('open') ? 'block' : 'none';
      };
      S._recallBlock = block;
      flow.appendChild(block);
      break;
    }
    case 'stream_text': {
      const t = (d.data && d.data.text) || '';
      if (!t) break;
      if (S._initialThink) { S._initialThink.remove(); S._initialThink = null; }
      const flow = $id('run-flow');
      if (!flow) break;
      if (S.curThink && document.body.contains(S.curThink) && S.curThink.classList.contains('thinking')) {
        S.curThink.classList.remove('thinking');
        const ic = S.curThink.querySelector('.th-ic');
        if (ic) ic.classList.remove('th-ic-spin');
        const lbl = S.curThink.querySelector('.th-label');
        if (lbl) lbl.textContent = '已思考（' + (S.thinkBuf || '').length + ' 字）';
      }
      let tb = S.curText;
      if (!tb || !document.body.contains(tb)) {
        tb = document.createElement('div');
        tb.className = 'rf-text';
        flow.appendChild(tb);
        S.curText = tb;
        S.curTextBuf = '';
      }
      S.curTextBuf += t;
      S._streaming = true;
      _d.scheduleStreamRender();
      if (st) { setChatStatus('正在生成回答', 'var(--ml-sky)'); }
      break;
    }
    case 'thinking': {
      const t = (d.data && d.data.text) || '';
      if (!t) break;
      if (S._initialThink) { S._initialThink.remove(); S._initialThink = null; }
      const flow = $id('run-flow');
      if (!flow) break;
      if (!S.curThink || !document.body.contains(S.curThink)) {
        S.curThink = document.createElement('div');
        S.curThink.className = 'think-block collapsed thinking';
        S.curThink.innerHTML = '<div class="think-head"><span class="th-ic th-ic-spin">💭</span><span class="th-label">思考中…</span><span class="th-arrow">▸</span></div><div class="think-body"></div>';
        S.curThink.querySelector('.think-head').onclick = () => {
          S.curThink.classList.toggle('collapsed');
          const ar = S.curThink.querySelector('.th-arrow');
          if (ar) ar.textContent = S.curThink.classList.contains('collapsed') ? '▸' : '▾';
        };
        flow.appendChild(S.curThink);
        S.thinkBuf = '';
      }
      const tb = S.curThink.querySelector('.think-body');
      if (tb) {
        S.thinkBuf += t;
        tb.innerHTML = renderMarkdown(S.thinkBuf);
        if (S.curThink.classList.contains('thinking')) {
          const lbl = S.curThink.querySelector('.th-label');
          if (lbl) lbl.textContent = '思考中…（' + S.thinkBuf.length + ' 字）';
        }
      }
      if (st) { setChatStatus('思考中', 'var(--ml-warn)'); }
      break;
    }
    case 'tool_call':
      if (S.curText) { S._streaming = false; _d.flushStreamRender(); }
      S.curText = null;
      if (S.curThink && document.body.contains(S.curThink)) {
        S.curThink.classList.remove('thinking');
        const ic = S.curThink.querySelector('.th-ic');
        if (ic) ic.classList.remove('th-ic-spin');
        const lbl = S.curThink.querySelector('.th-label');
        if (lbl) lbl.textContent = '已思考（' + (S.thinkBuf || '').length + ' 字）';
      }
      appendToolCard(d.data);
      collectToolLog(d.data);
      const _tname = d.data && d.data.name ? friendlyToolArgs(d.data.name, d.data.args || {}) : '';
      if (st) { setChatStatus('调用工具：' + (_tname.length > 25 ? _tname.slice(0, 25) + '…' : _tname), 'var(--ml-warn)'); }
      break;
    case 'tool_result':
      resolveToolCard(d.data);
      updateToolLog(d.data);
      if (d.data && d.data.status !== 'error') {
        if (st) { setChatStatus('工具完成，继续分析', 'var(--ml-sky)'); }
      }
      break;
    case 'approval_request':
      appendApprovalCard(d.data);
      break;
    case 'done':
      if (S.curText) { S._streaming = false; _d.flushStreamRender(); }
      S.curText = null;
      document.querySelectorAll('#run-flow .run-step.running').forEach(s => {
        s.classList.remove('running'); s.classList.add('fail');
        const stx = s.querySelector('.rs-status'); if (stx) stx.textContent = '✕ 失败';
        if (s.dataset.planIdx) _planSetStatus(parseInt(s.dataset.planIdx, 10), 'fail');
        const det = s.querySelector('.run-step-detail');
        if (det) det.insertAdjacentHTML('beforeend', '<div class="run-result fail">✕ 执行失败 · 工具重试后仍无有效结果</div>');
      });
      if (st) { setChatStatus('就绪', 'var(--ml-text-faint)'); }
      if (S.execPanelOpen) renderExecLog();
      _d.setBusy(false);
      if (S.session) loadSessions();
      if (!S.memHinted) {
        S.memHinted = true;
        const flow = document.getElementById('run-flow');
        if (flow) {
          const mb = document.createElement('div');
          mb.className = 'recall-block';
          mb.innerHTML = '<div class="think-head"><span class="th-ic">🧠</span>' +
            '<span class="th-label">本轮内容已进入长期记忆沉淀</span><span class="th-arrow">▸</span></div>' +
            '<div class="th-detail">对话结束后，Mem0 会自动提取值得记住的信息（研究方向、偏好、结论）存入长期记忆，后续对话中会主动回忆并自然引用——这是 Hermes 的自我成长机制。可在右侧「记忆」标签查看沉淀结果。</div>';
          mb.querySelector('.think-head').onclick = () => {
            mb.classList.toggle('open');
            const dd = mb.querySelector('.th-detail');
            if (dd) dd.style.display = mb.classList.contains('open') ? 'block' : 'none';
          };
          flow.appendChild(mb);
        }
      }
      setTimeout(() => {
        const pg = document.getElementById('page-chat');
        if (pg && pg.classList.contains('active')) loadMemory().catch(() => {});
      }, 2500);
      break;
    case 'error': {
      if (S.curText) { S._streaming = false; _d.flushStreamRender(); }
      S.curText = null;
      const rawErr = String((d.data && d.data.message) || (d.data && d.data.error) || '未知错误');
      let friendly = rawErr;
      if (/429|rate.?limit|too many requests|限流/i.test(rawErr)) friendly = '模型服务繁忙（限流），请稍后重试或切换到其他模型/Provider。';
      else if (/timeout|timed out|超时/i.test(rawErr)) friendly = '请求超时，可能是网络不稳定或模型响应慢。请检查网络后重试，或在设置中切换更快的模型。';
      else if (/api.?key|invalid.*key|unauthorized|401/i.test(rawErr)) friendly = 'API Key 无效或已过期，请在「设置」页面检查并重新配置 API Key。';
      else if (/model.*not.*found|model.*does not exist|model.*unavailable|404/i.test(rawErr)) friendly = '当前模型不可用，请在「设置」页面切换到其他模型。';
      else if (/network|fetch|ECONNREFUSED|connection.*refused|连接/i.test(rawErr)) friendly = '网络连接失败，请检查网络连接后重试。';
      else if (/context.*length|context.*window|token.*limit|too long/i.test(rawErr)) friendly = '对话上下文过长，请开启新会话或减少输入内容后重试。';
      else if (/insufficient.*quota|quota.*exceeded|billing|余额/i.test(rawErr)) friendly = 'API 额度不足或欠费，请在 Provider 平台充值或更换 API Key。';
      if (st) { setChatStatus('出错了', 'var(--ml-danger)'); }
      const flow2 = $id('run-flow');
      if (flow2) {
        const eb = document.createElement('div');
        eb.className = 'rf-text rf-error';
        eb.innerHTML = '<div style="font-weight:600;margin-bottom:4px">⚠ ' + esc(friendly) + '</div>' +
          (friendly !== rawErr ? '<div style="font-size:11px;color:var(--ml-text-faint);margin-top:4px">原始错误：' + esc(rawErr.slice(0, 200)) + '</div>' : '');
        flow2.appendChild(eb);
        // A6：挂上「重试 / 换模型」动作，否则用户只能重新打字
        decorateError(eb, S.lastUserMsg || '');
      }
      _d.setBusy(false);
      break;
    }
  }
  _d.autoScroll();
}

/* ── 停止生成 ────────────────────────────────────────────
   与 sendMsg / startStream 同属 SSE 生命周期，故随本模块（2026-10-15）。 */
export function stop() {
  if (S.es) { S.es.close(); S.es = null; }
  if (S._streamRaf) { cancelAnimationFrame(S._streamRaf); S._streamRaf = null; }
  S._streaming = false;
  if (S.curText) { _d.flushStreamRender(); }
  S.curText = null;
  S.curThink = null;
  let stopped = 0;
  document.querySelectorAll('#run-flow .run-step.running').forEach(s => {
    s.classList.remove('running'); s.classList.add('fail');
    const st = s.querySelector('.rs-status'); if (st) st.textContent = '已停止';
    if (s.dataset.planIdx) _planSetStatus(parseInt(s.dataset.planIdx, 10), 'stopped', '已停止');
    stopped++;
  });
  _d.setBusy(false);
  toast(stopped > 0 ? ('已停止生成（' + stopped + ' 个工具调用中断）') : '已停止生成');
}
