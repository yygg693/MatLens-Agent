/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · exp.js（实验工作流模板 + Canvas 数据可视化）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, renderMarkdown, jget, jpost, jdel, _cssVar } from './core.js';

const EXP_TPL_META = {
  standard: { icon: '📋', c: '#38bdf8', desc: '通用流程编排与标准化记录' },
  synthesis: { icon: '⚗️', c: '#6366f1', desc: '前驱体/温度/气氛/后处理 → 合成方案' },
  characterization: { icon: '🔬', c: '#34d399', desc: 'XRD/SEM/电化学 → 表征测试方案' },
  electrochem: { icon: '⚡', c: '#fbbf24', desc: 'CV/EIS/充放电 → 电化学测试方案' },
};
// 旧键 hydrothermal/solgel/calcination 后端已归并为 synthesis，前端元数据补一个映射，
// 使历史记录里的旧键也能显示图标。
const EXP_TPL_LEGACY = { hydrothermal: 'synthesis', solgel: 'synthesis', calcination: 'synthesis' };
let expTpl = 'standard';
let lastExpData = null;

/* ── 设置（动作时刻实时读 /api/settings）：默认模板 + 自动保存开关 ── */
let expSettings = { template: 'standard', autosave: true };
let _expAutosaveTimer = null;
let _expLastSavedSig = null;

async function loadExpSettings() {
  const d = await jget('/api/settings');
  if (d && d.ok && d.experiment) {
    expSettings.template = d.experiment.template || expSettings.template;
    expSettings.autosave = d.experiment.autosave !== false;
  }
  // 用设置默认模板选中（仅当用户还没在本页点过 tile——expTpl 默认值即代表未手动选）
  return expSettings.template;
}

function _expTplKey(raw) {
  return EXP_TPL_LEGACY[raw] || raw;
}

function _expProtocolSig() {
  if (!lastExpData) return null;
  return expTpl + '|' + (lastExpData.goal || '') + '|' + (lastExpData.steps ? lastExpData.steps.length : 0);
}

/* 60 秒自动保存：仅当 experiment.autosave=true 且已生成方案时启用；
 * 同一份方案只自动落一次（按签名去重，避免每 60s 插重复行）。手动保存仍随时可用。 */
function _applyExpAutosave() {
  if (_expAutosaveTimer) { clearInterval(_expAutosaveTimer); _expAutosaveTimer = null; }
  if (!expSettings.autosave) return;
  _expAutosaveTimer = setInterval(() => {
    if (!expSettings.autosave || !lastExpData) return;
    const sig = _expProtocolSig();
    if (!sig || sig === _expLastSavedSig) return;
    const protocol = JSON.stringify(Object.assign({ __autosaved: true }, lastExpData));
    jpost('/api/experiment/record', {
      title: '自动草稿 · ' + (($id('exp-goal') && $id('exp-goal').value || '').slice(0, 24) || '实验方案'),
      protocol: protocol,
      template: expTpl,
    }).then(r => {
      if (r && r.ok) { _expLastSavedSig = sig; loadExpRecords(); }
    }).catch(() => {});
  }, 60000);
}

export async function loadExpTemplates() {
  // 先读设置：默认模板 + autosave 开关
  await loadExpSettings();
  // 仅在尚未手动选择时（expTpl 仍为初始 'standard'）采用设置默认模板
  if (expTpl === 'standard') expTpl = expSettings.template || 'standard';
  expTpl = _expTplKey(expTpl);
  _applyExpAutosave();

  const d = await jget('/api/experiment/templates');
  const el = $id('exp-tiles');
  if (!el) return;
  if (!d || !d.templates || !d.templates.length) { el.innerHTML = ''; return; }
  // 后端返回的规范四键中若不含当前 expTpl（设置值异常），回退到第一个
  if (!d.templates.some(t => t.key === expTpl)) expTpl = d.templates[0].key;
  el.innerHTML = d.templates.map(t => {
    const meta = EXP_TPL_META[t.key] || { icon: '🧪', c: '#94a3b8', desc: t.applicable || '' };
    const sel = t.key === expTpl ? ' selected' : '';
    return '<div class="exp-tile' + sel + '" data-tpl="' + t.key + '">' +
      '<div class="tt-icon" style="background:' + meta.c + '14;color:' + meta.c + '">' + meta.icon + '</div>' +
      '<div class="tt-name" style="font-weight:700;font-size:13.5px">' + esc(t.name) + '</div>' +
      '<div class="tt-desc" style="font-size:12px;color:var(--ml-text-faint);margin-top:5px">' + esc(meta.desc) + '</div>' +
      '</div>';
  }).join('');
  // 事件委托
  el.querySelectorAll('.exp-tile').forEach(t => {
    t.onclick = () => selectExpTpl(t.dataset.tpl);
  });
  const tn = $id('exp-tpl-name');
  if (tn) tn.textContent = '· ' + ((d.templates.find(t => t.key === expTpl) || {}).name || '');
}

export function selectExpTpl(key) {
  expTpl = _expTplKey(key);
  loadExpTemplates();
}

export async function generateExp() {
  const goal = $id('exp-goal').value.trim();
  if (!goal) { toast('请输入研究目标'); return; }
  const btn = $id('btn-exp-generate');
  if (btn) { btn.textContent = '生成中…'; btn.disabled = true; }
  const d = await jpost('/api/experiment/generate', { goal: goal, template: expTpl });
  if (btn) { btn.textContent = '生成方案'; btn.disabled = false; }
  const el = $id('exp-result');
  if (!d || !d.ok) { el.innerHTML = '<div style="color:var(--ml-danger);font-size:13px">' + esc((d && d.detail) || '生成失败') + '</div>'; return; }
  el.innerHTML = renderProtocol(d);
  lastExpData = d;
  // 新方案：重置自动保存签名并重挂定时器（autosave 开关由 settings 决定）
  _expLastSavedSig = null;
  _applyExpAutosave();
}

function renderProtocol(d) {
  const toList = (x) => Array.isArray(x) ? x : (x ? String(x).split(/[,，、]/).map(s => s.trim()).filter(Boolean) : []);
  const steps = (d.steps || []).map((s, i) => '<div style="margin:5px 0;line-height:1.6"><b>' + (i + 1) + '.</b> ' + esc(typeof s === 'object' ? (s.step || s.name || JSON.stringify(s)) : s) + '</div>').join('');
  const reagents = toList(d.reagents).map(r => '<span class="tag" style="margin:2px">' + esc(r) + '</span>').join('');
  const equip = toList(d.equipment).map(r => '<span class="tag tag-blue" style="margin:2px">' + esc(r) + '</span>').join('');
  const safety = toList(d.safety).map(s => '<div style="margin:3px 0">⚠ ' + esc(s) + '</div>').join('');
  return '<div style="background:var(--ml-card);border:1px solid var(--ml-card-border);border-radius:12px;padding:16px">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">' +
      '<span style="font-weight:700">' + esc(d.goal || '') + '</span>' +
      '<span class="tag tag-purple">' + esc(d.template || '') + '</span>' +
    '</div>' +
    '<div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:8px">适用：' + esc(d.applicable || '') + '</div>' +
    '<div style="font-size:12px;font-weight:600;margin:10px 0 4px">🧪 试剂</div><div>' + (reagents || '—') + '</div>' +
    '<div style="font-size:12px;font-weight:600;margin:10px 0 4px">🔬 仪器</div><div>' + (equip || '—') + '</div>' +
    '<div style="font-size:12px;font-weight:600;margin:10px 0 4px">📋 步骤</div>' + (steps || '<div>—</div>') +
    '<div style="font-size:12px;font-weight:600;margin:10px 0 4px">🛡 安全</div>' + (safety || '—') +
    '<div style="font-size:11px;color:var(--ml-text-faint);margin-top:10px">' + esc(d.tips || '') + '</div>' +
    '<div style="margin-top:12px;display:flex;gap:8px">' +
      '<button class="btn btn-primary btn-sm" id="btn-exp-save">💾 保存为记录</button>' +
    '</div></div>';
  // 保存按钮绑定
  setTimeout(() => {
    const b = document.getElementById('btn-exp-save');
    if (b) b.onclick = () => saveExpRecord();
  }, 0);
}

export async function saveExpRecord() {
  const title = prompt('实验记录标题：', ($id('exp-goal').value.slice(0, 24) || '实验方案'));
  if (!title) return;
  let protocol;
  if (lastExpData) {
    protocol = JSON.stringify(Object.assign({ __saved: true }, lastExpData));
  } else {
    const protoEl = $id('exp-result');
    protocol = protoEl ? protoEl.innerHTML.slice(0, 8000) : '';
  }
  const d = await jpost('/api/experiment/record', { title: title, protocol: protocol, template: expTpl });
  if (d && d.ok) {
    toast('已保存实验记录', 'ok');
    _expLastSavedSig = _expProtocolSig();  // 手动保存后，自动保存不再重复落同一份
    loadExpRecords();
  }
  else toast('保存失败', 'err');
}

export async function loadExpRecords() {
  const d = await jget('/api/experiment/list');
  const el = $id('exp-records');
  if (!el) return;
  if (!d || !d.records || !d.records.length) { el.innerHTML = '<div style="font-size:12px;color:var(--ml-text-faint)">暂无记录 · 生成方案后保存</div>'; return; }
  el.innerHTML = d.records.map(r =>
    '<div class="mem-item" style="display:flex;justify-content:space-between;align-items:center">' +
      '<div style="min-width:0">' +
        '<div style="font-weight:600;font-size:12.5px">' + esc(r.title) + '</div>' +
        '<div style="font-size:11px;color:var(--ml-text-faint)">' + esc(r.created_at) + ' · ' + esc(r.template || '') + ' · ' + r.protocol_len + ' 字符</div>' +
      '</div>' +
      '<div style="display:flex;gap:6px">' +
        '<button class="btn btn-ghost btn-sm exp-view" data-id="' + r.id + '">查看</button>' +
        '<button class="btn btn-ghost btn-sm exp-del" data-id="' + r.id + '">删除</button>' +
      '</div>' +
    '</div>').join('');
  el.querySelectorAll('.exp-view').forEach(b => { b.onclick = () => viewExpRecord(b.dataset.id); });
  el.querySelectorAll('.exp-del').forEach(b => { b.onclick = () => delExpRecord(b.dataset.id); });
}

export async function viewExpRecord(id) {
  const d = await jget('/api/experiment/records/' + id);
  if (!d || !d.ok) { toast('记录不存在', 'err'); return; }
  const el = $id('exp-result');
  const raw = d.protocol || '';
  let html;
  try {
    const obj = JSON.parse(raw);
    if (obj && (obj.steps || obj.reagents || obj.goal)) {
      html = renderProtocol(obj);
    } else {
      throw new Error('not protocol json');
    }
  } catch (e) {
    const isHtml = raw.includes('<') && raw.includes('>');
    html = '<div style="background:var(--ml-card);border:1px solid var(--ml-card-border);border-radius:12px;padding:16px">' +
      '<div style="font-weight:700;margin-bottom:8px">' + esc(d.title) + '</div>' +
      '<div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:8px">' + esc(d.created_at) + '</div>' +
      '<div style="' + (isHtml ? '' : 'white-space:pre-wrap;') + 'font-size:13px;line-height:1.7;max-height:400px;overflow-y:auto">' + (isHtml ? raw : esc(raw)) + '</div>' +
      '</div>';
  }
  el.innerHTML = html;
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export async function delExpRecord(id) {
  if (!confirm('删除该实验记录？')) return;
  const d = await jdel('/api/experiment/records/' + id);
  if (d && d.ok) { toast('已删除', 'ok'); loadExpRecords(); }
  else toast('删除失败', 'err');
}

/* ── 数据可视化（Canvas） ─────────────────────────────── */
const VIZ = { mode: 'line', series: [], hover: null };
const VIZ_COLORS = ['#38bdf8', '#f472b6', '#34d399', '#fbbf24', '#a5b4fc', '#fb7185'];

function parseXY(text) {
  const groups = [[]];
  for (const raw of String(text || '').split('\n')) {
    const t = raw.trim();
    if (!t || t.startsWith('#')) {
      if (groups[groups.length - 1].length) groups.push([]);
      continue;
    }
    const parts = t.split(/[\s,;|\t]+/);
    const x = parseFloat(parts[0]);
    const y = parseFloat(parts[1]);
    if (!isNaN(x) && !isNaN(y)) groups[groups.length - 1].push({ x, y });
  }
  return groups.filter(g => g.length > 0);
}

function _setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w: rect.width, h: rect.height };
}

function _niceTicks(min, max, count) {
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  let step = Math.pow(10, Math.floor(Math.log10(range / count)));
  const err = (count / range) * step;
  let mult;
  if (err <= 0.15) mult = 10;
  else if (err <= 0.35) mult = 5;
  else if (err <= 0.75) mult = 2;
  else mult = 1;
  step *= mult;
  const start = Math.ceil(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.01; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

function _fmtNum(v) {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  if (Math.abs(v) >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

function _drawAxes(ctx, plot, xTicks, yTicks, xRange, yRange, xLabel, yLabel, colors) {
  const { x, y, w, h } = plot;
  const [x0, x1] = xRange;
  const [y0, y1] = yRange;
  ctx.strokeStyle = colors.grid;
  ctx.lineWidth = 1;
  ctx.font = '11px -apple-system,system-ui,sans-serif';
  ctx.fillStyle = colors.text;
  yTicks.forEach(v => {
    if (v < y0 || v > y1) return;
    const py = y + h - ((v - y0) / (y1 - y0)) * h;
    if (py < y || py > y + h) return;
    ctx.beginPath(); ctx.moveTo(x, py); ctx.lineTo(x + w, py); ctx.stroke();
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    ctx.fillText(_fmtNum(v), x - 8, py);
  });
  xTicks.forEach(v => {
    if (v < x0 || v > x1) return;
    const px = x + ((v - x0) / (x1 - x0)) * w;
    if (px < x || px > x + w) return;
    ctx.beginPath(); ctx.moveTo(px, y); ctx.lineTo(px, y + h); ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(_fmtNum(v), px, y + h + 6);
  });
  if (xLabel) { ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillText(xLabel, x + w / 2, y + h + 28); }
  if (yLabel) { ctx.save(); ctx.translate(14, y + h / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText(yLabel, 0, 0); ctx.restore(); }
  ctx.strokeStyle = colors.axis;
  ctx.strokeRect(x, y, w, h);
}

function drawLineChart(canvas, series, opts) {
  opts = opts || {};
  const { ctx, w, h } = _setupCanvas(canvas);
  const colors = {
    grid: _cssVar('--ml-card-border', '#e2e8f0') || '#e2e8f0',
    axis: _cssVar('--ml-text-faint', '#94a3b8') || '#94a3b8',
    text: _cssVar('--ml-text-dim', '#64748b') || '#64748b',
  };
  const plot = { x: 52, y: 18, w: w - 72, h: h - 62 };
  if (!series.length) {
    ctx.fillStyle = colors.text; ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('粘贴数据后点击「渲染」', w / 2, h / 2);
    return;
  }
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  series.forEach(s => s.forEach(p => {
    if (p.x < xMin) xMin = p.x; if (p.x > xMax) xMax = p.x;
    if (p.y < yMin) yMin = p.y; if (p.y > yMax) yMax = p.y;
  }));
  const xPad = (xMax - xMin) * 0.03 || 1;
  const yPad = (yMax - yMin) * 0.08 || 1;
  xMin -= xPad; xMax += xPad;
  yMin = (yMin >= 0) ? Math.max(0, yMin - yPad) : (yMin - yPad);
  yMax += yPad;
  const xTicks = _niceTicks(xMin, xMax, 6);
  const yTicks = _niceTicks(yMin, yMax, 5);
  const xRange = [xMin, xMax], yRange = [yMin, yMax];
  _drawAxes(ctx, plot, xTicks, yTicks, xRange, yRange, opts.xLabel || '', opts.yLabel || '', colors);
  const X = v => plot.x + ((v - xMin) / (xMax - xMin)) * plot.w;
  const Y = v => plot.y + plot.h - ((v - yMin) / (yMax - yMin)) * plot.h;
  series.forEach((s, si) => {
    if (s.length < 2) return;
    const color = VIZ_COLORS[si % VIZ_COLORS.length];
    const grad = ctx.createLinearGradient(0, plot.y, 0, plot.y + plot.h);
    grad.addColorStop(0, color + '33'); grad.addColorStop(1, color + '00');
    ctx.beginPath();
    ctx.moveTo(X(s[0].x), Y(s[0].y));
    s.forEach(p => ctx.lineTo(X(p.x), Y(p.y)));
    ctx.lineTo(X(s[s.length - 1].x), Y(yMin));
    ctx.lineTo(X(s[0].x), Y(yMin));
    ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    ctx.beginPath();
    ctx.moveTo(X(s[0].x), Y(s[0].y));
    s.forEach(p => ctx.lineTo(X(p.x), Y(p.y)));
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round'; ctx.stroke();
  });
  if (VIZ.hover) {
    const { mx, my } = VIZ.hover;
    if (mx >= plot.x && mx <= plot.x + plot.w && my >= plot.y && my <= plot.y + plot.h) {
      ctx.strokeStyle = colors.axis; ctx.setLineDash([4, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(mx, plot.y); ctx.lineTo(mx, plot.y + plot.h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(plot.x, my); ctx.lineTo(plot.x + plot.w, my); ctx.stroke();
      ctx.setLineDash([]);
      const hv = xMin + (mx - plot.x) / plot.w * (xMax - xMin);
      let nearest = null, minDist = Infinity;
      series.forEach(s => s.forEach(p => {
        const d = Math.abs(p.x - hv);
        if (d < minDist) { minDist = d; nearest = p; }
      }));
      if (nearest) {
        const px = X(nearest.x), py = Y(nearest.y);
        ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#fff'; ctx.fill();
        ctx.strokeStyle = VIZ_COLORS[0]; ctx.lineWidth = 2; ctx.stroke();
        const tip = document.getElementById('viz-tooltip');
        if (tip) {
          tip.style.display = 'block';
          tip.style.left = Math.min(mx + 12, plot.x + plot.w - 120) + 'px';
          tip.style.top = Math.max(my - 30, 4) + 'px';
          tip.innerHTML = '<b>x</b>=' + _fmtNum(nearest.x) + ' &nbsp; <b>y</b>=' + _fmtNum(nearest.y);
        }
      }
    }
  }
}

function drawPhaseDiagram(canvas, series, opts) {
  opts = opts || {};
  const { ctx, w, h } = _setupCanvas(canvas);
  const colors = {
    grid: _cssVar('--ml-card-border', '#e2e8f0') || '#e2e8f0',
    axis: _cssVar('--ml-text-faint', '#94a3b8') || '#94a3b8',
    text: _cssVar('--ml-text-dim', '#64748b') || '#64748b',
  };
  const plot = { x: 56, y: 18, w: w - 76, h: h - 62 };
  if (!series.length) {
    ctx.fillStyle = colors.text; ctx.font = '13px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('相图模式：空行分隔多条相界线（液相线/固相线等）', w / 2, h / 2);
    return;
  }
  let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
  series.forEach(s => s.forEach(p => {
    if (p.x < xMin) xMin = p.x; if (p.x > xMax) xMax = p.x;
    if (p.y < yMin) yMin = p.y; if (p.y > yMax) yMax = p.y;
  }));
  const xPad = (xMax - xMin) * 0.03 || 1;
  const yPad = (yMax - yMin) * 0.08 || 1;
  xMin -= xPad; xMax += xPad; yMin -= yPad; yMax += yPad;
  const xTicks = _niceTicks(xMin, xMax, 6);
  const yTicks = _niceTicks(yMin, yMax, 5);
  const xRange = [xMin, xMax], yRange = [yMin, yMax];
  _drawAxes(ctx, plot, xTicks, yTicks, xRange, yRange,
    opts.xLabel || '成分 / at.%', opts.yLabel || '温度 / ℃', colors);
  const X = v => plot.x + ((v - xMin) / (xMax - xMin)) * plot.w;
  const Y = v => plot.y + plot.h - ((v - yMin) / (yMax - yMin)) * plot.h;
  if (series.length >= 2) {
    for (let i = 0; i < series.length - 1; i++) {
      const a = series[i], b = series[i + 1];
      if (a.length < 2 || b.length < 2) continue;
      const color = VIZ_COLORS[i % VIZ_COLORS.length];
      ctx.beginPath();
      a.forEach(p => ctx.lineTo(X(p.x), Y(p.y)));
      for (let j = b.length - 1; j >= 0; j--) ctx.lineTo(X(b[j].x), Y(b[j].y));
      ctx.closePath();
      ctx.fillStyle = color + '18'; ctx.fill();
    }
  }
  const lineLabels = opts.lineLabels || [];
  series.forEach((s, si) => {
    if (s.length < 2) return;
    const color = VIZ_COLORS[si % VIZ_COLORS.length];
    ctx.beginPath();
    ctx.moveTo(X(s[0].x), Y(s[0].y));
    s.forEach(p => ctx.lineTo(X(p.x), Y(p.y)));
    ctx.strokeStyle = color; ctx.lineWidth = 2.2; ctx.lineJoin = 'round'; ctx.stroke();
    s.forEach((p, pi) => {
      if (pi === 0 || pi === s.length - 1) {
        ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), 3.5, 0, Math.PI * 2);
        ctx.fillStyle = color; ctx.fill();
      }
    });
    const label = lineLabels[si] || ('相界线 ' + (si + 1));
    const mid = s[Math.floor(s.length / 2)];
    if (mid) {
      ctx.font = '10px sans-serif'; ctx.fillStyle = color;
      ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
      ctx.fillText(label, X(mid.x) + 6, Y(mid.y) - 4);
    }
  });
  if (opts.tieLine) {
    const { x1: tx1, x2: tx2, y: ty } = opts.tieLine;
    ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 1.5; ctx.setLineDash([6, 4]);
    ctx.beginPath(); ctx.moveTo(X(tx1), Y(ty)); ctx.lineTo(X(tx2), Y(ty)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#ef4444'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('结线 (tie-line)', X((tx1 + tx2) / 2), Y(ty) - 6);
  }
}

function renderViz() {
  const canvas = document.getElementById('viz-canvas');
  if (!canvas) return;
  const text = document.getElementById('viz-data').value;
  VIZ.series = parseXY(text);
  const stats = document.getElementById('viz-stats');
  const totalPts = VIZ.series.reduce((a, s) => a + s.length, 0);
  if (stats) stats.innerHTML = '数据组：<b>' + VIZ.series.length + '</b> · 数据点：<b>' + totalPts + '</b>' +
    (VIZ.series.length > 1 ? ' · ' + VIZ.series.map((s, i) => '组' + (i + 1) + '=' + s.length + '点').join(' · ') : '');
  const isPhase = VIZ.mode === 'phase';
  const opts = {
    xLabel: isPhase ? (document.getElementById('viz-xlabel')?.value || '') : '',
    yLabel: isPhase ? (document.getElementById('viz-ylabel')?.value || '') : '',
  };
  if (isPhase) drawPhaseDiagram(canvas, VIZ.series, opts);
  else drawLineChart(canvas, VIZ.series, opts);
}

export function initViz() {
  const canvas = document.getElementById('viz-canvas');
  if (!canvas) return;
  document.querySelectorAll('.viz-tab').forEach(tab => {
    tab.onclick = () => {
      document.querySelectorAll('.viz-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      VIZ.mode = tab.dataset.viz;
      const po = document.getElementById('viz-phase-opts');
      if (po) po.style.display = VIZ.mode === 'phase' ? 'flex' : 'none';
      renderViz();
    };
  });
  const renderBtn = document.getElementById('viz-render');
  if (renderBtn) renderBtn.onclick = renderViz;
  const demoBtn = document.getElementById('viz-demo');
  if (demoBtn) demoBtn.onclick = () => {
    const ta = document.getElementById('viz-data');
    if (VIZ.mode === 'phase') {
      ta.value = '# Pb-Sn 二元相图示意（空行分隔液相线/固相线）\n# 液相线\n0 327\n20 275\n40 225\n61.9 183\n80 200\n100 232\n\n# 固相线\n0 327\n20 183\n40 183\n61.9 183\n80 183\n100 232';
      document.getElementById('viz-xlabel').value = 'Sn 含量 / wt.%';
      document.getElementById('viz-ylabel').value = '温度 / ℃';
    } else {
      ta.value = '# XRD 图谱示例（2θ vs 强度）\n10 120\n15 95\n20 850\n25 180\n30 200\n35 620\n40 150\n45 410\n50 130\n60 280\n70 90\n80 160';
    }
    renderViz();
  };
  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    VIZ.hover = { mx: e.clientX - rect.left, my: e.clientY - rect.top };
    if (VIZ.mode === 'line') renderViz();
  });
  canvas.addEventListener('mouseleave', () => {
    VIZ.hover = null;
    const tip = document.getElementById('viz-tooltip');
    if (tip) tip.style.display = 'none';
    renderViz();
  });
  renderViz();
}
