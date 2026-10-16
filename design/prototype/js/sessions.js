/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · sessions.js（会话列表 / 历史消息回放 / 新建/重命名/删除）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, renderMarkdown, jget, jpost, jput, jdel, S, TOOL_ICON } from './core.js';

/* 切换并高亮「智能对话」页面（供历史会话选择时直接跳转） */
export function _gotoChatPage() {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const cn = document.querySelector('.nav-item[data-page="chat"]');
  if (cn) cn.classList.add('active');
  const cp = document.getElementById('page-chat');
  if (cp) cp.classList.add('active');
}

/* ── 会话列表（三态：loading / empty / error） ────────── */
/* 2026-10-15：新增「归档箱」视图切换 + 归档/恢复能力。
   归档入口放在**侧栏**而非工作区面板 —— 侧栏才是会话管理的主入口
   （常驻可见、有搜索框、有重命名/删除）。此前把会话列表塞进 320px 的
   工作区弹层里，与侧栏重复渲染两份，且弹层宽度根本放不下 50 条。 */

/** 会话行操作按钮（统一 SVG 线性图标，不用 emoji —— 字形/基线不统一）。 */
function OP_BTN(act, title, path, extra) {
  return '<button class="s-op' + (extra ? ' s-op-' + extra : '') + '" data-act="' + act +
    '" title="' + title + '" aria-label="' + title + '">' +
    '<svg viewBox="0 0 24 24">' + path + '</svg></button>';
}

export async function loadSessions() {
  const el = $id('session-list');
  if (!el) return;
  const grp = '<div class="s-group">会话</div>';
  el.innerHTML = grp +
    '<div style="padding:14px;color:var(--ml-text-faint);font-size:12px;text-align:center">加载中…</div>';

  let d;
  try {
    d = await jget('/api/sessions');
  } catch (e) {
    d = null;
  }
  if (!d || !d.sessions) {
    el.innerHTML = grp +
      '<div style="padding:14px;color:var(--ml-danger);font-size:12px;text-align:center">会话列表加载失败</div>' +
      '<div style="text-align:center"><button class="btn btn-ghost btn-sm" id="btn-session-retry">重试</button></div>';
    const rb = $id('btn-session-retry');
    if (rb) rb.onclick = () => loadSessions();
    return;
  }
  const list = d.sessions || [];
  if (!list.length) {
    el.innerHTML = grp + '<div style="padding:20px 14px;color:var(--ml-text-faint);font-size:12px;text-align:center">' +
      '还没有会话，点上方 + 开始</div>';
    return;
  }
  let h = grp;
  list.forEach(s => {
    const act = S.session && s.id === S.session.id ? 'active' : '';
    const title = esc(s.title || '未命名会话');
    const preview = esc((s.preview || '').slice(0, 26));
    const sid = esc(String(s.id));
    /* 三个操作同排放在每条会话右侧：归档 / 重命名 / 删除。
       统一用 SVG 线性图标 —— 原版用 emoji（📥✎✕），字形与基线各不相同。 */
    const ops = '<div class="s-ops">' +
      OP_BTN('archive', '归档（不删除，可在归档箱恢复）', '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/><path d="M10 13h4"/>') +
      OP_BTN('rename', '重命名', '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>') +
      OP_BTN('delete', '删除', '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>', ' danger') +
      '</div>';
    h += '<div class="session-item ' + act + '" data-sid="' + sid + '" data-act="select">' +
      '<span class="s-dot"></span>' +
      '<div class="s-title">' + title + '</div>' +
      '<div class="s-meta"><span>' + (s.message_count || 0) + ' 条消息</span></div>' +
      '<div class="s-preview">' + preview + '</div>' +
      ops + '</div>';
  });
  el.innerHTML = h;
}

/** 归档会话（不删除数据）。归档箱在「设置 → 会话」里管理。 */
export async function archiveSession(id, archived) {
  const verb = archived ? '归档' : '恢复';
  try {
    const d = await jpost('/api/sessions/' + encodeURIComponent(id) + '/archive', { archived: !!archived });
    if (!d || !d.ok) { toast(verb + '失败', 'err'); return; }
    if (archived && S.session && S.session.id === id) {
      S.session = null;
      $id('chat-title').textContent = '新会话';
      $id('chat-stream').innerHTML = '';
    }
    await loadSessions();
    toast(archived ? '已归档，可在设置 → 会话里恢复' : '已恢复', 'ok');
  } catch (e) { toast(verb + '失败：' + (e.message || e), 'err'); }
}

export async function selectSession(id) {
  _gotoChatPage();
  if (S.es) { S.es.close(); S.es = null; }
  S.streaming = false;
  const d = await jget('/api/sessions');
  if (!d || !d.sessions) return;
  const s = d.sessions.find(x => x.id === id);
  if (!s) return;
  S.session = { id: id, title: s.title || '会话' };
  $id('chat-title').textContent = S.session.title;
  loadMessages(id);
  loadSessions();
}

/* ── 历史消息回放 ─────────────────────────────────────── */
function _stripUntrusted(s) {
  return String(s || '').replace(/<\/?untrusted_tool_result[^>]*>/g, '').trim();
}
function _histUserBubble(text) {
  const stream = $id('chat-stream');
  const wrap = document.createElement('div');
  wrap.className = 'msg user';
  wrap.innerHTML = '<div class="avatar">你</div><div class="msg-body"><div class="bubble"></div></div>';
  wrap.querySelector('.bubble').innerHTML = esc(String(text || '')).replace(/\n/g, '<br>');
  stream.appendChild(wrap);
}
function _histAgentFlow(stream) {
  const wrap = document.createElement('div');
  wrap.className = 'msg agent';
  wrap.innerHTML = '<div class="avatar">ML</div><div class="msg-body"><div class="run-flow"></div></div>';
  stream.appendChild(wrap);
  return wrap.querySelector('.run-flow');
}
function _histTextBlock(flow, text, reasoning) {
  if (!text.trim() && !reasoning) return;
  if (reasoning) {
    const tb = document.createElement('div');
    tb.className = 'think-block collapsed';
    tb.innerHTML = '<div class="think-head"><span class="th-ic">💭</span><span class="th-label">思考过程</span><span class="th-arrow">▸</span></div><div class="think-body"></div>';
    tb.querySelector('.think-body').innerHTML = renderMarkdown(reasoning);
    tb.querySelector('.think-head').onclick = () => {
      tb.classList.toggle('collapsed');
      const ar = tb.querySelector('.th-arrow');
      if (ar) ar.textContent = tb.classList.contains('collapsed') ? '▸' : '▾';
    };
    flow.appendChild(tb);
  }
  if (text.trim()) {
    const el = document.createElement('div');
    el.className = 'rf-text';
    el.innerHTML = renderMarkdown(text);
    flow.appendChild(el);
  }
}
function _histToolCard(flow, name, result) {
  const step = document.createElement('div');
  step.className = 'run-step ok';
  step.innerHTML = '<span class="rs-icon">' + (TOOL_ICON[name] || '⚙') + '</span>' +
    '<span class="rs-name">' + esc(name) + '</span>' +
    '<span class="rs-status">✓ 完成</span>' +
    '<span class="rs-arrow">▸</span>';
  step.onclick = () => {
    const detail = step.querySelector('.run-step-detail');
    const arrow = step.querySelector('.rs-arrow');
    if (detail) { detail.remove(); step.classList.remove('open'); if (arrow) arrow.textContent = '▸'; return; }
    step.classList.add('open'); if (arrow) arrow.textContent = '▾';
    const dd = document.createElement('div');
    dd.className = 'run-step-detail';
    dd.innerHTML = '<div class="run-result ok">✓ 执行成功</div>' +
      '<div class="t-label" style="margin-top:4px">执行结果 · Observation</div><pre>' + esc(String(result).slice(0, 2000)) + '</pre>';
    step.appendChild(dd);
  };
  flow.appendChild(step);
}

export async function loadMessages(id) {
  const d = await jget('/api/sessions/' + id + '/messages');
  const stream = $id('chat-stream');
  stream.innerHTML = '';
  if (!d || !d.messages || !d.messages.length) {
    stream.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">新会话 · 向 MatLens 提问开始科研协作</div>';
    return;
  }
  const msgs = d.messages;
  let flow = null;
  let i = 0;
  while (i < msgs.length) {
    const m = msgs[i];
    if (m.role === 'user') {
      flow = null;
      _histUserBubble(m.content);
      i++;
    } else if (m.role === 'assistant') {
      if (!flow) flow = _histAgentFlow(stream);
      let buf = '', reasoning = '';
      while (i < msgs.length && msgs[i].role === 'assistant') {
        buf += String(msgs[i].content || '');
        if (msgs[i].reasoning_content) reasoning += String(msgs[i].reasoning_content);
        i++;
      }
      _histTextBlock(flow, buf, reasoning);
    } else if (m.role === 'tool') {
      if (!flow) flow = _histAgentFlow(stream);
      const name = m.tool_name || 'tool';
      let result = _stripUntrusted(m.content);
      i++;
      while (i < msgs.length && msgs[i].role === 'tool' && (msgs[i].tool_name || 'tool') === name) {
        const r2 = _stripUntrusted(msgs[i].content);
        if (r2.length > result.length) result = r2;
        i++;
      }
      _histToolCard(flow, name, result);
    } else {
      i++;
    }
  }
  stream.scrollTop = stream.scrollHeight;
}

export function newSession() {
  if (S.es) { S.es.close(); S.es = null; }
  S.streaming = false;
  S.session = null;
  $id('chat-title').textContent = '新会话';
  $id('chat-stream').innerHTML = '<div id="chat-empty" style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">新会话 · 向 MatLens 提问开始科研协作</div>';
  loadSessions();
}

export async function renameSession(id) {
  const title = prompt('输入新名称：');
  if (!title) return;
  const d = await jput('/api/sessions/' + id, { title: title });
  if (d && d.ok) {
    if (S.session && S.session.id === id) { S.session.title = title; $id('chat-title').textContent = title; }
    loadSessions(); toast('已重命名', 'ok');
  } else toast('重命名失败', 'err');
}

export async function deleteSession(id) {
  if (!confirm('删除该会话？消息将不可恢复。')) return;
  const d = await jdel('/api/sessions/' + id);
  if (d && d.ok) {
    if (S.session && S.session.id === id) {
      S.session = null; $id('chat-title').textContent = '新会话';
      $id('chat-stream').innerHTML = '';
    }
    loadSessions(); toast('会话已删除', 'ok');
  } else toast('删除失败', 'err');
}
