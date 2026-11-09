/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · graph.js（记忆侧栏 / 知识图谱 / 记忆管理页）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jpost, jdel } from './core.js';

/* ── 右侧记忆侧栏 ─────────────────────────────────────── */
/** 右栏记忆面板（2026-10-15 迁至 chat_right.js 重写版）。
 *  保留此导出名是为了不改 3 处调用点（main.js / chat_sse.js ×2）。 */
export async function loadMemory() {
  const m = await import('./chat_right.js');
  return m.refreshRightPanel();
}

/* ── 知识图谱（vis-network） ─────────────────────────── */

// 类别 → 节点颜色（任务约定：材料=蓝、方法=绿、性质=橙、参数=灰）
const NODE_COLORS = {
  '材料': '#38bdf8',
  '方法': '#22c55e',
  '性质': '#f97316',
  '参数': '#9ca3af',
  '用户': '#6366f1',
  '实验': '#2dd4bf',
  '结论': '#f59e0b',
  '其他': '#94a3b8',
};

let _visGraph = null;       // vis.Network 实例
let _visNodes = null;       // vis DataSet
let _visEdges = null;
let _rawGraph = null;       // 最近一次 /api/graph 响应

function _loadVisNetwork() {
  // 已加载则直接返回
  if (typeof window !== 'undefined' && window.vis && window.vis.Network) {
    return Promise.resolve(window.vis);
  }
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js';
    s.async = true;
    s.onload = () => resolve(window.vis);
    s.onerror = () => reject(new Error('vis-network CDN 加载失败'));
    document.head.appendChild(s);
  });
}

function _ensureGraphContainer() {
  // 记忆中心「实体图谱」视图里的静态容器（index.html 已声明，不再动态注入）
  return document.getElementById('vis-graph-canvas');
}

function _renderDetailPanel(nodeId) {
  const panel = document.getElementById('mem-graph-detail');
  if (!panel || !_rawGraph) return;
  const nodes = _rawGraph.nodes || [];
  const edges = _rawGraph.edges || [];
  const node = nodes.find(n => String(n.id) === String(nodeId));
  if (!node) return;
  const cat = node.category || '其他';
  const color = NODE_COLORS[cat] || NODE_COLORS['其他'];
  // 关联边
  const rel = edges.filter(e => String(e.source) === String(nodeId) || String(e.target) === String(nodeId));
  const relHtml = rel.map(e => {
    const otherId = String(e.source) === String(nodeId) ? e.target : e.source;
    const other = nodes.find(n => String(n.id) === String(otherId));
    const otherLabel = other ? (other.label || other.id) : otherId;
    const dir = String(e.source) === String(nodeId) ? '→' : '←';
    return '<div class="mem-item" style="margin-top:5px">' +
      '<span class="mem-cat" style="background:' + color + '22;color:' + color + '">' + esc(cat) + '</span>' +
      ' ' + esc(e.label || '关系') + ' ' + dir + ' ' + esc(otherLabel) + '</div>';
  }).join('');
  panel.innerHTML =
    '<div style="font-weight:700;margin-bottom:4px;font-size:14px">' + esc(node.label || node.id) + '</div>' +
    '<div style="font-size:11px;color:var(--ml-text-faint);margin-bottom:10px">' + esc(cat) + ' · ' + rel.length + ' 条关联</div>' +
    '<div style="font-size:12px;color:var(--ml-text-dim);line-height:1.7;margin-bottom:8px">' +
    '该实体由 DeepSeek 从对话记忆中抽取，来源为本项目积累的材料科研对话。</div>' +
    (relHtml || '<div style="font-size:12px;color:var(--ml-text-faint)">暂无关联关系</div>');
}

export async function loadGraph() {
  const d = await jget('/api/graph');
  if (!d || !d.nodes) {
    const dd = document.getElementById('mem-graph-detail');
    if (dd) dd.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div><div style="font-size:12px;color:var(--ml-text-faint)">图谱后端暂不可用</div>';
    return;
  }
  _rawGraph = d;
  const countEl = document.getElementById('mem-graph-detail');
  if (countEl) {
    countEl.innerHTML = '<div style="font-weight:700;margin-bottom:8px;font-size:13px">实体图谱</div>' +
      '<div style="font-size:11.5px;color:var(--ml-text-faint);line-height:1.8">' +
      (d.fallback ? '示例图谱 · ' : '') + d.nodes.length + ' 实体 · ' + (d.edges ? d.edges.length : 0) +
      ' 关系<br>点击节点查看关联实体与来源。</div>';
  }

  if (!d.nodes.length) return;

  // 确保容器存在
  const container = _ensureGraphContainer();
  if (!container) return;

  try {
    const vis = await _loadVisNetwork();
    // 转 vis DataSet
    _visNodes = new vis.DataSet(d.nodes.map(n => {
      const cat = n.category || '其他';
      return {
        id: String(n.id),
        label: n.label || n.id,
        group: cat,
        color: { background: n.color || NODE_COLORS[cat] || NODE_COLORS['其他'], border: '#ffffff33' },
        font: { color: '#e2e8f0', size: 13 },
        value: n.val || 1,
      };
    }));
    _visEdges = new vis.DataSet(d.edges.map((e, i) => ({
      id: 'e' + i,
      from: String(e.source),
      to: String(e.target),
      label: e.label || '',
      arrows: 'to',
      color: { color: '#475569', highlight: '#38bdf8' },
      font: { color: '#94a3b8', size: 10, strokeWidth: 0 },
      smooth: { type: 'continuous' },
    })));

    const data = { nodes: _visNodes, edges: _visEdges };
    const options = {
      physics: {
        barnesHut: { gravitationalConstant: -4500, springLength: 140, springConstant: 0.04, damping: 0.4 },
        stabilization: { iterations: 150 },
      },
      interaction: { hover: true, tooltipDelay: 120 },
      nodes: { shape: 'dot', scaling: { min: 12, max: 32 } },
      edges: { width: 1.2 },
    };
    if (_visGraph) { _visGraph.destroy(); _visGraph = null; }
    _visGraph = new vis.Network(container, data, options);

    // 点击节点 → 高亮关联边 + 右侧面板
    _visGraph.on('click', (params) => {
      if (params.nodes && params.nodes.length) {
        const nodeId = params.nodes[0];
        // 高亮关联边：只保留与该节点相连的边高亮，其余变淡
        const connected = _visEdges.get().filter(e =>
          String(e.from) === String(nodeId) || String(e.to) === String(nodeId)
        ).map(e => e.id);
        _visEdges.forEach(e => {
          const active = connected.includes(e.id);
          _visEdges.update({
            id: e.id,
            color: { color: active ? '#38bdf8' : '#334155', highlight: '#38bdf8' },
            width: active ? 2.2 : 1.0,
            dashes: active ? false : true,
          });
        });
        _renderDetailPanel(nodeId);
      }
    });
  } catch (e) {
    // CDN 失败降级为文字列表
    const dd = document.getElementById('mem-graph-detail');
    if (dd) dd.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div>' +
      '<div style="font-size:12px;color:var(--ml-warn)">图谱可视化库加载失败，显示实体列表：</div>' +
      d.nodes.slice(0, 15).map(n => '<div class="mem-item"><span class="mem-cat" style="color:' + (n.color || '#94a3b8') + '">●</span> ' + esc(String(n.label || n.id)) + '</div>').join('');
  }
}

/* ── 记忆中心：概览 / 列表 / 详情 三栏 ─────────────────── */
let _memAll = [];            // 浏览态：一次拉满的全量记忆
let _memHits = [];           // 搜索态：后端语义检索结果
let _memQuery = '';
let _memView = 'all';        // 'all' | 'cat:<分类>' | 'dup'
let _memSelected = null;     // 当前选中记忆 id
let _memDupGroups = [];      // 疑似重复分组 [{ids:[], items:[]}]（优先用后端 /duplicates）
let _memSuperseded = {};     // 已合并掉的内存 id → {keep_id, at}
let _memSupersededRows = [];  // 已合并条目的完整行（「已合并」视图用）
let _memTotal = null;
let _memEditingId = null;
const MEM_FETCH_LIMIT = 200; // 浏览态一次拉取的条数（后端上限 200）

const CAT_ORDER = ['用户', '实验', '材料', '结论', '其他'];
const CAT_COLORS = {
  用户: '#38bdf8', 实验: '#34d399', 材料: '#818cf8', 结论: '#fbbf24', 其他: '#94a3b8',
};
/** source_type → 人话。与 dashboard 的 MemoryPage 保持同一套语义。 */
const SOURCE_LABELS = {
  user: '用户陈述',
  document: '文献',
  agent_inference: 'Agent 推断',
  imported_web: '网络导入',
};

/** 进入记忆页 / 刷新时调用：清掉选中态再重载。 */
export function reloadMemories() {
  _memSelected = null;
  return loadMemories();
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

/* 相似度聚类：把"同一件事写了多遍"的记忆归成一组，供去重治理使用。
   朴素二元组 Jaccard 足够用——127 条两两比较不到 1 万次，毫秒级。 */
function _normForSim(s) {
  return String(s || '')
    .replace(/^\[[^\]]{1,8}\]/, '')
    .replace(/[\s\u3000]/g, '')
    .replace(/[，。；：、！？·“”"'（）()【】\[\],.;:!?\-]/g, '')
    .toLowerCase();
}
function _bigrams(s) {
  const g = new Set();
  for (let i = 0; i < s.length - 1; i++) g.add(s.slice(i, i + 2));
  return g;
}
function _simScore(a, b) {
  if (!a.size || !b.size) return 0;
  let inter = 0;
  a.forEach(x => { if (b.has(x)) inter++; });
  return inter / (a.size + b.size - inter);
}
/** 返回疑似重复分组（每组 ≥2 条），组内按相似度从高到低。 */
function computeDupGroups(items, threshold) {
  const th = typeof threshold === 'number' ? threshold : 0.5;
  const grams = items.map(m => _bigrams(_normForSim(m.memory)));
  const parent = items.map((_, i) => i);
  const find = i => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  const union = (i, j) => { const a = find(i), b = find(j); if (a !== b) parent[b] = a; };
  const pairs = [];
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const sc = _simScore(grams[i], grams[j]);
      if (sc >= th) { union(i, j); pairs.push({ i, j, sc }); }
    }
  }
  const buckets = new Map();
  items.forEach((m, i) => {
    const root = find(i);
    if (!buckets.has(root)) buckets.set(root, []);
    buckets.get(root).push({ item: m, idx: i });
  });
  const groups = [];
  buckets.forEach(list => {
    if (list.length < 2) return;
    let best = 0;
    pairs.forEach(p => {
      if (find(p.i) === find(list[0].idx)) best = Math.max(best, p.sc);
    });
    groups.push({
      ids: list.map(x => String(x.item.id || '')),
      items: list.map(x => x.item),
      score: best,
    });
  });
  groups.sort((a, b) => b.items.length - a.items.length || b.score - a.score);
  return groups;
}

/** 拉后端算好的重复簇；后端不可用时回退到本地同构算法。
 *
 * 判定逻辑只留在后端一处（plugins/memory/mem0/_dedup.py），前端这份
 * 只是降级兜底，避免两套阈值各自漂移。
 */
async function fetchDupGroups(all) {
  try {
    const r = await fetch('/api/memory/duplicates');
    if (r.ok) {
      const d = await r.json();
      if (d && Array.isArray(d.groups)) {
        const byId = new Map(all.map(m => [String(m.id), m]));
        return d.groups
          .map(g => ({
            ids: g.ids,
            score: g.score || 0,
            items: g.ids.map(id => byId.get(String(id))).filter(Boolean),
          }))
          .filter(g => g.items.length > 1);
      }
    }
  } catch (e) { /* 落到本地兜底 */ }
  return computeDupGroups(all, 0.5);
}

export async function loadMemories() {
  const list = document.getElementById('mem-list');
  if (list) list.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">加载中…</div>';
  try {
    if (_memQuery) {
      const r = await fetch('/api/memory?q=' + encodeURIComponent(_memQuery) + '&limit=60');
      const data = await r.json();
      _memHits = data.memories || [];
      _memTotal = (typeof data.total === 'number') ? data.total : null;
    } else {
      const r = await fetch('/api/memory?offset=0&limit=' + MEM_FETCH_LIMIT);
      const data = await r.json();
      _memAll = data.memories || [];
      _memTotal = (typeof data.total === 'number') ? data.total : null;
      _memSuperseded = {};
      _memAll.forEach(m => {
        if (m.superseded_by) {
          _memSuperseded[String(m.id)] = { keep_id: m.superseded_by, at: m.superseded_at };
        }
      });
      // 列表默认已过滤掉合并过的条目，这里单独再拉一次带 include_superseded，
      // 供「已合并」视图展示与撤销——否则那个视图永远是空的。
      try {
        const r2 = await fetch('/api/memory?offset=0&limit=' + MEM_FETCH_LIMIT + '&include_superseded=true');
        const d2 = await r2.json();
        _memSupersededRows = (d2.memories || []).filter(m => m.superseded_by);
        _memSupersededRows.forEach(m => {
          _memSuperseded[String(m.id)] = { keep_id: m.superseded_by, at: m.superseded_at };
        });
      } catch (e2) {
        _memSupersededRows = [];
      }
      _memDupGroups = await fetchDupGroups(_memAll);
    }
    // 选中的那条如果已经不在数据里，清掉选中态
    const all = _memQuery ? _memHits : _memAll;
    if (_memSelected && !all.some(m => String(m.id) === _memSelected)) _memSelected = null;
    renderOverview();
    renderRows();
    renderDetail();
  } catch (e) {
    if (list) {
      list.innerHTML = '<div style="color:var(--ml-danger);font-size:13px;padding:40px;text-align:center">加载失败：' +
        escapeHtml(e.message) + '</div>' +
        '<div style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="loadMemories()">重试</button></div>';
    }
  }
}

/** 当前视图下要展示的记忆。已被合并掉的条目只在「已合并」视图里出现。 */
function currentItems() {
  const all = _memQuery ? _memHits : _memAll;
  if (_memQuery) return all;
  if (_memView === 'superseded') {
    return _memSupersededRows;
  }
  const visible = all.filter(m => !_memSuperseded[String(m.id)]);
  if (_memView === 'dup') {
    const ids = new Set();
    _memDupGroups.forEach(g => g.ids.forEach(id => ids.add(id)));
    return visible.filter(m => ids.has(String(m.id)));
  }
  if (_memView.indexOf('cat:') === 0) {
    const cat = _memView.slice(4);
    return visible.filter(m => (m.category || '其他') === cat);
  }
  return visible;
}

function memDate(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d.getTime())) return '';
  const p = n => (n < 10 ? '0' + n : '' + n);
  return (d.getMonth() + 1) + '-' + p(d.getDate());
}

function memDateTime(s) {
  if (!s) return '';
  const d = new Date(s);
  if (isNaN(d.getTime())) return '';
  const p = n => (n < 10 ? '0' + n : '' + n);
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

/** 列表上方的状态行（总数 / 当前显示 / 搜索态）。 */
function statusLine() {
  const box = document.getElementById('mem-count');
  const tabCount = document.getElementById('mt-list-count');
  const all = _memQuery ? _memHits : _memAll;
  const shown = currentItems().length;
  const totalN = _memTotal !== null ? _memTotal : all.length;
  if (tabCount) tabCount.textContent = totalN;
  if (!box) return;
  let html;
  if (_memQuery) {
    html = '<span>语义检索命中 <b style="color:var(--ml-text)">' + totalN + '</b> 条</span>' +
      '<span>· 已显示 <b style="color:var(--ml-text)">' + shown + '</b></span>';
  } else {
    html = '<span>共 <b style="color:var(--ml-text)">' + totalN + '</b> 条</span>' +
      '<span>· 当前显示 <b style="color:var(--ml-text)">' + shown + '</b></span>';
    if (_memTotal !== null && _memTotal > all.length) {
      html += '<span style="color:var(--ml-warn)">· 仅加载前 ' + all.length + ' 条</span>';
    }
  }
  box.innerHTML = html;
}

/** 左栏：总数 + 分类占比 + 治理入口。计数基于全量数据，不是当前页。 */
function renderOverview() {
  const box = document.getElementById('mem-overview');
  if (!box) return;
  const raw = _memQuery ? _memHits : _memAll;
  // 分类占比只统计"在场"的记忆：已合并掉的不该继续占份额。
  const all = _memQuery ? raw : raw.filter(m => !_memSuperseded[String(m.id)]);
  const counts = {};
  all.forEach(m => { const c = m.category || '其他'; counts[c] = (counts[c] || 0) + 1; });
  const base = all.length || 1;
  const catRows = CAT_ORDER.map(c => {
    const n = counts[c] || 0;
    const pct = Math.round(n / base * 100);
    const active = _memView === 'cat:' + c;
    return '<div class="mc-ov-cat' + (active ? ' active' : '') + '" data-cat="' + c + '">' +
      '<div class="row"><span>' + c + '</span><span>' + n + '</span></div>' +
      '<div class="bar"><div class="fill" style="width:' + pct + '%;background:' + CAT_COLORS[c] + '"></div></div>' +
      '</div>';
  }).join('');
  const extra = Object.keys(counts).filter(c => CAT_ORDER.indexOf(c) < 0);
  const extraRows = extra.map(c => '<div class="mc-ov-cat' + (_memView === 'cat:' + c ? ' active' : '') +
    '" data-cat="' + escapeHtml(c) + '"><div class="row"><span>' + escapeHtml(c) + '</span><span>' +
    counts[c] + '</span></div></div>').join('');

  const noSrc = all.filter(m => !m.source_type).length;
  const mergedCount = Object.keys(_memSuperseded).length;
  const dupGroups = _memQuery ? 0 : _memDupGroups.length;
  const dupItems = _memQuery ? 0 : _memDupGroups.reduce((s, g) => s + g.items.length, 0);

  box.innerHTML =
    '<div class="mc-ov-hero"><div class="n">' + all.length + '</div>' +
    '<div class="l">条有效记忆 · Mem0 语义检索</div></div>' +
    '<div class="mc-ov-sec"><div class="t">分类</div>' +
    '<div class="mc-ov-cat' + (_memView === 'all' ? ' active' : '') + '" data-cat="all">' +
    '<div class="row"><span>全部</span><span>' + all.length + '</span></div>' +
    '<div class="bar"><div class="fill" style="width:100%;background:var(--ml-grad)"></div></div></div>' +
    catRows + extraRows + '</div>' +
    '<div class="mc-ov-sec"><div class="t">治理</div>' +
    '<div class="mc-gov-item' + (_memView === 'dup' ? ' active' : '') + '" data-gov="dup"><span class="k">疑似重复</span>' +
    '<span class="v">' + dupGroups + ' 组 / ' + dupItems + ' 条</span></div>' +
    '<div class="mc-gov-item" data-gov="nosrc"><span class="k">无来源标记</span>' +
    '<span class="v">' + noSrc + ' 条</span></div>' +
    (mergedCount ? '<div class="mc-gov-item' + (_memView === 'superseded' ? ' active' : '') +
      '" data-gov="superseded"><span class="k">已合并</span>' +
      '<span class="v">' + mergedCount + ' 条 · 可撤销</span></div>' : '') +
    '</div>';

  box.querySelectorAll('.mc-ov-cat').forEach(el => {
    el.onclick = () => {
      const c = el.dataset.cat;
      _memView = c === 'all' ? 'all' : 'cat:' + c;
      renderOverview(); renderRows();
    };
  });
  box.querySelectorAll('.mc-gov-item').forEach(el => {
    el.onclick = () => {
      if (el.dataset.gov === 'dup') {
        if (!_memDupGroups.length) { alert('当前没有检测到疑似重复的记忆。'); return; }
        _memView = 'dup';
      } else if (el.dataset.gov === 'superseded') {
        _memView = 'superseded';
      } else {
        _memView = 'all';
      }
      renderOverview(); renderRows();
    };
  });
}

function rowHtml(m) {
  const cat = m.category || '其他';
  const color = CAT_COLORS[cat] || '#94a3b8';
  const meta = ['<span class="mr-cat" style="background:' + color + '22;color:' + color + '">' + escapeHtml(cat) + '</span>'];
  if (m.source_type) meta.push('<span>' + escapeHtml(SOURCE_LABELS[m.source_type] || m.source_type) + '</span>');
  if (typeof m.confidence === 'number') meta.push('<span>置信度 ' + Math.round(m.confidence * 100) + '%</span>');
  if (m.created_at) meta.push('<span>' + memDate(m.created_at) + '</span>');
  if (m.score) meta.push('<span>相关度 ' + (m.score * 100).toFixed(0) + '%</span>');
  if (_memSuperseded[String(m.id)]) meta.push('<span style="color:var(--ml-warn)">已合并</span>');
  const sel = String(m.id) === _memSelected ? ' sel' : '';
  const idEsc = escapeHtml(String(m.id || ''));
  return '<div class="mem-row' + sel + '" data-mid="' + idEsc + '">' +
    '<span class="mr-bar" style="background:' + color + '"></span>' +
    '<div class="mr-main"><div class="mr-text">' + escapeHtml(m.memory) + '</div>' +
    '<div class="mr-meta">' + meta.join('') + '</div></div>' +
    '<div class="mr-ops"><button class="edit" data-id="' + idEsc + '" title="编辑">✎</button>' +
    '<button class="del" data-id="' + idEsc + '" title="删除">✕</button></div>' +
    '</div>';
}

/** 中栏：行式列表。重复视图下按组分段显示。 */
function renderRows() {
  const list = document.getElementById('mem-list');
  if (!list) return;
  statusLine();
  const items = currentItems();
  if (!items.length) {
    list.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">' +
      (_memQuery ? '没有匹配的记忆' : '暂无记忆') + '</div>';
    return;
  }
  let html = '';
  if (_memView === 'dup' && !_memQuery) {
    _memDupGroups.forEach((g, gi) => {
      const keep = _richestOf(g.items);
      html += '<div style="display:flex;align-items:center;justify-content:space-between;' +
        'font-size:11px;color:var(--ml-text-faint);padding:10px 2px 3px">' +
        '<span>重复组 ' + (gi + 1) + ' · ' + g.items.length + ' 条 · 相似度 ' +
        Math.round((g.score || 0) * 100) + '%</span>' +
        '<button class="btn btn-ghost btn-sm" data-merge-keep="' + escapeHtml(String(keep.id)) + '">合并为一条</button>' +
        '</div>';
      g.items.forEach(m => { html += rowHtml(m); });
    });
  } else {
    items.forEach(m => { html += rowHtml(m); });
  }
  list.innerHTML = html;
  list.querySelectorAll('.mem-row').forEach(el => {
    el.onclick = () => { _memSelected = el.dataset.mid; renderRows(); renderDetail(); };
  });
  list.querySelectorAll('[data-merge-keep]').forEach(btn => {
    btn.onclick = (ev) => { ev.stopPropagation(); mergeGroup(btn.dataset.mergeKeep); };
  });
  list.querySelectorAll('.mr-ops .edit').forEach(btn => {
    btn.onclick = (ev) => {
      ev.stopPropagation();
      const item = currentItems().find(x => String(x.id) === btn.dataset.id);
      if (item) openMemModal(item);
    };
  });
  list.querySelectorAll('.mr-ops .del').forEach(btn => {
    btn.onclick = (ev) => { ev.stopPropagation(); deleteMemory(btn.dataset.id); };
  });
}

/** 右栏：选中记忆的详情 + 相似记忆 + 操作。 */
function renderDetail() {
  const panel = document.getElementById('mem-detail-panel');
  if (!panel) return;
  const items = currentItems();
  const item = _memSelected ? items.find(m => String(m.id) === _memSelected) : null;
  if (!item) {
    panel.innerHTML = '<div class="d-empty">选中列表中任意一条记忆<br>查看完整内容、来源与相似记忆</div>';
    return;
  }
  const cat = item.category || '其他';
  const color = CAT_COLORS[cat] || '#94a3b8';
  const tags = ['<span class="mc-badge" style="background:' + color + '22;color:' + color + ';border-color:' + color + '44">' + escapeHtml(cat) + '</span>'];
  if (item.source_type) tags.push('<span class="mc-badge">' + escapeHtml(SOURCE_LABELS[item.source_type] || item.source_type) + '</span>');
  if (typeof item.confidence === 'number') tags.push('<span class="mc-badge">置信度 ' + Math.round(item.confidence * 100) + '%</span>');
  if (item.score) tags.push('<span class="mc-badge">相关度 ' + (item.score * 100).toFixed(0) + '%</span>');

  const sim = _memDupGroups.find(g => g.ids.indexOf(String(item.id)) >= 0);
  const simOthers = sim ? sim.items.filter(m => String(m.id) !== String(item.id)) : [];
  const sup = _memSuperseded[String(item.id)];

  panel.innerHTML =
    '<div class="d-tags">' + tags.join('') + '</div>' +
    (sup ? '<div class="d-meta" style="color:var(--ml-warn)"><div><span class="k">状态</span>' +
      '<span class="v">已合并到 ' + escapeHtml(String(sup.keep_id || '').slice(0, 8)) + '</span></div></div>' : '') +
    '<div class="d-text">' + escapeHtml(item.memory) + '</div>' +
    '<div class="d-meta">' +
    (item.source_ref ? '<div><span class="k">来源引用</span><span class="v">' + escapeHtml(item.source_ref) + '</span></div>' : '') +
    (item.created_at ? '<div><span class="k">创建于</span><span class="v">' + memDateTime(item.created_at) + '</span></div>' : '') +
    (item.updated_at ? '<div><span class="k">更新于</span><span class="v">' + memDateTime(item.updated_at) + '</span></div>' : '') +
    '<div><span class="k">ID</span><span class="v">' + escapeHtml(String(item.id || '')) + '</span></div>' +
    '</div>' +
    (simOthers.length ? '<div class="mc-ov-sec"><div class="t">相似记忆 ' + simOthers.length + ' 条</div><div class="mc-sim">' +
      simOthers.map(m => '<div class="s" data-mid="' + escapeHtml(String(m.id)) + '">' + escapeHtml(m.memory) + '</div>').join('') +
      '</div></div>' : '') +
    '<div class="d-ops">' +
    (sup
      ? '<button class="btn btn-ghost" id="mem-detail-restore">撤销合并</button>'
      : (simOthers.length ? '<button class="btn btn-ghost" id="mem-detail-merge">合并其余 ' + simOthers.length + ' 条</button>' : '')) +
    '<button class="btn btn-ghost" id="mem-detail-edit">编辑</button>' +
    '<button class="btn btn-ghost" id="mem-detail-del" style="color:#ef4444">删除</button>' +
    '</div>';

  const eb = document.getElementById('mem-detail-edit');
  if (eb) eb.onclick = () => openMemModal(item);
  const db = document.getElementById('mem-detail-del');
  if (db) db.onclick = () => deleteMemory(String(item.id));
  const rb = document.getElementById('mem-detail-restore');
  if (rb) rb.onclick = () => restoreMemory([String(item.id)]);
  const mb = document.getElementById('mem-detail-merge');
  if (mb) mb.onclick = () => mergeGroup(String(item.id));
  panel.querySelectorAll('.mc-sim .s').forEach(el => {
    el.onclick = () => { _memSelected = el.dataset.mid; renderRows(); renderDetail(); };
  });
}

async function deleteMemory(id) {
  if (!confirm('确定删除这条记忆？删除后不可恢复。')) return;
  try {
    await fetch('/api/memory/' + encodeURIComponent(id), { method: 'DELETE' });
    if (_memSelected === id) _memSelected = null;
    await loadMemories();
  } catch (e) {
    alert('删除失败：' + e.message);
  }
}

/** 组内表述最全的那条——合并默认保留它，避免合完反而丢信息。 */
function _richestOf(items) {
  let best = items[0];
  items.forEach(m => { if (String(m.memory || '').length > String(best.memory || '').length) best = m; });
  return best;
}

/** 把一组近重复合并成一条。
 *
 * 走后端的 supersede：保留最全的那条，其余只标为"已合并"，随时能撤销。
 * 不做物理删除——合并判断可能有误，不可逆的代价太大。
 */
async function mergeGroup(keepId) {
  const g = _memDupGroups.find(x => x.ids.indexOf(String(keepId)) >= 0);
  if (!g || g.ids.length < 2) return;
  const keep = g.items.find(m => String(m.id) === String(keepId)) || _richestOf(g.items);
  if (!confirm('把这组 ' + g.ids.length + ' 条合并为 1 条？\n\n保留：' +
      String(keep.memory || '').slice(0, 80) + '\n\n其余 ' + (g.ids.length - 1) +
      ' 条标记为已合并（不删除，可随时撤销）。')) return;
  try {
    const r = await fetch('/api/memory/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ids: g.ids,
        keep: String(keep.id),
        mode: 'supersede',
        merged_text: String(keep.memory || ''),
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '合并失败');
    await loadMemories();
  } catch (e) {
    alert('合并失败：' + e.message);
  }
}

/** 撤销合并：把条目放回列表。 */
async function restoreMemory(ids) {
  try {
    const r = await fetch('/api/memory/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    if (!r.ok) throw new Error('撤销失败');
    await loadMemories();
  } catch (e) {
    alert('撤销失败：' + e.message);
  }
}

/** 打开记忆弹窗：item 为空 → 新增；传入记忆 → 编辑预填。 */
function openMemModal(item) {
  const modal = document.getElementById('mem-modal');
  const title = document.getElementById('mem-modal-title');
  const hint = document.getElementById('mem-modal-hint');
  const area = document.getElementById('mem-new-text');
  const save = document.getElementById('btn-mem-save');
  if (!modal || !area) return;
  _memEditingId = item && item.id ? String(item.id) : null;
  if (title) title.textContent = _memEditingId ? '编辑记忆' : '添加记忆';
  if (hint) hint.textContent = _memEditingId
    ? '修改后保存会覆盖原记忆内容；分类标签仍由 [用户] / [实验] / [材料] / [结论] 前缀决定'
    : '建议加类别标签，如 [用户] / [实验] / [材料] / [结论]';
  if (save) save.textContent = _memEditingId ? '保存修改' : '保存';
  area.value = _memEditingId ? (item.memory || '') : '';
  modal.classList.add('show');
  setTimeout(() => area.focus(), 50);
}

function closeMemModal() {
  const modal = document.getElementById('mem-modal');
  if (modal) modal.classList.remove('show');
  _memEditingId = null;
}

export function bindMemoryUI() {
  const search = document.getElementById('mem-search');
  if (search) {
    let t;
    search.oninput = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        _memQuery = search.value.trim();
        _memSelected = null;
        _memView = 'all';
        loadMemories();
      }, 400);
    };
  }
  const addBtn = document.getElementById('btn-add-mem');
  if (addBtn) addBtn.onclick = () => openMemModal(null);
  const cancelBtn = document.getElementById('btn-mem-cancel');
  if (cancelBtn) cancelBtn.onclick = () => closeMemModal();
  const saveBtn = document.getElementById('btn-mem-save');
  if (saveBtn) saveBtn.onclick = async () => {
    const area = document.getElementById('mem-new-text');
    const text = area ? area.value.trim() : '';
    if (!text) return;
    const editingId = _memEditingId;
    saveBtn.disabled = true;
    try {
      const res = editingId
        ? await fetch('/api/memory/' + encodeURIComponent(editingId), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
          })
        : await fetch('/api/memory', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: text, source_type: 'user' }),
          });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      if (area) area.value = '';
      closeMemModal();
      loadMemories();
    } catch (e) {
      alert((editingId ? '保存修改失败：' : '添加失败：') + e.message);
    } finally {
      saveBtn.disabled = false;
    }
  };
  const refreshBtn = document.getElementById('btn-refresh-mem');
  if (refreshBtn) refreshBtn.onclick = () => reloadMemories();
  const modal = document.getElementById('mem-modal');
  if (modal) modal.onclick = (e) => { if (e.target === modal) closeMemModal(); };
  bindMemTabs();
}

/** 记忆列表 / 实体图谱两个视图切换（图谱按需懒加载）。 */
function bindMemTabs() {
  const tabs = document.querySelectorAll('.mem-tab[data-memview]');
  if (!tabs.length) return;
  tabs.forEach(tab => {
    tab.onclick = () => {
      const view = tab.dataset.memview;
      tabs.forEach(t => t.classList.toggle('active', t === tab));
      const listPane = document.getElementById('mem-pane-list');
      const graphPane = document.getElementById('mem-pane-graph');
      if (listPane) listPane.style.display = view === 'list' ? 'flex' : 'none';
      if (graphPane) graphPane.style.display = view === 'graph' ? 'flex' : 'none';
      if (view === 'graph') {
        // 容器刚变可见，尺寸为 0 时 vis-network 画不出来，等一帧再加载
        setTimeout(() => {
          Promise.resolve(loadGraph()).catch(() => {});
        }, 60);
      } else if (view === 'list' && !_memAll.length && !_memHits.length) {
        loadMemories();
      }
    };
  });
}
