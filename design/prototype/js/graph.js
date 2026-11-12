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

let _rawGraph = null;       // 最近一次 /api/graph 响应
let _graphFetchAt = 0;      // 上次拉取时刻（8 秒内复用，避免启动和切视图各拉一次）
let _g3 = null;             // 3D 渲染器状态（懒初始化）

/* ── 知识图谱：3D 脑区神经图（零依赖，纯 canvas 2D 透视投影） ──
 *
 * 为什么不再用 vis-network：旧实现从 unpkg CDN 拉脚本，网络不通就退化成
 * 文字列表；而"3D"在这里只需要把几十个点放到球面上转起来——自己算一遍
 * 透视投影的成本，远低于引一个三维引擎进来。86 实体 / 99 关系这个量级，
 * canvas 2D 每帧三百来次绘制绰绰有余，还能把节点画成神经元、按脑区分色，
 * 这些在通用引擎里反而不好做。
 */

// 分类 → 脑区。区中心用斐波那契球面算，布局是决定论的（刷新不变）。
const BRAIN_REGIONS = [
  { key: '用户', name: '前额叶 · 身份', color: '#38bdf8' },
  { key: '方法', name: '顶叶 · 方法', color: '#34d399' },
  { key: '材料', name: '颞叶 · 实体', color: '#818cf8' },
  { key: '性质', name: '枕叶 · 属性', color: '#fbbf24' },
  { key: '结论', name: '额叶回 · 判断', color: '#f472b6' },
  { key: '参数', name: '顶叶沟 · 数值', color: '#22d3ee' },
  { key: '其他', name: '联合皮层 · 待归类', color: '#94a3b8' },
];

/** 斐波那契球面：n 个近似均匀分布的单位向量。 */
function _fibSphere(n) {
  const ga = Math.PI * (3 - Math.sqrt(5));
  const out = [];
  for (let i = 0; i < n; i++) {
    const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const t = ga * i;
    out.push([Math.cos(t) * r, y, Math.sin(t) * r]);
  }
  return out;
}

/** 以单位向量 n 为轴的一组正交基，用来在球冠里采样。 */
function _basis(n) {
  const ax = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
  let tx = n[1] * ax[2] - n[2] * ax[1];
  let ty = n[2] * ax[0] - n[0] * ax[2];
  let tz = n[0] * ax[1] - n[1] * ax[0];
  const tl = Math.hypot(tx, ty, tz) || 1;
  tx /= tl; ty /= tl; tz /= tl;
  return [
    [tx, ty, tz],
    [n[1] * tz - n[2] * ty, n[2] * tx - n[0] * tz, n[0] * ty - n[1] * tx],
  ];
}

/** 字符串 → 0..1 的稳定散列（让"皮层厚度"抖动可重复，不是每次刷新乱跳）。 */
function _hash01(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = (h * 16777619) >>> 0;
  }
  return (h % 100000) / 100000;
}

/** 把节点铺到各个脑区的球冠里，同时建邻接关系。 */
function _layoutBrain(nodes, edges) {
  const centers = _fibSphere(BRAIN_REGIONS.length);
  const byKey = {};
  BRAIN_REGIONS.forEach(r => { byKey[r.key] = []; });
  nodes.forEach(n => {
    const k = String(n.category || '其他');
    (byKey[k] || byKey['其他']).push(n);
  });

  const out = [];
  BRAIN_REGIONS.forEach((region, ri) => {
    const list = byKey[region.key] || [];
    if (!list.length) return;
    const c = centers[ri];
    const [t, b] = _basis(c);
    // 区内点少就收得更紧，点多用更大球冠——既好看又不会跨区粘连
    const spread = Math.min(0.52, 0.20 + 0.30 * Math.sqrt(list.length / 30));
    list.forEach((n, i) => {
      const frac = list.length === 1 ? 0 : i / (list.length - 1);
      const cone = Math.sqrt(frac) * spread;
      const ang = i * 2.39996;                      // 黄金角螺旋，避免扎堆
      const sp = Math.sin(cone), cp = Math.cos(cone);
      const lx = sp * Math.cos(ang), ly = sp * Math.sin(ang);
      const ux = cp * c[0] + lx * t[0] + ly * b[0];
      const uy = cp * c[1] + lx * t[1] + ly * b[1];
      const uz = cp * c[2] + lx * t[2] + ly * b[2];
      const rad = 0.90 + 0.13 * _hash01(String(n.id)); // 皮层厚度
      out.push({
        id: String(n.id),
        label: String(n.label || n.id),
        cat: region.key,
        color: n.color || region.color,
        x: ux * rad, y: uy * rad, z: uz * rad,
        deg: 0,
        sx: 0, sy: 0, sr: 0, sz: 0,   // 每帧投影结果
      });
    });
  });

  const idx = new Map(out.map((n, i) => [n.id, i]));
  const es = [];
  (edges || []).forEach(e => {
    const a = idx.get(String(e.source));
    const b = idx.get(String(e.target));
    if (a === undefined || b === undefined || a === b) return;
    es.push({ a, b, label: String(e.label || ''), bridge: String(e.kind || '') === 'cooc',
              sx0: 0, sy0: 0, sx1: 0, sy1: 0, cxp: 0, cyp: 0, z: 0, sr: 0 });
    out[a].deg++;
    out[b].deg++;
  });
  return { nodes: out, edges: es };
}

/**
 * 文本共现：不看抽取出的关系，只看"哪些实体同时出现在同一条记忆里"。
 *
 * 为什么需要第二个视角：抽取出的关系目前高度集中在用户节点上（31 条边 / 99），
 * 图看起来像星形。共现完全由原文决定，能回答一个不同的问题——材料之间到底是
 * 被一起讨论过，还是仅仅都被写到过。
 *
 * 长 label 先匹配并占位，避免「固态电解质」这段文字又被更短的 label 重复命中。
 */
function _buildCooccurrence(memList, layoutNodes) {
  const cand = layoutNodes
    .filter(n => String(n.label || '').length >= 2)
    .map(n => ({ id: n.id, label: String(n.label) }))
    .sort((a, b) => b.label.length - a.label.length);
  const idx = new Map(layoutNodes.map((n, i) => [n.id, i]));
  const pairs = new Map();
  let usedMem = 0;

  (memList || []).forEach(m => {
    const text = String(m.memory || m.content || m.text || '');
    if (!text) return;
    let rest = text;
    const hits = [];
    cand.forEach(c => {
      if (rest.indexOf(c.label) >= 0) {
        hits.push(c.id);
        rest = rest.split(c.label).join('\u0001'); // 占位，防止同一段被短 label 再吃一遍
      }
    });
    if (hits.length < 2) return;
    usedMem++;
    for (let i = 0; i < hits.length; i++) {
      for (let j = i + 1; j < hits.length; j++) {
        const a = idx.get(hits[i]), b = idx.get(hits[j]);
        if (a === undefined || b === undefined || a === b) continue;
        const key = a < b ? a + '|' + b : b + '|' + a;
        pairs.set(key, (pairs.get(key) || 0) + 1);
      }
    }
  });

  const out = [];
  pairs.forEach((w, key) => {
    const [a, b] = key.split('|').map(Number);
    out.push({ a, b, w, label: '', cooc: true,
               sx0: 0, sy0: 0, sx1: 0, sy1: 0, cxp: 0, cyp: 0, z: 0, sr: 0 });
  });
  out.sort((x, y) => y.w - x.w);
  // 只留共现 ≥2 次的：偶发一次大多是句子碰巧同框，全画上会变成一团毛球
  return { edges: out.filter(e => e.w >= 2).slice(0, 260), usedMem, total: out.length };
}

/** 换边集：重算每个节点的度数和邻接表，路径高亮一并清掉。 */
function _applyEdges(st, mode) {
  st.mode = mode;
  if (mode === 'cooc') _ensureCooc(st);
  const src = mode === 'cooc' ? ((st.cooc && st.cooc.edges) || []) : st.relEdges;
  st.edges = src;
  st.nodes.forEach(n => { n.deg = 0; });
  st.nbr.clear();
  st.nodes.forEach(n => st.nbr.set(n.id, new Set()));
  src.forEach(e => {
    const A = st.nodes[e.a], B = st.nodes[e.b];
    if (!A || !B) return;
    A.deg++; B.deg++;
    st.nbr.get(A.id).add(B.id);
    st.nbr.get(B.id).add(A.id);
  });
  st.pathFrom = null; st.pathTo = null;
  st.pathNodes = null; st.pathEdges = null; st.pathLen = -1; st.pathLabels = null;
}

/** 共现边按记忆条数惰性重算：记忆是增量长出来的，条数变了就得重算一次。 */
function _ensureCooc(st) {
  const key = (_memAll || []).length;
  if (st.cooc && st.coocKey === key) return st.cooc;
  st.coocKey = key;
  st.cooc = _buildCooccurrence(_memAll, st.nodes);
  return st.cooc;
}

/** 无向图上的最短路径（BFS）。两点不连通时返回 null，而不是硬连一条假路径。 */
function _bfsPath(st, from, to) {
  if (!from || !to) return null;
  const prev = new Map([[from, null]]);
  const q = [from];
  while (q.length) {
    const cur = q.shift();
    if (cur === to) break;
    const ns = st.nbr.get(cur) || new Set();
    for (const nb of ns) {
      if (!prev.has(nb)) { prev.set(nb, cur); q.push(nb); }
    }
  }
  if (!prev.has(to)) return null;
  const path = [];
  let cur = to;
  while (cur) { path.unshift(cur); cur = prev.get(cur); }
  return path;
}

/** 把 id 序列变成画线时要查的边 key（index 有序拼接，双向都能命中）。 */
function _pathEdgeKeys(st, path) {
  if (!path || path.length < 2) return null;
  const at = new Map(st.nodes.map((n, i) => [n.id, i]));
  const s = new Set();
  for (let i = 0; i + 1 < path.length; i++) {
    const a = at.get(path[i]), b = at.get(path[i + 1]);
    if (a === undefined || b === undefined) continue;
    s.add(Math.min(a, b) + '|' + Math.max(a, b));
  }
  return s;
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
  const aliases = Array.isArray(node.aliases) ? node.aliases : [];
  const aliasHtml = aliases.length
    ? '<div style="font-size:11.5px;color:var(--ml-text-dim);line-height:1.7;margin-bottom:6px">' +
      '同一实体的其他写法已并入此节点：' + aliases.map(a => esc(a)).join('、') + '</div>' +
      (node.merged_why
        ? '<div style="font-size:11px;color:var(--ml-text-faint);line-height:1.6;margin-bottom:6px">合并依据：' +
          esc(node.merged_why) + '</div>'
        : '')
    : '';
  // 可能同物异名：只给证据，点「合并到此」才真正合并（写进本机配置，可撤销）
  const cands = ((_rawGraph && _rawGraph.merge_candidates) || []).filter(
    c => String(c.a) === String(nodeId) || String(c.b) === String(nodeId));
  const candHtml = cands.length
    ? '<div style="margin:10px 0 8px;padding-top:9px;border-top:1px dashed var(--ml-border)">' +
      '<div style="font-size:11.5px;color:#cbd5e1;margin-bottom:5px">可能指同一个实体</div>' +
      cands.map(c => {
        const other = String(c.a) === String(nodeId) ? c.b_label : c.a_label;
        return '<div style="display:flex;align-items:center;gap:7px;padding:3px 0">' +
          '<span style="flex:1;min-width:0;font-size:11.5px;color:var(--ml-text-dim);' +
          'overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(other) +
          ' <span style="color:var(--ml-text-faint)">· ' + esc(c.reason || '') + '</span></span>' +
          '<button data-g3-merge="' + esc(other) + '" style="flex:none;padding:3px 7px;' +
          'border-radius:6px;border:1px solid rgba(56,189,248,0.45);background:rgba(56,189,248,0.12);' +
          'color:#7dd3fc;font-size:11px;cursor:pointer;font-family:inherit">合并到此</button></div>';
      }).join('') +
      '<div style="font-size:10.5px;color:var(--ml-text-faint);line-height:1.6;margin-top:3px">' +
      '合并会写进本机配置，删掉对应条目就能撤销。</div></div>'
    : '';

  panel.innerHTML =
    '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">' +
    '<button data-g3-back style="background:none;border:0;color:#7dd3fc;font-size:11.5px;cursor:pointer;padding:0">← 全部脑区</button>' +
    '</div>' +
    '<div style="font-weight:700;margin-bottom:4px;font-size:14px">' + esc(node.label || node.id) + '</div>' +
    '<div style="font-size:11px;color:var(--ml-text-faint);margin-bottom:10px">' + esc(cat) + ' · ' + rel.length + ' 条关联</div>' +
    aliasHtml +
    candHtml +
    '<div style="font-size:12px;color:var(--ml-text-dim);line-height:1.7;margin-bottom:8px">' +
    '该实体由 DeepSeek 从对话记忆中抽取，来源为本项目积累的材料科研对话。</div>' +
    (relHtml || '<div style="font-size:12px;color:var(--ml-text-faint)">暂无关联关系</div>');
  panel.querySelectorAll('[data-g3-merge]').forEach(btn => {
    btn.onclick = () => {
      const other = btn.getAttribute('data-g3-merge');
      if (!other) return;
      btn.disabled = true;
      btn.textContent = '合并中…';
      fetch('/api/graph/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ a: node.label, b: other, keep: 'a' }),
      })
        .then(r => r.json().then(body => ({ ok: r.ok, body })))
        .then(({ ok, body }) => {
          if (!ok || !body.ok) throw new Error(body.detail || '合并失败');
          if (_g3) { _g3.sel = null; _g3.hover = null; _g3.focus = null; }
          _graphFetchAt = 0;
          return loadGraph(true);
        })
        .catch(err => {
          btn.disabled = false;
          btn.textContent = '合并到此';
          console.warn('merge-entity failed:', err);
        });
    };
  });

  const back = panel.querySelector('[data-g3-back]');
  if (back) {
    back.onclick = () => {
      if (_g3) { _g3.sel = null; _g3.hover = null; _g3.focus = null; }
      if (_rawGraph) _renderLegend(panel, _rawGraph);
    };
  }
}

/* ── 3D 脑区图：渲染器 ───────────────────────────────── */

/** hex → rgba 字符串（sprite 与描边都要带透明度）。 */
function _rgba(hex, a) {
  const h = String(hex || '#94a3b8').replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return 'rgba(' + ((n >> 16) & 255) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + a + ')';
}

/** 预烘一张神经元光点，渲染时只做 drawImage——比每帧建渐变便宜一个量级。 */
function _makeNeuronSprite(color) {
  const S = 96;
  const c = document.createElement('canvas');
  c.width = S; c.height = S;
  const g = c.getContext('2d');
  const rg = g.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
  rg.addColorStop(0, 'rgba(255,255,255,0.98)');
  rg.addColorStop(0.14, _rgba(color, 0.98));
  rg.addColorStop(0.36, _rgba(color, 0.42));
  rg.addColorStop(0.62, _rgba(color, 0.12));
  rg.addColorStop(1, _rgba(color, 0));
  g.fillStyle = rg;
  g.fillRect(0, 0, S, S);
  return c;
}

function _renderLegend(panel, d) {
  if (!panel) return;
  const counts = {};
  (d.nodes || []).forEach(n => {
    const k = String(n.category || '其他');
    counts[k] = (counts[k] || 0) + 1;
  });
  const rows = BRAIN_REGIONS.filter(r => counts[r.key]).map(r =>
    '<div style="display:flex;align-items:center;gap:9px;padding:5px 0;font-size:12px">' +
    '<span style="width:8px;height:8px;border-radius:50%;flex:none;background:' + r.color +
    ';box-shadow:0 0 9px ' + r.color + '99"></span>' +
    '<span style="flex:1;color:#cbd5e1">' + esc(r.name) + '</span>' +
    '<span style="color:#94a3b8;font-variant-numeric:tabular-nums">' + counts[r.key] + '</span></div>'
  ).join('');

  // 结构诊断：度数分布是判断这份记忆结构健不健康最便宜的指标。
  // 孤立实体说明抽出来没连上（噪音，或抽取漏了关系）；单点支配的枢纽会把
  // 整张图压成星形，让人误以为"所有知识都以用户为中心"。
  // 两种视图度数含义不同，一律按"当前这套边"算，不混用。
  const mode = (_g3 && _g3.mode) || 'rel';
  const cooc = (_g3 && _g3.cooc) || null;
  const edgeCount = mode === 'cooc'
    ? ((_g3 && _g3.edges) ? _g3.edges.length : 0)
    : ((d.edges || []).length);

  const deg = new Map();
  if (mode === 'cooc' && _g3 && _g3.nodes) {
    _g3.nodes.forEach(n => deg.set(n.id, n.deg || 0));
  } else {
    (d.edges || []).forEach(e => {
      const a = String(e.source), b = String(e.target);
      deg.set(a, (deg.get(a) || 0) + 1);
      deg.set(b, (deg.get(b) || 0) + 1);
    });
  }
  const nodes = d.nodes || [];
  const degOf = n => deg.get(String(n.id)) || 0;
  const isolated = nodes.filter(n => degOf(n) === 0);
  const leaf = nodes.filter(n => degOf(n) === 1);
  let hub = null;
  nodes.forEach(n => { if (!hub || degOf(n) > degOf(hub)) hub = n; });
  const hubDeg = hub ? degOf(hub) : 0;
  const total = nodes.length || 1;
  // 归并过的节点：同一实体的不同写法已经收成一个，这里把结果摆出来让人能核对
  const mergedNodes = nodes.filter(n => Array.isArray(n.aliases) && n.aliases.length);
  const mergedTotal = mergedNodes.reduce((s, n) => s + n.aliases.length, 0);
  const candidates = Array.isArray(d.merge_candidates) ? d.merge_candidates : [];
  const diagRow = (k, v, hint) =>
    '<div style="padding:6px 0;font-size:12px">' +
    '<div style="display:flex;gap:8px;align-items:baseline">' +
    '<span style="color:#cbd5e1">' + k + '</span>' +
    '<span style="margin-left:auto;color:#e2e8f0;font-variant-numeric:tabular-nums">' + v + '</span></div>' +
    (hint ? '<div style="font-size:10.5px;color:var(--ml-text-faint);line-height:1.5;margin-top:2px">' + hint + '</div>' : '') +
    '</div>';

  const modeBar =
    '<div style="display:flex;gap:6px;margin-bottom:10px">' +
    [['rel', '语义关系'], ['cooc', '文本共现']].map(pair => {
      const k = pair[0], name = pair[1], on = mode === k;
      return '<button data-g3mode="' + k + '" style="flex:1;padding:5px 0;font-size:11.5px;' +
        'cursor:pointer;border-radius:7px;font-family:inherit;' +
        'border:1px solid ' + (on ? 'rgba(56,189,248,0.6)' : 'var(--ml-border)') + ';' +
        'background:' + (on ? 'rgba(56,189,248,0.14)' : 'transparent') + ';' +
        'color:' + (on ? '#7dd3fc' : 'var(--ml-text-dim)') + '">' + name + '</button>';
    }).join('') + '</div>';

  panel.innerHTML =
    '<div style="font-weight:700;margin-bottom:10px;font-size:13px">实体图谱 · 3D 脑区</div>' +
    modeBar +
    '<div style="font-size:11.5px;color:var(--ml-text-faint);line-height:1.75;margin-bottom:12px">' +
    (d.fallback ? '示例图谱 · ' : '') + (d.nodes || []).length + ' 实体 · ' +
    edgeCount + (mode === 'cooc' ? ' 共现' : ' 关系') + '<br>' +
    (mode === 'cooc'
      ? '同一条记忆里被一起提到的实体相连，线越实同框次数越多'
      : '拖拽旋转 · 滚轮缩放 · 单击看关联 · 双击聚焦') + '</div>' +
    rows +
    '<div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--ml-border)">' +
    '<div style="font-size:12px;font-weight:600;margin-bottom:4px">结构诊断</div>' +
    diagRow('孤立实体', isolated.length + ' 个',
      isolated.length
        ? (mode === 'cooc'
            ? '没有任何一条记忆把它们和别的实体写在一起：'
            : '没有任何关系，球面上用虚线小圈标出：') +
          isolated.slice(0, 3).map(n => esc(n.label)).join('、') +
          (isolated.length > 3 ? ' 等' : '')
        : (mode === 'cooc' ? '每个实体都至少和别的实体同框过' : '全部实体都连上了关系')) +
    diagRow('最大枢纽', hub ? degOf(hub) + ' 条 · ' + esc(hub.label) : '—',
      hubDeg > 12 ? '连线高度集中，这张图会看起来像星形而不是网络' : '枢纽与其余实体差距不大') +
    diagRow('只连一条', leaf.length + ' / ' + nodes.length,
      '叶子节点占 ' + Math.round(leaf.length / total * 100) + '%，关系网还很浅') +
    (mergedTotal
      ? diagRow('已归并', mergedTotal + ' 个写法',
          mergedNodes.slice(0, 2).map(n => esc(n.aliases[0]) + ' → ' + esc(n.label)).join('，') +
          (mergedNodes.length > 2 ? ' 等' : ''))
      : '') +
    '</div>' +
    (candidates.length
      ? '<div style="margin-top:10px;font-size:10.5px;color:var(--ml-text-faint);line-height:1.6">' +
        '另有 ' + candidates.length + ' 对名字可能指同一实体（' +
        candidates.slice(0, 3).map(c => esc(c.a_label) + ' / ' + esc(c.b_label)).join('、') +
        '），没有自动合并——上下位、不同牌号、不同掺杂量在字面上也可能很像。</div>'
      : '') +
    (mode === 'cooc' && cooc
      ? '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--ml-border);' +
        'font-size:10.5px;color:var(--ml-text-faint);line-height:1.6">' +
        '口径：' + cooc.usedMem + ' 条记忆里至少提到 2 个实体，共 ' + cooc.total + ' 对同框，' +
        '这里只画出现 ≥2 次的 ' + ((cooc.edges || []).length) + ' 对。</div>'
      : '') +
    '<div style="margin-top:12px;font-size:11px;color:var(--ml-text-faint);line-height:1.7">' +
    'Shift 点击两个实体可以量出它们在这张图里的最短路径。</div>';

  panel.querySelectorAll('[data-g3mode]').forEach(btn => {
    btn.onclick = () => {
      const m = btn.dataset.g3mode;
      if (!_g3 || _g3.mode === m) return;
      _applyEdges(_g3, m);
      _g3.sel = null; _g3.focus = null; _g3.hover = null;
      _g3.paint();
      _renderLegend(panel, d);
    };
  });
}

function _mountBrain(box, d, sig, prev) {
  // 重建时（记忆新增触发自动刷新）沿用上一个渲染器的视角和选中态，
  // 否则用户刚转到的角度会被悄悄甩回默认位置。
  const old = prev || _g3;
  const prevIds = (old && old.nodes) ? new Set(old.nodes.map(n => n.id)) : null;
  if (_g3) {
    _g3.running = false;
    if (_g3.raf) cancelAnimationFrame(_g3.raf);
    if (_g3._onResize) window.removeEventListener('resize', _g3._onResize);
  }
  if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
  box.innerHTML = '';

  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;touch-action:none';
  box.appendChild(canvas);

  const layout = _layoutBrain(d.nodes || [], d.edges || []);

  // 这一版新出现的实体：绘制时给它们几秒钟的扩散环，像神经元刚长出来
  const fresh = prevIds
    ? new Set(layout.nodes.filter(n => !prevIds.has(n.id)).map(n => n.id))
    : new Set();

  const st = {
    sig, canvas, box, ctx: canvas.getContext('2d'),
    nodes: layout.nodes, edges: layout.edges, nbr: new Map(),
    relEdges: layout.edges,
    // 视图沿用上一版：自动刷新重建时不该把用户切过去的共现视图甩回关系视图
    mode: (old && old.mode === 'cooc') ? 'cooc' : 'rel',
    cooc: (old && old.cooc) || null,
    coocKey: (old && old.coocKey) || -1,
    pathFrom: null, pathTo: null, pathNodes: null, pathEdges: null,
    pathLen: -1, pathLabels: null,
    W: 0, H: 0, dpr: 1,
    yaw: old ? old.yaw : 0.45,
    pitch: old ? old.pitch : -0.18,
    dist: old ? old.dist : 2.5,
    vyaw: 0, vpitch: 0,
    auto: old ? old.auto : true,
    dragging: false, moved: 0,
    sel: (old && old.sel && layout.nodes.some(n => n.id === old.sel)) ? old.sel : null,
    hover: null, focus: null,
    lastX: 0, lastY: 0, t: 0, raf: 0, running: false,
    sprites: {},
    fresh, freshUntil: performance.now() + 7000,
  };
  _g3 = st;
  BRAIN_REGIONS.forEach(r => { st.sprites[r.key] = _makeNeuronSprite(r.color); });
  st.sprites._ = _makeNeuronSprite('#94a3b8');
  // 度数、邻接表都从"当前这套边"推出来：换视图就是换一套边，这些必须跟着重算
  _applyEdges(st, st.mode);

  st.resize = function () {
    const rect = box.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    st.dpr = dpr;
    st.W = Math.max(300, Math.floor(rect.width || box.clientWidth || 320));
    st.H = Math.max(240, Math.floor(rect.height || box.clientHeight || 280));
    canvas.width = Math.floor(st.W * dpr);
    canvas.height = Math.floor(st.H * dpr);
    st.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };

  st.frame = function (now) {
    const dt = Math.min(48, now - (st.t || now));
    st.t = now;
    if (st.auto && !st.dragging) st.yaw += dt * 0.00030;
    if (!st.dragging) {
      if (Math.abs(st.vyaw) > 1e-5) { st.yaw += st.vyaw; st.vyaw *= 0.93; }
      if (Math.abs(st.vpitch) > 1e-5) {
        st.pitch = Math.max(-1.25, Math.min(1.25, st.pitch + st.vpitch));
        st.vpitch *= 0.93;
      }
    }
    _drawBrain(st, now);
  };

  // 交互时立刻补一帧：标签页不可见时 rAF 会被浏览器停掉，
  // 只等下一帧的话拖拽是"看不见反应"的。
  st.paint = function () {
    try { _drawBrain(st, performance.now()); } catch (_) {}
  };

  st.start = function () {
    if (st.running) return;
    st.running = true;
    st.t = 0;
    // 先同步画一帧：标签页在后台时 rAF 会被节流甚至完全停摆，
    // 只靠 rAF 的话第一次切回来会看到一帧空白。
    try { _drawBrain(st, performance.now()); } catch (_) {}
    const loop = now => {
      if (!st.running) return;
      st.frame(now);
      st.raf = requestAnimationFrame(loop);
    };
    st.raf = requestAnimationFrame(loop);
  };
  st.stop = function () {
    st.running = false;
    if (st.raf) cancelAnimationFrame(st.raf);
    st.raf = 0;
  };

  const hitTest = (mx, my) => {
    let best = null, bestD = Infinity;
    st.nodes.forEach(n => {
      const dx = mx - n.sx, dy = my - n.sy;
      const d = dx * dx + dy * dy;
      const lim = Math.max(11, n.sr * 2.4);
      if (d < lim * lim && d < bestD) { bestD = d; best = n; }
    });
    return best;
  };
  st.hitTest = hitTest;

  canvas.addEventListener('pointerdown', e => {
    st.dragging = true; st.moved = 0;
    st.lastX = e.clientX; st.lastY = e.clientY;
    canvas.style.cursor = 'grabbing';
    if (canvas.setPointerCapture) { try { canvas.setPointerCapture(e.pointerId); } catch (_) {} }
  });
  canvas.addEventListener('pointermove', e => {
    const rect = canvas.getBoundingClientRect();
    if (st.dragging) {
      const dx = e.clientX - st.lastX, dy = e.clientY - st.lastY;
      st.lastX = e.clientX; st.lastY = e.clientY;
      st.moved += Math.abs(dx) + Math.abs(dy);
      st.yaw += dx * 0.0056;
      st.pitch = Math.max(-1.25, Math.min(1.25, st.pitch + dy * 0.0056));
      st.vyaw = dx * 0.0056;
      st.vpitch = dy * 0.0056;
      st.paint();
    } else {
      const n = hitTest(e.clientX - rect.left, e.clientY - rect.top);
      st.hover = n ? n.id : null;
      canvas.style.cursor = n ? 'pointer' : 'grab';
    }
  });
  canvas.addEventListener('pointerup', e => {
    const wasDrag = st.moved >= 5;
    st.dragging = false;
    canvas.style.cursor = 'grab';
    if (wasDrag) return;
    const rect = canvas.getBoundingClientRect();
    const n = hitTest(e.clientX - rect.left, e.clientY - rect.top);

    // Shift 点击 = 量两点之间的距离：第一次定起点，第二次定终点并求出最短路径。
    // 用"实际连过的边"来算，所以它回答的是"这两个概念在这个图里是怎么一路连上的"，
    // 而不是靠语义相似度猜出来的关系。
    if (e.shiftKey && n) {
      if (!st.pathFrom || st.pathFrom === n.id) {
        st.pathFrom = n.id; st.pathTo = null;
        st.pathNodes = null; st.pathEdges = null; st.pathLen = -1; st.pathLabels = null;
      } else {
        const path = _bfsPath(st, st.pathFrom, n.id);
        st.pathTo = n.id;
        st.pathNodes = path ? new Set(path) : null;
        st.pathEdges = path ? _pathEdgeKeys(st, path) : null;
        st.pathLen = path ? path.length - 1 : -1;
        st.pathLabels = path
          ? path.map(id => { const x = st.nodes.find(q => q.id === id); return x ? x.label : id; })
          : null;
      }
      st.sel = n.id; st.focus = null; st.hover = n.id;
      st.paint();
      _renderDetailPanel(n.id);
      return;
    }

    // 普通点击：清掉上一次的路径高亮，回到"看邻居"的状态
    st.pathFrom = null; st.pathTo = null;
    st.pathNodes = null; st.pathEdges = null; st.pathLen = -1; st.pathLabels = null;
    st.focus = null;
    st.sel = n ? n.id : null;
    st.hover = n ? n.id : null;
    st.paint();
    if (n) _renderDetailPanel(n.id);
    else if (_rawGraph) _renderLegend(document.getElementById('mem-graph-detail'), _rawGraph);
  });
  canvas.addEventListener('dblclick', e => {
    const rect = canvas.getBoundingClientRect();
    const n = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    st.pathFrom = null; st.pathTo = null;
    st.pathNodes = null; st.pathEdges = null; st.pathLen = -1; st.pathLabels = null;
    if (!n) { st.focus = null; return; }
    st.sel = n.id;
    st.focus = st.focus === n.id ? null : n.id;
    st.paint();
    _renderDetailPanel(n.id);
  });
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    st.dist = Math.max(1.15, Math.min(4.8, st.dist + (e.deltaY > 0 ? 0.14 : -0.14)));
    st.paint();
  }, { passive: false });

  // 悬浮操作条
  const statusEl = document.createElement('div');
  statusEl.style.cssText = 'position:absolute;left:12px;bottom:44px;z-index:3;font-size:11px;' +
    'color:rgba(226,232,240,0.75);pointer-events:none;text-shadow:0 1px 4px rgba(0,0,0,0.85);' +
    'max-width:calc(100% - 24px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
  box.appendChild(statusEl);
  st.statusEl = statusEl;

  const hud = document.createElement('div');
  hud.style.cssText = 'position:absolute;left:12px;bottom:10px;display:flex;gap:7px;z-index:3';
  hud.innerHTML =
    '<button class="btn btn-ghost btn-sm" data-g3="spin">⏸ 自转</button>' +
    '<button class="btn btn-ghost btn-sm" data-g3="reset">重置视角</button>';
  box.appendChild(hud);
  hud.addEventListener('click', ev => {
    const t = ev.target.closest ? ev.target.closest('[data-g3]') : null;
    if (!t) return;
    if (t.dataset.g3 === 'spin') {
      st.auto = !st.auto;
      t.textContent = st.auto ? '⏸ 自转' : '▶ 自转';
    } else {
      st.yaw = 0.45; st.pitch = -0.18; st.dist = 2.5;
      st.vyaw = 0; st.vpitch = 0; st.sel = null; st.hover = null; st.focus = null;
      st.paint();
      if (_rawGraph) _renderLegend(document.getElementById('mem-graph-detail'), _rawGraph);
    }
  });

  st._onResize = () => st.resize();
  window.addEventListener('resize', st._onResize);
  st.resize();
  // 只读调试句柄：排查渲染/交互问题时能在控制台直接看坐标、命中、选区
  window.__mlGraph3 = st;
}

function _drawBrain(st, now) {
  const ctx = st.ctx, W = st.W, H = st.H;
  const cx = W / 2, cyc = H / 2;
  const scale = Math.min(W, H) * 0.44;
  const FOCAL = 4.0, DIST = st.dist;
  // 透视只负责"近大远小"的体积感；真正的缩放交给 dist（boost），
  // 否则 dist 一大，节点会被压成 2 像素一个点。
  const boost = 2.5 / DIST;
  const cyw = Math.cos(st.yaw), syw = Math.sin(st.yaw);
  const cpi = Math.cos(st.pitch), spi = Math.sin(st.pitch);
  const tmp = { sx: 0, sy: 0, sz: 0, per: 0 };

  const proj = (x, y, z) => {
    const x1 = x * cyw - z * syw;
    const z1 = x * syw + z * cyw;
    const y2 = y * cpi - z1 * spi;
    const z2 = y * spi + z1 * cpi;
    const per = (FOCAL / (FOCAL + z2)) * boost;
    tmp.sx = cx + x1 * scale * per;
    tmp.sy = cyc - y2 * scale * per;
    tmp.sz = z2;
    tmp.per = per;
    return tmp;
  };

  // 背景
  const bg = ctx.createRadialGradient(cx, cyc * 0.95, 0, cx, cyc, Math.max(W, H) * 0.65);
  bg.addColorStop(0, 'rgba(24,36,60,0.96)');
  bg.addColorStop(0.55, 'rgba(11,17,30,0.94)');
  bg.addColorStop(1, 'rgba(5,8,15,0.97)');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // 脑壳经纬（给体积感，收敛格数以控成本）
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(120,160,220,0.09)';
  for (let i = 0; i < 8; i++) {
    const lon = (i / 8) * Math.PI * 2;
    ctx.beginPath();
    for (let j = 0; j <= 16; j++) {
      const lat = -1.5708 + (j / 16) * Math.PI;
      const r = Math.cos(lat);
      proj(r * Math.cos(lon), Math.sin(lat), r * Math.sin(lon));
      if (j) ctx.lineTo(tmp.sx, tmp.sy); else ctx.moveTo(tmp.sx, tmp.sy);
    }
    ctx.stroke();
  }
  for (let k = 1; k < 6; k++) {
    const lat = -1.5708 + (k / 6) * Math.PI;
    const r = Math.cos(lat), y = Math.sin(lat);
    ctx.beginPath();
    for (let j = 0; j <= 24; j++) {
      const lon = (j / 24) * Math.PI * 2;
      proj(r * Math.cos(lon), y, r * Math.sin(lon));
      if (j) ctx.lineTo(tmp.sx, tmp.sy); else ctx.moveTo(tmp.sx, tmp.sy);
    }
    ctx.stroke();
  }

  // 节点投影
  const nodes = st.nodes;
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    proj(n.x, n.y, n.z);
    n.sx = tmp.sx; n.sy = tmp.sy; n.sz = tmp.sz; n.per = tmp.per;
    // 屏幕半径跟着球体尺度走：球越大，光点也略大，但别跟着线性放大
    n.sr = (3.2 + Math.min(5.0, n.deg * 0.7)) * tmp.per * (scale / 130);
  }

  // 边：控制点沿球面法线外推，投影后画二次贝塞尔
  const selId = st.sel;
  const focus = st.focus;
  const focusNbr = focus && st.nbr.get(focus) ? st.nbr.get(focus) : null;
  for (let i = 0; i < st.edges.length; i++) {
    const e = st.edges[i];
    const A = nodes[e.a], B = nodes[e.b];
    const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2, mz = (A.z + B.z) / 2;
    const ml = Math.hypot(mx, my, mz) || 1;
    const chord = Math.hypot(A.x - B.x, A.y - B.y, A.z - B.z);
    const rr = 1 + 0.30 * Math.min(1.5, chord);
    proj((mx / ml) * rr, (my / ml) * rr, (mz / ml) * rr);
    const cpx = tmp.sx, cpy = tmp.sy, cz = tmp.sz;

    const active = selId && (A.id === selId || B.id === selId);
    const dimmed = focus && !(A.id === focus || B.id === focus ||
                              (focusNbr && (focusNbr.has(A.id) || focusNbr.has(B.id))));
    const onPath = st.pathEdges && st.pathEdges.has(Math.min(e.a, e.b) + '|' + Math.max(e.a, e.b));
    let alpha, width, color, dashed = false;
    if (st.pathEdges) {
      // 有路径时其余边一律压到几乎看不见：这条链路本身才是要看的东西
      if (onPath) { alpha = 1; width = 2.6; color = 'rgba(56,189,248,0.95)'; }
      else { alpha = 0.045; width = 0.7; color = 'rgba(120,150,190,0.6)'; }
    } else if (e.cooc) {
      // 共现边按同框次数加权：被一起讨论得越多，线越实
      const wgt = Math.min(1, (e.w || 1) / 5);
      alpha = 0.16 + 0.55 * wgt;
      width = 0.9 + 1.8 * wgt;
      color = 'rgba(56,189,248,0.9)';
    } else if (e.bridge) {
      // 这条不是模型抽出来的关系，只是"两个实体在同一条记忆里出现过"。
      // 分批抽取把图切成了几块，靠它补桥；用虚线和琥珀色明示来源不同。
      dashed = true;
      if (dimmed) { alpha = 0.03; width = 0.7; color = 'rgba(120,150,190,0.5)'; }
      else if (active) { alpha = 0.75; width = 1.6; color = 'rgba(251,191,36,0.95)'; }
      else { alpha = 0.28; width = 1.0; color = 'rgba(251,191,36,0.8)'; }
    } else if (active) {
      alpha = 0.92; width = 1.9; color = _rgba(B.color || '#38bdf8', 0.9);
    } else if (dimmed) {
      alpha = 0.05; width = 0.8; color = 'rgba(120,150,190,0.5)';
    } else {
      const near = Math.max(0, Math.min(1, ((A.sz + cz) / 2 + 1) / 2));
      alpha = 0.10 + 0.20 * near; width = 0.8 + 0.7 * near;
      color = 'rgba(130,170,220,0.9)';
    }
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.lineWidth = width * (A.per + B.per) / 2 * 1.35;
    if (dashed) ctx.setLineDash([3, 3.4]);
    ctx.beginPath();
    ctx.moveTo(A.sx, A.sy);
    ctx.quadraticCurveTo(cpx, cpy, B.sx, B.sy);
    ctx.stroke();
    if (dashed) ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // 选中节点的关系上跑脉冲
    if (active) {
      const ph = ((now / 1100) + (i % 7) / 7) % 1;
      const t1 = ph, mt = 1 - t1;
      const px = mt * mt * A.sx + 2 * mt * t1 * cpx + t1 * t1 * B.sx;
      const py = mt * mt * A.sy + 2 * mt * t1 * cpy + t1 * t1 * B.sy;
      ctx.beginPath();
      ctx.arc(px, py, 2.2, 0, Math.PI * 2);
      ctx.fillStyle = _rgba(B.color || '#38bdf8', 0.85);
      ctx.fill();
    }
  }

  // 节点：远→近，近的盖远的
  const order = nodes.slice().sort((a, b) => a.sz - b.sz);
  for (let i = 0; i < order.length; i++) {
    const n = order[i];
    const sp = st.sprites[n.cat] || st.sprites._;
    const isSel = n.id === st.sel;
    const isHover = n.id === st.hover;
    const dimmed = focus && n.id !== focus &&
                   !(focusNbr && focusNbr.has(n.id));
    const onPath = st.pathNodes && st.pathNodes.has(n.id);
    const r = n.sr * (isSel ? 2.0 : (isHover ? 1.5 : 1.0));
    // 路径模式下不在链路里的实体压到 0.10，让那一条单独亮着
    ctx.globalAlpha = (st.pathNodes && !onPath) ? 0.10
      : (dimmed ? 0.16 : (0.5 + 0.5 * Math.min(1, n.per)));
    ctx.drawImage(sp, n.sx - r * 2.6, n.sy - r * 2.6, r * 5.2, r * 5.2);
    ctx.globalAlpha = 1;

    // 路径上的实体补一圈青边，隔着几个区也能一眼认出链路
    if (onPath && !isSel) {
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, n.sr * 1.6, 0, Math.PI * 2);
      ctx.strokeStyle = _rgba('#38bdf8', 0.8);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    if (isSel) {
      const ph = (now / 1500) % 1;
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, n.sr * (1.3 + ph * 2.6), 0, Math.PI * 2);
      ctx.strokeStyle = _rgba(n.color, 0.55 * (1 - ph));
      ctx.lineWidth = 1.6;
      ctx.stroke();
    }

    // 孤立实体：没有任何关系连出去，用一圈虚线标出来，否则它混在结构里看不出来
    if (n.deg === 0 && !dimmed) {
      ctx.globalAlpha = 0.6;
      ctx.beginPath();
      ctx.arc(n.sx, n.sy, n.sr * 1.2, 0, Math.PI * 2);
      ctx.setLineDash([2.5, 3.5]);
      ctx.strokeStyle = _rgba('#94a3b8', 0.85);
      ctx.lineWidth = 1.1;
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }

    // 刚被抽取出来的实体：几秒内连放三圈扩散环，让"记忆长出来了"可见
    if (st.fresh && st.fresh.has(n.id) && now < st.freshUntil) {
      const fade = 1 - (now - (st.freshUntil - 7000)) / 7000;
      for (let k = 0; k < 3; k++) {
        const ph = ((now / 1100) + k / 3) % 1;
        ctx.beginPath();
        ctx.arc(n.sx, n.sy, n.sr * (1.1 + ph * 3.4), 0, Math.PI * 2);
        ctx.strokeStyle = _rgba('#22d3ee', 0.72 * (1 - ph) * fade);
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }

  // 只给选中/悬停的节点画名字，86 个标签一起画会糊成一团也费性能。
  // 例外：刚长出来的实体在扩散环期间报一下名字，否则用户只看到一圈光不知道是什么。
  const ln = st.nodes.find(n => n.id === st.sel) ||
             st.nodes.find(n => n.id === st.hover) ||
             ((st.fresh && st.fresh.size && now < st.freshUntil)
               ? st.nodes.find(n => st.fresh.has(n.id))
               : null);
  if (ln) {
    const ty = ln.sy - ln.sr * 2.4 - 7;
    ctx.font = '600 13px ui-sans-serif, system-ui, "Segoe UI", "Microsoft YaHei", sans-serif';
    ctx.textAlign = 'center';
    ctx.lineWidth = 3.5;
    ctx.strokeStyle = 'rgba(4,8,16,0.92)';
    ctx.strokeText(ln.label, ln.sx, ty);
    ctx.fillStyle = '#eaf2ff';
    ctx.fillText(ln.label, ln.sx, ty);
    ctx.textAlign = 'start';
  }

  // 状态行：随手告诉用户"现在在什么状态、怎么退出"，不用去猜。
  // 只在文字真的变了才写 DOM，逐帧比较一个字符串可以忽略不计。
  if (st.statusEl) {
    const selNode = st.sel ? st.nodes.find(n => n.id === st.sel) : null;
    let txt;
    if (st.pathNodes && st.pathLabels) {
      txt = '路径 ' + st.pathLen + ' 跳：' + st.pathLabels.join(' → ');
    } else if (st.pathFrom) {
      const s = st.nodes.find(n => n.id === st.pathFrom);
      txt = '起点「' + (s ? s.label : st.pathFrom) + '」· Shift 点击另一个实体看最短路径';
    } else if (selNode) {
      txt = st.focus === selNode.id
        ? '聚焦「' + selNode.label + '」· 再次双击或重置退出'
        : '已选中「' + selNode.label + '」· ' + selNode.deg + ' 条关联 · 双击聚焦';
    } else {
      txt = st.auto
        ? '拖拽旋转 · 滚轮缩放 · 单击查看 · 双击聚焦 · Shift 点击量路径'
        : '自转已暂停 · 拖拽仍可旋转';
    }
    if (st.statusEl.textContent !== txt) st.statusEl.textContent = txt;
  }
}

export async function loadGraph(force) {
  const panel = document.getElementById('mem-graph-detail');
  // 8 秒内重复调用直接用缓存：启动时预热一次，切到图谱视图不必再打一次请求。
  // 自动同步（force）必须绕过缓存，否则新长出来的实体会被旧缓存挡住。
  let d = null;
  if (!force && _rawGraph && Date.now() - _graphFetchAt < 8000) {
    d = _rawGraph;
  } else {
    try {
      d = await jget('/api/graph');
      _graphFetchAt = Date.now();
    } catch (e) {
      d = _rawGraph;
    }
  }
  if (!d || !d.nodes) {
    if (panel) {
      panel.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div>' +
        '<div style="font-size:12px;color:var(--ml-text-faint)">图谱后端暂不可用</div>';
    }
    return;
  }
  _rawGraph = d;
  if (!d.nodes.length) {
    if (panel) {
      panel.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">实体图谱</div>' +
        '<div style="font-size:12px;color:var(--ml-text-faint)">暂无实体。先在对话里积累一些材料科研内容。</div>';
    }
    return;
  }

  const box = _ensureGraphContainer();
  if (!box) return;

  // 图谱视图还没显示时容器宽高为 0，此时建渲染器会得到一张尺寸错位的画布，
  // 也会白跑 rAF。数据已经存进 _rawGraph，等切过去再建。
  if (!box.clientWidth || !box.clientHeight) return;

  // 同一版图谱（实体数/关系数/更新时间都没变）不重排布局，切 tab 回来是瞬时的
  const sig = (d.nodes.length || 0) + ':' + ((d.edges || []).length) + ':' + String(d.updated_at || '');
  if (!_g3 || _g3.sig !== sig || _g3.box !== box) {
    _mountBrain(box, d, sig, _g3);
  } else {
    _g3.resize();
  }
  _g3.start();
  if (!_g3.sel) _renderLegend(panel, d);
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

/* ── 记忆自动同步 ───────────────────────────────────────
 *
 * 记忆是对话时由 sync_turn 在后台线程写入的，不需要用户手动"存"。但前端
 * 原本只在切页或点刷新时才重拉，于是刚聊出来的记忆要手动刷新才看得见。
 * 这里在记忆页可见时低频轮询（15s 一次 facet，30ms 量级的本地请求），
 * 只比条数、不做全量重载；用户正在编辑/搜索/看弹窗时不打扰。
 */
let _memSupCount = null;   // 已合并条数，与 total 一起作为"后端变了"的信号
let _memWatchTimer = 0;

async function _pollMemoryChange() {
  const page = document.getElementById('page-memory');
  if (!page || page.getClientRects().length === 0) return;   // 不在记忆页就不发请求
  if (_memEditingId) return;
  const modal = document.getElementById('mem-modal');
  if (modal && modal.classList.contains('show')) return;
  const search = document.getElementById('mem-search');
  if (search && document.activeElement === search) return;

  let f = null;
  try {
    const r = await fetch('/api/memory/facet');
    if (!r.ok) return;
    f = await r.json();
  } catch (e) {
    return;
  }
  const total = typeof f.total === 'number' ? f.total : null;
  const sup = typeof f.superseded_count === 'number' ? f.superseded_count : null;
  const changed = (total !== null && _memTotal !== null && total !== _memTotal) ||
                  (sup !== null && _memSupCount !== null && sup !== _memSupCount);
  if (!changed) return;

  // 搜索态只记下新计数，不换掉用户正在看的结果
  if (_memQuery) { _memSupCount = sup; return; }

  const list = document.getElementById('mem-list');
  const top = list ? list.scrollTop : 0;
  await loadMemories();
  if (list) list.scrollTop = top;
  // 图谱正开着就同步重建（重建会保留视角，新实体会闪一下）
  if (_g3 && _g3.running) {
    await loadGraph(true);
  }
}

function _startMemoryWatch() {
  if (_memWatchTimer) clearInterval(_memWatchTimer);
  _memWatchTimer = setInterval(() => { _pollMemoryChange().catch(() => {}); }, 15000);
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
async function fetchDupGroups(all, preFetched) {
  try {
    const r = preFetched || await fetch('/api/memory/duplicates');
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
      // 三次请求彼此不依赖，并行发出去：串行时首屏要等三个 RTT 排队，
      // 并行后总耗时约等于最慢的那一个。
      const pList = fetch('/api/memory?offset=0&limit=' + MEM_FETCH_LIMIT);
      const pSup = fetch('/api/memory?offset=0&limit=' + MEM_FETCH_LIMIT + '&include_superseded=true');
      const pDup = fetch('/api/memory/duplicates');
      const [r, r2, rdup] = await Promise.all([pList, pSup, pDup]);

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
        const d2 = await r2.json();
        _memSupersededRows = (d2.memories || []).filter(m => m.superseded_by);
        _memSupersededRows.forEach(m => {
          _memSuperseded[String(m.id)] = { keep_id: m.superseded_by, at: m.superseded_at };
        });
      } catch (e2) {
        _memSupersededRows = [];
      }
      _memSupCount = _memSupersededRows.length;
      _memDupGroups = await fetchDupGroups(_memAll, rdup);
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
  _startMemoryWatch();
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
        // 容器刚变可见时尺寸还是 0，等一帧拿到真实宽高再建渲染器
        setTimeout(() => {
          Promise.resolve(loadGraph()).catch(() => {});
        }, 60);
      } else if (view === 'list' && !_memAll.length && !_memHits.length) {
        loadMemories();
      }
      // 3D 只在图谱视图里跑 rAF：切回列表就停，别让它在后台空转烧 CPU
      if (view !== 'graph' && _g3) _g3.stop();
    };
  });
}
