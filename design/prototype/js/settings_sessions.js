/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · settings_sessions.js
 *
 * 2026-10-15：设置页「会话归档箱」面板。
 *
 * 为什么归档箱在设置里而不是侧栏：
 *   归档是**低频操作**（整理旧对话），而侧栏窄（215px）且已列 50 条会话，
 *   再塞一个「归档箱」视图切换器会把列表头挤没。设置页有完整空间，
 *   还能顺带承载「从归档提炼记忆」这个批量操作。
 *
 * 本面板两个能力：
 *   1. 归档列表：查看 / 恢复 / 彻底删除
 *   2. **从归档对话中提炼记忆** —— 会话是「过程」，记忆是「资产」。
 *      用户聊完几十轮归档后，里面的研究方向、材料体系偏好、实验参数、
 *      结论方式就此沉在 state.db 里；提炼把它们变成长期记忆，
 *      下次开新会话 Agent 自动带上这些背景。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jpost, jdel } from './core.js';

let _distilling = false;

const ICON = {
  restore: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
};

function _opBtn(act, title, path, danger) {
  return '<button class="ar-op' + (danger ? ' ar-op-danger' : '') + '" data-act="' + act +
    '" title="' + title + '" aria-label="' + title + '">' +
    '<svg viewBox="0 0 24 24">' + path + '</svg></button>';
}

function _fmtDate(iso) {
  try {
    const d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
      + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  } catch (e) { return ''; }
}

/** 加载归档列表。 */
export async function loadArchivedSessions() {
  const box = $id('archived-list');
  if (!box) return;
  box.innerHTML = '<div class="ar-loading">加载归档…</div>';
  let d;
  try { d = await jget('/api/sessions/archived'); }
  catch (e) { box.innerHTML = '<div class="ar-empty" style="color:var(--ml-danger)">归档列表加载失败</div>'; return; }

  const list = (d && d.sessions) || [];
  if (!list.length) {
    box.innerHTML = '<div class="ar-empty">' +
      '<svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="5" rx="1"/>' +
      '<path d="M4 9v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/></svg>' +
      '<div class="ar-empty-t">归档箱是空的</div>' +
      '<div class="ar-empty-h">在侧栏「聊天历史」里，把不常用的会话点归档按钮收进来。' +
      '归档不删除任何数据。</div></div>';
    return;
  }

  box.innerHTML = '<div class="ar-head"><span>共 ' + list.length + ' 条归档</span>' +
    '<span class="ar-head-tip">共 ' +
    list.reduce((n, s) => n + (s.message_count || 0), 0) + ' 条消息</span></div>' +
    list.map(s =>
      '<div class="ar-item" data-sid="' + esc(String(s.id)) + '">' +
        '<div class="ar-main">' +
          '<div class="ar-title">' + esc(s.title || '未命名会话') + '</div>' +
          '<div class="ar-meta">' + (s.message_count || 0) + ' 条消息 · ' +
          esc(_fmtDate(s.last_active)) + '</div>' +
        '</div>' +
        '<div class="ar-ops">' +
          _opBtn('restore', '恢复到聊天历史', ICON.restore) +
          _opBtn('delete', '彻底删除（不可恢复）', ICON.trash, true) +
        '</div>' +
      '</div>').join('');

  box.querySelectorAll('.ar-item').forEach(el => {
    const sid = el.dataset.sid;
    el.querySelector('[data-act="restore"]').onclick = async () => {
      try {
        await jpost('/api/sessions/' + encodeURIComponent(sid) + '/archive', { archived: false });
        toast('已恢复到聊天历史', 'ok');
        await loadArchivedSessions();
        try { const m = await import('./sessions.js'); m.loadSessions(); } catch (e) { /* 静默 */ }
      } catch (err) { toast('恢复失败：' + (err.message || err), 'err'); }
    };
    el.querySelector('[data-act="delete"]').onclick = async () => {
      if (!confirm('彻底删除该会话？\n消息与归档记录都将不可恢复。')) return;
      try {
        await jdel('/api/sessions/' + encodeURIComponent(sid));
        toast('已彻底删除', 'ok');
        await loadArchivedSessions();
      } catch (err) { toast('删除失败：' + (err.message || err), 'err'); }
    };
  });
}

/** 从归档会话提炼记忆（调后端 /api/sessions/distill）。 */
async function distillSessions() {
  if (_distilling) return;
  const btn = $id('btn-distill-sessions');
  const tx = $id('distill-btn-tx');
  const logBox = $id('distill-log');
  const scopeEl = $id('distill-scope');
  if (!btn || !logBox) return;

  _distilling = true;
  btn.disabled = true;
  btn.classList.add('busy');
  if (tx) tx.textContent = '提炼中…';
  logBox.style.display = '';
  logBox.textContent = '正在读取归档会话并调用模型提炼，请稍候…（首次约 15–40 秒）';
  logBox.className = 'running';

  try {
    const scope = (scopeEl && scopeEl.value) || 'all';
    const res = await jpost('/api/sessions/distill', { limit: scope === 'recent' ? 10 : 20 });
    const lines = (res && res.log) || [];
    let html = lines.map(l => esc(l)).join('<br>');
    if (res && res.extracted) {
      html += '<br><b>提取到 ' + res.extracted + ' 条知识，已存入长期记忆：</b><br>' +
        (res.lines || []).map(l => '· ' + esc(l)).join('<br>');
      html += '<br><span style="color:var(--ml-text-faint)">' +
        '下次开新会话时，Agent 会自动带上这些背景。</span>';
    } else if (res && res.processed === 0) {
      html += '<br><span style="color:var(--ml-warn)">没有内容足够长的归档会话。</span>';
    }
    logBox.innerHTML = html;
    logBox.className = '';
    logBox.scrollTop = 0;
    if (tx) tx.textContent = '再次提炼';
    if (res && res.stored) {
      toast('已提炼 ' + res.extracted + ' 条知识入库', 'ok');
      // 刷新右栏记忆（若在对话页能看到）
      try {
        const r = await import('./chat_right.js');
        if (r.refreshRightPanel) r.refreshRightPanel();
      } catch (e) { /* 静默 */ }
    }
  } catch (e) {
    logBox.className = '';
    logBox.innerHTML = '<span style="color:var(--ml-danger)">提炼失败：' +
      esc(e.message || e) + '</span>';
    if (tx) tx.textContent = '重试';
  } finally {
    _distilling = false;
    btn.disabled = false;
    btn.classList.remove('busy');
  }
}

/** settings.js 的模块引用（动态 import，避免与本模块互相 import 形成环）。 */
let _settingsMod = null;

/** 挂上自定义 select。
 *  原生 <select class="hidden-sel"> 被 CSS 隐藏，必须额外挂一层 .ml-select UI，
 *  否则界面上就是一个 150px 的空白框（实测踩过）。 */
function _mountScopeSelect() {
  try {
    const m = _settingsMod && _settingsMod.mountMlSelect;
    if (m) m('distill-scope-ui');
  } catch (e) { /* 静默：退回原生 select 也不影响提炼 */ }
}

export async function initSettingsSessions() {
  try { _settingsMod = await import('./settings.js'); } catch (e) { _settingsMod = null; }
  const btn = $id('btn-distill-sessions');
  if (btn) btn.onclick = distillSessions;
  _mountScopeSelect();
  await loadArchivedSessions();
  // 提炼区显示归档条数，让用户知道会处理多少内容
  try {
    const d = await jget('/api/sessions/archived');
    const n = (d && d.sessions) || [];
    const hint = $id('distill-hint');
    if (hint) {
      hint.textContent = n.length
        ? ('当前归档 ' + n.length + ' 条、共 ' +
            n.reduce((a, s) => a + (s.message_count || 0), 0) + ' 条消息')
        : '归档箱为空，先在侧栏归档几条对话';
    }
    // 无内容时禁用按钮（避免点了只得到一句空话）
    if (btn) btn.disabled = !n.length;
  } catch (e) { /* 静默 */ }
}
