/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · paper.js（论文工坊 7 步：选题→检索→大纲→写作→
 * 质量→审稿→导出；含导出 Word / 回流知识库）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, renderMarkdown, jget, jpost, psCard } from './core.js';

export const PAPER_STAGES = ['topic', 'search', 'outline', 'write', 'quality', 'review', 'export'];
export const PAPER_LABELS = {
  topic: '选题设定', search: '文献检索', outline: '大纲生成', write: '逐章写作',
  quality: '质量巡检', review: '模拟审稿', export: '导出',
};
export let curPaper = null;
export let curStage = 'topic';
let _paperAbort = null;
let _paperMode = 'view';
let _paperDataOpen = false;   // write 步「实验数据」面板展开态
let pError = '';

function lastDoneStage(stages) {
  for (let i = PAPER_STAGES.length - 1; i >= 0; i--) {
    const s = stages[PAPER_STAGES[i]];
    if (s && s.status === 'done') return PAPER_STAGES[i];
  }
  return null;
}
function firstPendingStage(stages) {
  for (const s of PAPER_STAGES) {
    const st = stages[s];
    if (!st || st.status !== 'done') return s;
  }
  return 'export';
}

export async function loadPapers() {
  const el = $id('paper-list');
  if (!el) return;
  el.innerHTML = '<div style="padding:10px;color:var(--ml-text-faint);font-size:12px;text-align:center">加载中…</div>';
  const d = await jget('/api/papers');
  if (!d || !d.papers) {
    el.innerHTML = '<div style="padding:10px;color:var(--ml-danger);font-size:12px;text-align:center">课题列表加载失败</div>' +
      '<div style="text-align:center"><button class="btn btn-ghost btn-sm" id="btn-paper-retry">重试</button></div>';
    const rb = $id('btn-paper-retry'); if (rb) rb.onclick = () => loadPapers();
    return;
  }
  if (!d.papers.length) {
    el.innerHTML = '<div style="font-size:12px;color:var(--ml-text-faint);padding:14px 10px">还没有课题，点右上角「新建」开始 7 步论文之旅</div>';
    return;
  }
  el.innerHTML = d.papers.map(p => {
    const act = curPaper && p.id === curPaper.id ? 'active' : '';
    return '<div class="kb-item ' + act + '" style="cursor:pointer;position:relative" data-pid="' + esc(p.id) + '">' +
      '<div class="k-name" style="font-size:12.5px;padding-right:18px">' + esc(p.title).slice(0, 18) + '</div>' +
      '<div class="k-meta"><span>' + ((p.progress && p.progress.pct) || 0) + '%</span><span>' + (PAPER_LABELS[lastDoneStage(p.stages)] || '') + '</span></div>' +
      '<span title="删除课题" class="paper-del" data-pid="' + esc(p.id) + '" data-title="' + esc(p.title) + '" style="position:absolute;top:6px;right:10px;font-size:12px;opacity:.45;cursor:pointer;color:var(--ml-text-faint)">✕</span>' +
      '</div>';
  }).join('');
  // 事件委托
  el.querySelectorAll('.kb-item').forEach(item => {
    item.onclick = (e) => {
      if (e.target.classList.contains('paper-del')) return;
      selectPaper(item.dataset.pid);
    };
  });
  el.querySelectorAll('.paper-del').forEach(b => {
    b.onclick = (e) => {
      e.stopPropagation();
      delPaper(b.dataset.pid, b.dataset.title);
    };
  });
}

export function createPaper() {
  const m = document.getElementById('paper-modal');
  if (m) { m.classList.add('show'); const t = document.getElementById('paper-title'); if (t) t.focus(); }
}

export function bindPaperUI() {
  const cancelBtn = document.getElementById('btn-paper-cancel');
  if (cancelBtn) cancelBtn.onclick = () => { const m = document.getElementById('paper-modal'); if (m) m.classList.remove('show'); };
  const createBtn = document.getElementById('btn-paper-create');
  if (createBtn) createBtn.onclick = async () => {
    const title = document.getElementById('paper-title').value.trim();
    if (!title) { document.getElementById('paper-title').focus(); return; }
    const topic = document.getElementById('paper-topic').value.trim();
    const d = await jpost('/api/papers', { title: title, topic: topic || title, paper_type: 'research' });
    if (d && d.id) {
      const m = document.getElementById('paper-modal'); if (m) m.classList.remove('show');
      document.getElementById('paper-title').value = '';
      document.getElementById('paper-topic').value = '';
      await loadPapers(); selectPaper(d.id); toast('课题已创建，从选题设定开始', 'ok');
    } else toast('创建失败：' + ((d && d.detail) || ''), 'err');
  };
  const modal = document.getElementById('paper-modal');
  if (modal) modal.onclick = (e) => { if (e.target === modal) modal.classList.remove('show'); };
}

export async function selectPaper(id) {
  const d = await jget('/api/papers/' + id);
  if (!d || !d.id) { toast('课题不存在', 'err'); return; }
  curPaper = d;
  curStage = firstPendingStage(d.stages) || 'export';
  _paperMode = 'view';
  renderPaperSteps();
  renderPaperPanel();
  fillPaperProgress();
  loadPapers();
}

export function renderPaperSteps() {
  const el = $id('stepbar');
  if (!el) return;
  if (!curPaper) { el.innerHTML = ''; return; }
  const st = curPaper.stages || {};
  el.innerHTML = PAPER_STAGES.map((s, i) => {
    const stt = (st[s] && st[s].status) || 'pending';
    const cls = stt === 'done' ? 'done' : stt === 'running' ? 'active' : stt === 'error' ? 'error' : '';
    const num = stt === 'done' ? '✓' : i + 1;
    const isCur = s === curStage ? ' cur' : '';
    return (i ? '<span class="step-arrow">›</span>' : '') +
      '<div class="step ' + cls + isCur + '" data-stage="' + s + '" title="' + PAPER_LABELS[s] + '">' +
      '<span class="s-num">' + num + '</span>' + PAPER_LABELS[s] + '</div>';
  }).join('');
  el.querySelectorAll('.step').forEach(step => {
    step.onclick = () => viewStage(step.dataset.stage);
  });
}

export function viewStage(s) {
  if (!curPaper) return;
  curStage = s;
  renderPaperSteps();
  renderPaperPanel();
}

export function renderPaperPanel() {
  const panel = $id('paper-panel');
  if (!panel) return;
  if (!curPaper) {
    panel.innerHTML = '<div style="color:var(--ml-text-faint);padding:40px;text-align:center;font-size:13px;margin:auto">← 选择左侧课题，或新建开始 7 步论文之旅</div>';
    return;
  }
  const st = (curPaper.stages && curPaper.stages[curStage]) || {};
  const status = st.status || 'pending';
  const content = st.content || '';
  const statusText = { pending: '未开始', running: '生成中…', done: '已完成', error: '出错' }[status] || status;
  const isLast = curStage === 'export';
  const prev = PAPER_STAGES[PAPER_STAGES.indexOf(curStage) - 1];
  const prevDone = !prev || (curPaper.stages[prev] && curPaper.stages[prev].status === 'done');

  panel.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px">' +
      '<div style="display:flex;align-items:center;gap:10px">' +
        '<span style="font-weight:700;font-size:14px">' + PAPER_LABELS[curStage] + '</span>' +
        '<span class="tag" id="p-status" style="' + (status === 'done' ? 'color:var(--ml-ok)' : status === 'error' ? 'color:var(--ml-danger)' : status === 'running' ? 'color:var(--ml-warn)' : 'color:var(--ml-text-faint)') + '">' + statusText + '</span>' +
      '</div>' +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        (content ? '<button class="btn btn-ghost btn-sm" id="btn-p-mode">' + (_paperMode === 'edit' ? '👁 查看' : '✎ 编辑') + '</button>' : '') +
        '<button class="btn btn-ghost btn-sm" id="btn-p-save">保存编辑</button>' +
        (curStage === 'write' ? '<button class="btn btn-ghost btn-sm" id="btn-p-data" title="录入/导入实验数据：必须标注拟议或实测，AI 不得编造数据冒充实验结果">🧪 实验数据' + ((curPaper.data && curPaper.data.status === 'measured') ? ' <span style="color:var(--ml-ok)">●实测</span>' : (curPaper.data ? ' <span style="color:var(--ml-warn)">●拟议</span>' : '')) + '</button>' : '') +
        (!isLast ? '<button class="btn btn-primary btn-sm" id="btn-p-run" ' + (prevDone ? '' : 'disabled title="先完成上一步"') + ' style="' + (prevDone ? '' : 'opacity:.45;cursor:not-allowed') + '">' + (prevDone ? (status === 'done' ? '重新生成' : '▶ 生成') : '⚠ 先完成上一步') + '</button>' : '') +
        '<button class="btn btn-ghost btn-sm" id="btn-p-cancel" style="display:none">停止</button>' +
        '<button class="btn btn-ghost btn-sm" id="btn-p-word" title="按设置页默认格式导出成稿（docx/tex/md）">📥 导出成稿</button>' +
        '<button class="btn btn-ghost btn-sm" id="btn-p-tokb" title="把成稿回流到知识库">📚 回流知识库</button>' +
      '</div>' +
    '</div>' +
    (prev && !prevDone ? '<div style="font-size:12px;color:var(--ml-warn);margin-bottom:10px">⚠ 前置步骤「' + PAPER_LABELS[prev] + '」未完成，请先完成上一步</div>' : '') +
    (curStage === 'write' ? _renderDataBlock() : '') +
    '<div style="flex:1;min-height:0;display:flex;flex-direction:column">' +
      '<div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:6px" id="p-gen-label"></div>' +
      '<div id="p-stream" style="display:none;font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--ml-text);max-height:45%;overflow-y:auto;background:rgba(255,255,255,.03);border:1px solid var(--ml-card-border);border-radius:10px;padding:12px;margin-bottom:10px"></div>' +
      '<div id="p-view" style="' + (_paperMode === 'edit' ? 'display:none' : '') + ';flex:1;min-height:200px;overflow-y:auto;border:1px solid var(--ml-card-border);border-radius:10px;padding:13px;color:var(--ml-text);font-size:13px;line-height:1.75;background:var(--ml-input-bg)">' + (content ? renderMarkdown(content) : '<span style="color:var(--ml-text-faint)">（该步骤暂无内容，点击「▶ 生成」或「保存编辑」开始）</span>') + '</div>' +
      '<textarea id="p-editor" spellcheck="false" style="' + (_paperMode === 'edit' ? '' : 'display:none') + ';flex:1;min-height:200px;background:transparent;border:1px solid var(--ml-card-border);border-radius:10px;padding:13px;color:var(--ml-text);font:13px/1.7 Consolas,Menlo,monospace;resize:none;outline:none">' + esc(content) + '</textarea>' +
    '</div>';

  // 绑定按钮
  const modeBtn = $id('btn-p-mode'); if (modeBtn) modeBtn.onclick = () => { _paperMode = _paperMode === 'edit' ? 'view' : 'edit'; renderPaperPanel(); };
  const saveBtn = $id('btn-p-save'); if (saveBtn) saveBtn.onclick = () => savePaperStep();
  const dataBtn = $id('btn-p-data'); if (dataBtn) dataBtn.onclick = () => { _paperDataOpen = !_paperDataOpen; renderPaperPanel(); };
  const dataTpl = $id('btn-p-data-tpl'); if (dataTpl) dataTpl.onclick = () => { const ta = $id('p-data-tables'); if (ta) ta.value = JSON.stringify([{ name: 'Table 1', caption: '', rows: [[]] }], null, 2); };
  const dataSave = $id('btn-p-data-save'); if (dataSave) dataSave.onclick = () => savePaperData();
  const runBtn = $id('btn-p-run'); if (runBtn && prevDone) runBtn.onclick = () => runPaperStep(curStage);
  const cancelBtn = $id('btn-p-cancel'); if (cancelBtn) cancelBtn.onclick = () => cancelPaperRun();
  const wordBtn = $id('btn-p-word'); if (wordBtn) wordBtn.onclick = () => exportPaper();
  const tokbBtn = $id('btn-p-tokb'); if (tokbBtn) tokbBtn.onclick = () => toKb();
}

/* write 步「实验数据」区块：摘要条（已存数据时常驻）+ 展开编辑器 */
function _renderDataBlock() {
  const d = (curPaper && curPaper.data) || null;
  let html = '';
  // 摘要条：已存数据时常驻显示（状态徽标 + notes + 表数 + 更新时间）
  if (d) {
    const measured = d.status === 'measured';
    const badge = measured
      ? '<span class="tag" style="color:var(--ml-ok)">● 实测数据</span>'
      : '<span class="tag" style="color:var(--ml-warn)">● 拟议数据（待实验确认）</span>';
    const tcount = Array.isArray(d.tables) ? d.tables.length : 0;
    const note = d.notes ? esc(d.notes) : '（无说明）';
    html += '<div style="display:flex;align-items:center;gap:10px;font-size:12px;color:var(--ml-text-faint);margin-bottom:8px;flex-wrap:wrap">' +
      badge +
      '<span style="flex:1;min-width:120px;color:var(--ml-text)">' + note + '</span>' +
      '<span>表 ' + tcount + ' 张</span>' +
      (d.updated_at ? '<span>更新于 ' + esc(d.updated_at) + '</span>' : '') +
      '</div>';
  }
  // 展开编辑器
  if (_paperDataOpen) {
    const status = (d && d.status) || 'proposed';
    const notes = (d && d.notes) || '';
    const tablesJson = (d && Array.isArray(d.tables) && d.tables.length) ? JSON.stringify(d.tables, null, 2) : '';
    html += '<div id="p-data-panel" style="border:1px solid var(--ml-card-border);border-radius:10px;padding:12px;margin-bottom:10px;background:rgba(255,255,255,.02)">' +
      '<div style="font-size:12.5px;font-weight:700;margin-bottom:8px;color:var(--ml-text)">🧪 实验数据录入' +
        '<span style="font-weight:400;color:var(--ml-text-faint)">　学术诚信：请如实标注「拟议/实测」，AI 不会、也不得编造数据冒充实验结果</span>' +
      '</div>' +
      '<div style="margin-bottom:8px;font-size:12.5px;display:flex;gap:16px;flex-wrap:wrap">' +
        '<label style="cursor:pointer"><input type="radio" name="p-data-status" value="proposed"' + (status === 'proposed' ? ' checked' : '') + '> 拟议（待实验确认）</label>' +
        '<label style="cursor:pointer"><input type="radio" name="p-data-status" value="measured"' + (status === 'measured' ? ' checked' : '') + '> 实测数据</label>' +
      '</div>' +
      '<div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:4px">数据来源 / 说明</div>' +
      '<textarea id="p-data-notes" spellcheck="false" placeholder="例：2026-10-11 在 SOFC 实验室测得；或拟议值仅用于方法演示" style="width:100%;min-height:48px;background:var(--ml-input-bg);border:1px solid var(--ml-card-border);border-radius:8px;padding:8px;color:var(--ml-text);font:12.5px/1.6 inherit;resize:vertical;outline:none">' + esc(notes) + '</textarea>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0 4px">' +
        '<span style="font-size:12px;color:var(--ml-text-faint)">数据表（JSON，可选，数组）</span>' +
        '<button class="btn btn-ghost btn-sm" id="btn-p-data-tpl" style="padding:2px 8px;font-size:11px">载入模板</button>' +
      '</div>' +
      '<textarea id="p-data-tables" spellcheck="false" placeholder=\'[{"name":"Table 1","caption":"","rows":[[1,2],[3,4]]}]\' style="width:100%;min-height:80px;background:var(--ml-input-bg);border:1px solid var(--ml-card-border);border-radius:8px;padding:8px;color:var(--ml-text);font:12px/1.5 Consolas,Menlo,monospace;resize:vertical;outline:none">' + esc(tablesJson) + '</textarea>' +
      '<div style="margin-top:8px;text-align:right"><button class="btn btn-primary btn-sm" id="btn-p-data-save">保存数据</button></div>' +
    '</div>';
  }
  return html;
}

/* 保存实验数据：POST /api/papers/{pid}/data → 局部刷新 curPaper（保持当前步骤/展开态） */
export async function savePaperData() {
  if (!curPaper) return;
  const statusEl = document.querySelector('input[name="p-data-status"]:checked');
  const status = statusEl ? statusEl.value : 'proposed';
  const notes = ($id('p-data-notes') ? $id('p-data-notes').value : '');
  let tables = [];
  const tablesRaw = ($id('p-data-tables') ? $id('p-data-tables').value : '').trim();
  if (tablesRaw) {
    try {
      tables = JSON.parse(tablesRaw);
    } catch (e) {
      toast('数据表 JSON 格式错误：' + (e.message || e), 'err');
      return;
    }
    if (!Array.isArray(tables)) { toast('数据表 JSON 应为数组 [{...}]', 'err'); return; }
  }
  const d = await jpost('/api/papers/' + curPaper.id + '/data', { data: { status: status, notes: notes, tables: tables } });
  if (d && d.ok) {
    toast('实验数据已保存（' + (status === 'measured' ? '实测' : '拟议') + '）', 'ok');
    const fresh = await jget('/api/papers/' + curPaper.id);
    if (fresh && fresh.id) curPaper = fresh;
    renderPaperPanel();
  } else {
    toast('保存失败：' + ((d && d.detail) || ''), 'err');
  }
}

export async function runPaperStep(stage) {
  if (!curPaper) return;
  const btn = $id('btn-p-run');
  if (btn) { btn.disabled = true; btn.textContent = '生成中…'; }
  const cancelBtn = $id('btn-p-cancel');
  if (cancelBtn) { cancelBtn.style.display = ''; cancelBtn.disabled = false; }
  const statusEl = $id('p-status');
  if (statusEl) { statusEl.textContent = '生成中…'; statusEl.style.color = 'var(--ml-warn)'; }
  const streamEl = $id('p-stream');
  if (streamEl) { streamEl.style.display = 'block'; streamEl.textContent = ''; }
  const genLabel = $id('p-gen-label');
  if (genLabel) genLabel.textContent = stage === 'quality' ? '● 本地规则巡检中…' : '● 正在生成（AI 流式输出）…';
  pError = '';
  let cancelled = false;
  _paperAbort = new AbortController();
  try {
    const res = await fetch('/api/papers/' + curPaper.id + '/run/' + stage, { method: 'POST', signal: _paperAbort.signal });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split('\n\n');
      buf = frames.pop();
      for (const f of frames) {
        if (!f.startsWith('data: ')) continue;
        let d; try { d = JSON.parse(f.slice(6)); } catch (_) { continue; }
        handlePaperEvent(d);
      }
    }
  } catch (e) {
    if (e && e.name === 'AbortError') { cancelled = true; if (genLabel) genLabel.textContent = '✕ 已取消生成'; }
    else if (genLabel) genLabel.textContent = '生成中断：' + (e.message || e);
  }
  _paperAbort = null;
  if (cancelBtn) cancelBtn.style.display = 'none';
  if (!cancelled && !pError) _paperMode = 'view';
  await selectPaper(curPaper.id);
  if (curStage === stage) renderPaperPanel();
  if (pError) toast('「' + PAPER_LABELS[stage] + '」失败：' + pError, 'err');
  else if (!cancelled) toast(stage === 'export' ? '导出完成' : '「' + PAPER_LABELS[stage] + '」已完成', 'ok');
}

export function cancelPaperRun() {
  const btn = $id('btn-p-cancel');
  if (btn) btn.disabled = true;
  if (_paperAbort) _paperAbort.abort();
}

export function handlePaperEvent(d) {
  switch (d.type) {
    case 'stream_text': {
      const el = $id('p-stream');
      if (el) el.textContent += (d.data && d.data.text) || '';
      break;
    }
    case 'stage_error':
      pError = (d.data && d.data.message) || '生成失败';
      { const g = $id('p-gen-label'); if (g) g.textContent = '✕ ' + pError; }
      break;
    case 'error':
      pError = (d.data && d.data.message) || '未知错误';
      { const g = $id('p-gen-label'); if (g) g.textContent = '✕ ' + pError; }
      break;
    case 'done': {
      const r = d.data || {};
      const g = $id('p-gen-label');
      if (!r.ok) { pError = r.error || '前置未完成'; if (g) g.textContent = '✕ ' + pError; }
      else if (g) g.textContent = '✓ 生成完成';
      break;
    }
  }
}

export async function savePaperStep() {
  if (!curPaper) return;
  const content = $id('p-editor') ? $id('p-editor').value : '';
  const d = await jpost('/api/papers/' + curPaper.id + '/save', { stage: curStage, content: content });
  if (d && d.ok) {
    _paperMode = 'view';
    toast('已保存「' + PAPER_LABELS[curStage] + '」', 'ok');
    selectPaper(curPaper.id);
  } else toast('保存失败', 'err');
}

/* 导出成稿（不传 fmt → 走设置页默认导出格式；传 fmt 显式导出该格式）
   导出前先过质量门（GET /quality_gate）：分数过低/有严重问题时二次确认，
   确认则带 force=true 强行导出（后端不再带警告）。 */
export async function exportPaper(fmt, force) {
  if (!curPaper) return;

  // 质量门预检：仅在首次（非 force）时问一次
  if (!force) {
    let gate = null;
    try {
      gate = await jget('/api/papers/' + curPaper.id + '/quality_gate');
    } catch (_) { /* 门不可用不阻断导出 */ }
    if (gate && gate.checked && gate.passed === false) {
      const lines = [];
      (gate.reasons || []).forEach(r => lines.push('· ' + r));
      (gate.blocking || []).forEach(b => lines.push('  ' + b));
      const msg = '⚠️ 这篇论文尚未达到导出质量标准\n\n'
        + lines.join('\n')
        + '\n\n建议先执行「质量巡检」并按建议修订。';
      if (!confirm(msg + '\n\n仍要导出吗？')) { toast('已取消导出', 'warn'); return; }
      force = true;
    }
  }

  const btn = $id('btn-p-word');
  if (btn) { btn.disabled = true; btn.textContent = '导出中…'; }
  try {
    const url = '/api/papers/' + curPaper.id + '/export' + (fmt ? '/' + fmt : '') + (force ? '?force=true' : '');
    const res = await fetch(url);
    if (!res.ok) { toast('导出失败（' + res.status + '）', 'err'); return; }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/);
    const safe = (curPaper.title || 'paper').replace(/[\\/:*?"<>|]/g, '_');
    const fname = m ? decodeURIComponent(m[1]) : (safe + '.' + (fmt || 'bin'));
    const url2 = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url2; a.download = fname;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url2);
    try {
      await jpost('/api/papers/' + curPaper.id + '/save', { stage: 'export', content: '已导出成稿：' + fname });
      await selectPaper(curPaper.id);
    } catch (_) { /* 标记失败不影响下载 */ }
    toast('已导出：' + fname, 'ok');
  } catch (e) {
    toast('导出失败：' + (e.message || e), 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📥 导出成稿'; }
  }
}

/* 回流知识库：POST /api/papers/{pid}/to_kb */
export async function toKb() {
  if (!curPaper) return;
  const btn = $id('btn-p-tokb');
  if (btn) { btn.disabled = true; btn.textContent = '回流中…'; }
  try {
    const d = await jpost('/api/papers/' + curPaper.id + '/to_kb', {});
    if (d && d.ok) {
      toast('已回流到知识库' + (d.kb_name ? '（' + d.kb_name + '）' : ''), 'ok');
    } else {
      toast('回流失败：' + ((d && d.detail) || '请先完成论文写作'), 'err');
    }
  } catch (e) {
    toast('回流失败：' + (e.message || e), 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '📚 回流知识库'; }
  }
}

export async function delPaper(id, title) {
  if (!confirm('删除课题「' + (title || '') + '」？\n该操作不可恢复，将同时删除全部 7 步产物。')) return;
  let d = null;
  try {
    const res = await fetch('/api/papers/' + id, { method: 'DELETE' });
    d = await res.json().catch(() => null);
  } catch (e) { d = null; }
  if (!d || !d.ok) { toast('删除失败', 'err'); return; }
  if (curPaper && curPaper.id === id) { curPaper = null; curStage = 'topic'; renderPaperPanel(); }
  loadPapers();
  toast('课题已删除', 'ok');
}

/* 右侧论文进度环 */
export function fillPaperProgress() {
  const box = $id('ps-paper-progress');
  if (!box) return;
  if (!curPaper) { box.innerHTML = '<div style="font-size:12px;color:var(--ml-text-faint)">选择课题后显示进度</div>'; return; }
  const p = curPaper.progress || {};
  const st = curPaper.stages || {};
  const refs = (st.search && st.search.refs) || [];
  const qScore = (st.quality && st.quality.content) || '';
  const m = qScore.match(/质量评分：(\d+)\s*\/\s*100/);
  box.innerHTML =
    '<div style="display:flex;align-items:center;gap:12px;margin-bottom:6px">' +
      '<div style="position:relative;width:52px;height:52px">' +
        '<svg viewBox="0 0 36 36" style="width:52px;height:52px;transform:rotate(-90deg)">' +
        '<circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--ml-ring-track)" stroke-width="4"/>' +
        '<circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--ml-sky)" stroke-width="4" stroke-linecap="round" stroke-dasharray="' + ((p.pct || 0) * 0.986) + ' 100"/>' +
        '</svg>' +
        '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--ml-text)">' + (p.pct || 0) + '%</div>' +
      '</div>' +
      '<div style="font-size:12px;line-height:1.7">' +
        '<div>完成 <b style="color:var(--ml-sky)">' + (p.done || 0) + '</b> / ' + (p.total || 7) + ' 步</div>' +
        '<div>引用白名单 <b style="color:var(--ml-ok)">' + refs.length + '</b> 条</div>' +
        (m ? '<div>质量评分 <b style="color:' + (Number(m[1]) >= 80 ? 'var(--ml-ok)' : 'var(--ml-warn)') + '">' + m[1] + '</b> 分</div>' : '') +
      '</div>' +
    '</div>';
}
