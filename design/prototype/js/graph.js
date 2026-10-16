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
  // 已有 .graph-main 容器则复用；否则在 page-memory 内自建图谱面板
  let main = document.querySelector('.graph-main');
  if (main) return main;
  const page = document.getElementById('page-memory');
  if (!page) return null;
  const body = page.querySelector('.page-body') || page;
  // 避免重复注入
  main = document.getElementById('vis-graph-canvas-wrap');
  if (main) return main;

  const wrap = document.createElement('div');
  wrap.id = 'vis-graph-canvas-wrap';
  wrap.style.cssText = 'display:flex;gap:14px;height:460px;margin-bottom:14px;';
  wrap.innerHTML =
    '<div style="flex:1;position:relative;border:1px solid var(--ml-card-border,' +
    ');border-radius:15px;background:rgba(10,14,26,.55);overflow:hidden" id="vis-graph-canvas"></div>' +
    '<div style="width:260px;flex-shrink:0;border:1px solid var(--ml-card-border);' +
    'border-radius:15px;padding:14px;overflow-y:auto;background:rgba(10,14,26,.45)" id="mem-detail">' +
    '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div>' +
    '<div style="font-size:12px;color:var(--ml-text-faint)">点击节点查看关联实体与来源。</div></div>';
  body.insertBefore(wrap, body.firstChild);
  return wrap.querySelector('#vis-graph-canvas');
}

function _renderDetailPanel(nodeId) {
  const panel = document.getElementById('mem-detail');
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
    const dd = document.getElementById('mem-detail');
    if (dd) dd.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div><div style="font-size:12px;color:var(--ml-text-faint)">图谱后端暂不可用</div>';
    return;
  }
  _rawGraph = d;
  const countEl = document.querySelector('.graph-main > div');
  if (countEl) countEl.textContent = (d.fallback ? '示例图谱 · ' : '') + d.nodes.length + ' 实体 · ' + (d.edges ? d.edges.length : 0) + ' 关系';

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
    const dd = document.getElementById('mem-detail');
    if (dd) dd.innerHTML = '<div style="font-weight:700;margin-bottom:9px;font-size:13px">记忆详情</div>' +
      '<div style="font-size:12px;color:var(--ml-warn)">图谱可视化库加载失败，显示实体列表：</div>' +
      d.nodes.slice(0, 15).map(n => '<div class="mem-item"><span class="mem-cat" style="color:' + (n.color || '#94a3b8') + '">●</span> ' + esc(String(n.label || n.id)) + '</div>').join('');
  }
}

/* ── 记忆管理页（mem-list / mem-cats / mem-search） ────── */
let _memories = [];
let _memCat = 'all';
let _memQuery = '';

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

export async function loadMemories() {
  const list = document.getElementById('mem-list');
  if (list) list.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">加载中…</div>';
  try {
    const url = '/api/memory' + (_memQuery ? '?q=' + encodeURIComponent(_memQuery) : '');
    const r = await fetch(url);
    const data = await r.json();
    _memories = data.memories || [];
    const cnt = document.getElementById('mem-count');
    if (cnt) cnt.textContent = _memories.length + ' 条记忆 · Mem0 语义检索';
    renderMemCats();
    renderMemories();
  } catch (e) {
    if (list) list.innerHTML = '<div style="color:var(--ml-danger);font-size:13px;padding:40px;text-align:center">加载失败：' + esc(e.message) + '</div>' +
      '<div style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="loadMemories()">重试</button></div>';
  }
}

function renderMemCats() {
  const cats = {};
  _memories.forEach(m => { cats[m.category] = (cats[m.category] || 0) + 1; });
  const box = document.getElementById('mem-cats');
  if (!box) return;
  const order = ['用户', '实验', '材料', '结论', '其他'];
  let html = '<div class="mem-cat' + (_memCat === 'all' ? ' active' : '') + '" data-cat="all">全部<span class="mc-count">' + _memories.length + '</span></div>';
  order.forEach(c => {
    if (cats[c]) html += '<div class="mem-cat' + (_memCat === c ? ' active' : '') + '" data-cat="' + c + '">' + c + '<span class="mc-count">' + cats[c] + '</span></div>';
  });
  Object.keys(cats).forEach(c => {
    if (!order.includes(c)) html += '<div class="mem-cat' + (_memCat === c ? ' active' : '') + '" data-cat="' + c + '">' + c + '<span class="mc-count">' + cats[c] + '</span></div>';
  });
  box.innerHTML = html;
  box.querySelectorAll('.mem-cat').forEach(el => {
    el.onclick = () => { _memCat = el.dataset.cat; renderMemCats(); renderMemories(); };
  });
}

function renderMemories() {
  const list = document.getElementById('mem-list');
  if (!list) return;
  const filtered = _memCat === 'all' ? _memories : _memories.filter(m => m.category === _memCat);
  if (!filtered.length) {
    list.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">暂无记忆</div>';
    return;
  }
  list.innerHTML = filtered.map(m => {
    const cat = m.category || '其他';
    const score = m.score ? (m.score * 100).toFixed(0) + '%' : '';
    return '<div class="mem-card">' +
      '<div class="mc-head"><span class="mc-tag cat-' + cat + '">' + cat + '</span>' +
      (score ? '<span class="mc-score">相关度 ' + score + '</span>' : '') +
      '<button class="mc-del" data-id="' + m.id + '" title="删除">✕</button></div>' +
      '<div class="mc-text">' + escapeHtml(m.memory) + '</div></div>';
  }).join('');
  list.querySelectorAll('.mc-del').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('确定删除这条记忆？')) return;
      try {
        await fetch('/api/memory/' + btn.dataset.id, { method: 'DELETE' });
        loadMemories();
      } catch (e) { alert('删除失败：' + e.message); }
    };
  });
}

export function bindMemoryUI() {
  const search = document.getElementById('mem-search');
  if (search) {
    let t;
    search.oninput = () => { clearTimeout(t); t = setTimeout(() => { _memQuery = search.value.trim(); loadMemories(); }, 400); };
  }
  const addBtn = document.getElementById('btn-add-mem');
  if (addBtn) addBtn.onclick = () => { const m = document.getElementById('mem-modal'); if (m) { m.classList.add('show'); document.getElementById('mem-new-text').focus(); } };
  const cancelBtn = document.getElementById('btn-mem-cancel');
  if (cancelBtn) cancelBtn.onclick = () => { const m = document.getElementById('mem-modal'); if (m) m.classList.remove('show'); };
  const saveBtn = document.getElementById('btn-mem-save');
  if (saveBtn) saveBtn.onclick = async () => {
    const text = document.getElementById('mem-new-text').value.trim();
    if (!text) return;
    try {
      await fetch('/api/memory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: text }) });
      document.getElementById('mem-new-text').value = '';
      const m = document.getElementById('mem-modal'); if (m) m.classList.remove('show');
      loadMemories();
    } catch (e) { alert('添加失败：' + e.message); }
  };
  const refreshBtn = document.getElementById('btn-refresh-mem');
  if (refreshBtn) refreshBtn.onclick = () => loadMemories();
  const modal = document.getElementById('mem-modal');
  if (modal) modal.onclick = (e) => { if (e.target === modal) modal.classList.remove('show'); };
}
