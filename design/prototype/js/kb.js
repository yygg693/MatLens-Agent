/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · kb.js（数据源双模：本地库 / 云端学术 API）
 *
 * 2026-10-15 本轮改动：
 *  1. **新增云端学术 API 数据源**。此前知识库只能索引本地文件，页面
 *     完全没体现「联网检索文献」这条真实需求路径。依据
 *     docs/kb_cloud_sources_research.md 的 GitHub 横向调研，实测可用
 *     的免 key 源为 OpenAlex / Crossref / arXiv（已实现并实测通过）。
 *  2. **中文文献如实标注为不可用**。知网无公开 API（仅机构合作），
 *     维普返回 412。界面**灰显并写明原因 + 替代路径**，不伪造端点，
 *     也不让用户误以为功能漏做。
 *  3. **score 阈值修正**（上一轮真 bug）：离线哈希嵌入余弦相似度实测
 *     0.10–0.21，旧代码按 ≥0.7/≥0.5 分档导致全部标红。改为相对排序。
 *  4. **存储信息可视化**：stats().dir / 向量后端 / 占用此前从不展示。
 *  5. 保留并接齐：删库、删单篇、精读抽屉、本地路径批量导入、top_k 可调。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jpost, jdel, S } from './core.js';

/* ── 状态 ──────────────────────────────────────────────── */
let _docFilter = '';
let _docCache = [];
let _kbMode = 'local';          // 'local' | 'cloud'
let _sources = [];              // 云端源目录（后端 /api/kb/sources）
let _srcChecked = {};           // { source_id: bool }
let _webItems = [];             // 云端检索结果
let _picked = new Set();        // 勾选待导入的文献 id

/* ══════════════════════════════════════════════════════════
 * 一、模式切换
 * ══════════════════════════════════════════════════════════ */
export function switchKbMode(mode) {
  _kbMode = mode === 'cloud' ? 'cloud' : (mode === 'dataset' ? 'dataset' : 'local');
  document.querySelectorAll('#page-kb .kb-mode').forEach(b =>
    b.classList.toggle('active', b.dataset.kbmode === _kbMode));
  // 云端/数据集模式隐藏本地检索条与 tab（那套控件对它们无意义），反之亦然
  const localBar = document.querySelector('#page-kb .kb-searchbar');
  const tabs = document.querySelector('#page-kb .kb-tabs');
  const panes = document.querySelectorAll('#page-kb .kb-tabpane');
  const cloud = $id('kb-cloud-pane');
  const dsPane = $id('kb-dataset-pane');
  const store = $id('kb-storeinfo');
  if (_kbMode === 'cloud' || _kbMode === 'dataset') {
    if (localBar) localBar.style.display = 'none';
    if (tabs) tabs.style.display = 'none';
    panes.forEach(p => { p.style.display = 'none'; });
    if (cloud) cloud.style.display = _kbMode === 'cloud' ? '' : 'none';
    if (dsPane) dsPane.style.display = _kbMode === 'dataset' ? '' : 'none';
    if (store) store.style.display = 'none';
    _renderSrcList();
    if (_kbMode === 'cloud') {
      if (!$id('kb-web-results').innerHTML.trim()) _renderWebEmpty();
    } else {
      // 数据集模式：懒加载源目录，避免拖慢本地库首屏
      import('./kb_dataset.js')
        .then(m => { if (m.loadDatasetSources) m.loadDatasetSources(); })
        .catch(() => {});
    }
  } else {
    if (localBar) localBar.style.display = '';
    if (tabs) tabs.style.display = '';
    // 恢复当前 tab 的显示（不要全部显示，否则叠在一起）
    const cur = document.querySelector('#page-kb .kb-tabpane.active');
    panes.forEach(p => { p.style.display = (p === cur) ? '' : 'none'; });
    if (cloud) cloud.style.display = 'none';
    if (dsPane) dsPane.style.display = 'none';
    renderStoreInfo();
  }
  loadKb();
}

/* ══════════════════════════════════════════════════════════
 * 二、本地库（原有能力，保持不变）
 * ══════════════════════════════════════════════════════════ */
export async function loadKb() {
  const el = $id('kb-list');
  if (!el) return;
  const nLocal = $id('km-local-n');
  const nCloud = $id('km-cloud-n');

  // ⚠️ 云端/数据集模式下左栏展示**源目录**，但本地库数据仍要加载 ——
  //    S.kb（当前库）与 doc-count（文献数）都依赖它。数据集导入后文献数会变，
  //    不刷新用户看不到变化（实测踩过：导入后计数纹丝不动）。
  const isRemote = (_kbMode === 'cloud' || _kbMode === 'dataset');

  if (!isRemote) {
    el.innerHTML = '<div style="padding:14px;color:var(--ml-text-faint);font-size:12px;text-align:center">加载中…</div>';
  }
  let d = null;
  try { d = await jget('/api/kb'); } catch (e) { /* 静默 */ }
  if (!d || !d.kbs) {
    if (!isRemote) {
      el.innerHTML = '<div style="padding:14px;color:var(--ml-danger);font-size:12px;text-align:center">知识库加载失败</div>' +
        '<div style="text-align:center"><button class="btn btn-ghost btn-sm" id="btn-kb-retry">重试</button></div>';
      const rb = $id('btn-kb-retry'); if (rb) rb.onclick = () => loadKb();
    }
    return;
  }
  if (nLocal) nLocal.textContent = d.kbs.length;
  _countCloud(d.kbs.length);
  if (d.kbs.length) {
    S.kb = (d.kbs.find(k => k.active) || d.kbs[0]);
  }
  if (isRemote) {
    if (_kbMode === 'dataset') {
      // 数据集模式的左栏要显示**数据集源**目录 —— 沿用云端模式的学术 API
      // 目录会让用户在「数据集」标签下看到 OpenAlex/Crossref，完全是另一回事。
      import('./kb_dataset.js')
        .then(m => { if (m.renderDatasetSrcList) m.renderDatasetSrcList(); })
        .catch(() => { _renderSrcList(); });
    } else {
      _renderSrcList();
      // 左栏刚渲染出源目录（含健康圆点），把自检状态刷上去
      import('./kb_health.js')
        .then(m => { if (m.resyncHealthDots) m.resyncHealthDots(); })
        .catch(() => {});
    }
    if (S.kb && S.kb.name) {
      loadDocs(S.kb.name);
      renderStoreInfo();
    }
    return;
  }
  if (!d.kbs.length) {
    el.innerHTML = '<div class="kb-sec">本地知识库</div>' +
      '<div class="kb-empty" style="padding:22px 10px">' +
      '<div class="kb-empty-t">还没有知识库</div>' +
      '<div class="kb-empty-h">点右上角「新建知识库」，或切到「云端 API」联网捞文献</div></div>';
    return;
  }
  el.innerHTML = '<div class="kb-sec">本地知识库 · ' + d.kbs.length + '</div>' + d.kbs.map(k => {
    const act = k.active ? ' active' : '';
    const kbSize = Math.round((k.size_bytes || 0) / 1024);
    return '<div class="kb-item' + act + '" data-kbname="' + esc(k.name) + '" title="' + esc(k.name) + '">' +
      '<div class="k-name">' + esc(k.display_name || k.name) + '</div>' +
      '<div class="k-meta"><span>' + (k.docs || 0) + ' 文献</span><span>' + (k.chunks || 0) + ' 分块</span>' +
      (kbSize ? '<span>' + kbSize + ' KB</span>' : '') + '</div>' +
      (k.active ? '<span class="k-active-dot" title="当前库"></span>' : '') +
      '<button class="kb-del" data-delkb="' + esc(k.name) + '" title="删除此知识库">✕</button>' +
      '</div>';
  }).join('');
  el.querySelectorAll('.kb-item').forEach(item => {
    item.onclick = (e) => {
      if (e.target.closest('.kb-del')) return;
      switchKb(item.dataset.kbname);
    };
  });
  el.querySelectorAll('[data-delkb]').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation();
      const name = b.dataset.delkb;
      const kb = d.kbs.find(x => x.name === name);
      if (!confirm('删除知识库「' + (kb ? kb.display_name : name) + '」？\n' +
          '将一并删除 ' + ((kb && kb.chunks) || 0) + ' 个分块的索引。\n磁盘上的原始文献文件不受影响。')) return;
      try {
        const r = await jdel('/api/kb/' + encodeURIComponent(name));
        if (r && r.ok) { toast('知识库已删除', 'ok'); await loadKb(); }
        else toast('删除失败', 'err');
      } catch (err) { toast('删除失败：' + (err.message || err), 'err'); }
    };
  });
  if (S.kb) {
    const cn = $id('cur-kb-name'); if (cn) cn.textContent = S.kb.display_name || S.kb.name;
    const kbTag = $id('chat-kb-tag'); if (kbTag) kbTag.textContent = S.kb.display_name || S.kb.name;
    loadDocs(S.kb.name);
    renderStoreInfo();
  }
}

function _countCloud(localN) {
  const el = $id('km-cloud-n');
  if (el) el.textContent = (_sources.length || localN || 0);
}

/** 切 tab（文献 / 检索结果 / 添加文献）。 */
export function switchKbTab(tab) {
  if (_kbMode === 'cloud') return;   // 云端模式不用本地 tab
  document.querySelectorAll('#page-kb .kb-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.kbtab === tab));
  document.querySelectorAll('#page-kb .kb-tabpane').forEach(p => {
    const on = p.dataset.kbpane === tab;
    p.classList.toggle('active', on);
    p.style.display = on ? '' : 'none';
  });
}

/** 存储信息：磁盘位置 / 索引后端 / 占用（此前后端有、前端从不展示）。 */
function renderStoreInfo() {
  const box = $id('kb-storeinfo');
  if (!box || !S.kb || _kbMode === 'cloud') return;
  if (!S.kb.dir) { box.style.display = 'none'; return; }
  const kb = Math.round((S.kb.size_bytes || 0) / 1024);
  box.innerHTML = '<b>当前库存储</b><br>' +
    '位置：<code>' + esc(S.kb.dir) + '</code><br>' +
    '向量后端：' + esc(S.kb.vector_backend || '未知') +
    ' · 占用：' + (kb > 1024 ? (kb / 1024).toFixed(1) + ' MB' : kb + ' KB') +
    ' · 文献 ' + (S.kb.docs || 0) + ' 篇 / 分块 ' + (S.kb.chunks || 0);
  box.style.display = '';
}

/** 文献行渲染（带筛选 + 操作按钮）。 */
function _renderDocs(d) {
  const el = $id('doc-list');
  if (!el) return;
  const cnt = $id('doc-count');
  let list = (d && d.document_list) || [];
  _docCache = list;
  if (cnt) cnt.textContent = '文献 ' + list.length + ' 篇 / ' + ((d && d.chunks) || 0) + ' 分块';
  const q = _docFilter.trim().toLowerCase();
  if (q) list = list.filter(x => String(x.source || '').toLowerCase().includes(q));

  if (!list.length) {
    el.innerHTML = '<div class="kb-empty">' +
      '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>' +
      '<div class="kb-empty-t">' + (_docFilter ? '没有匹配的文献' : '还没有文献') + '</div>' +
      '<div class="kb-empty-h">' + (_docFilter ? '换个关键词试试' : '切到「添加文献」上传，或用「云端 API」联网检索后一键导入') + '</div></div>';
    return;
  }

  el.innerHTML = list.map(doc => {
    const name = String(doc.source || '未知来源').split(/[\\/]/).pop();
    const id = esc(String(doc.id));
    return '<div class="doc-item" data-docid="' + id + '">' +
      '<span class="d-icon"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>' +
      '<div class="d-main"><div class="d-name" title="' + esc(doc.source || '') + '">' + esc(name) + '</div>' +
      '<div class="d-sub">' + (doc.chunks || 0) + ' 分块</div></div>' +
      '<div class="d-ops">' +
        '<button class="d-op" data-act="read" title="精读全文">精读</button>' +
        '<button class="d-op d-op-danger" data-act="del" title="从库中移除（不删磁盘文件）">移除</button>' +
      '</div></div>';
  }).join('');

  el.querySelectorAll('.doc-item').forEach(row => {
    const id = row.dataset.docid;
    row.querySelector('[data-act="read"]').onclick = () => openDocReader(id);
    row.querySelector('[data-act="del"]').onclick = async () => {
      const doc = _docCache.find(x => String(x.id) === id);
      const nm = doc ? String(doc.source || '').split(/[\\/]/).pop() : id;
      if (!confirm('从知识库移除「' + nm + '」？\n该文献的 ' + ((doc && doc.chunks) || 0) + ' 个分块索引会被删除，磁盘原文件不受影响。')) return;
      try {
        const r = await jdel('/api/kb/' + encodeURIComponent(S.kb.name) + '/documents/' + encodeURIComponent(id));
        if (r && r.ok) { toast('已移除 ' + nm + '（移除 ' + r.removed_chunks + ' 个分块）', 'ok'); loadDocs(S.kb.name); loadKb(); }
        else toast('移除失败', 'err');
      } catch (err) { toast('移除失败：' + (err.message || err), 'err'); }
    };
  });
}

export async function switchKb(name) {
  const d = await jpost('/api/kb/' + encodeURIComponent(name) + '/switch');
  if (d && d.ok) { S.kb = { name: name }; await loadKb(); toast('已切换到「' + name + '」', 'ok'); }
  else toast('切换失败', 'err');
}

/** 按文件名筛选（本地过滤，不重新请求）。 */
export function filterDocs(q) {
  _docFilter = q || '';
  _renderDocs({ document_list: _docCache, chunks: (_docCache || []).reduce((a, x) => a + (x.chunks || 0), 0) });
}

export async function loadDocs(name) {
  if (!S.kb || name !== S.kb.name) return;
  let d = null;
  try { d = await jget('/api/kb/' + encodeURIComponent(name)); } catch (e) { /* 静默 */ }
  if (d) { S.kb = Object.assign({}, S.kb, d); renderStoreInfo(); }
  _renderDocs(d || {});
}

/* ── 文献精读抽屉 ────────────────────────────────────── */
export async function openDocReader(docId) {
  const mask = $id('kb-read-mask'), panel = $id('kb-read-panel');
  const body = $id('kb-read-body'), title = $id('kb-read-title'), sub = $id('kb-read-sub');
  if (!panel || !mask) return;
  mask.classList.add('show');
  panel.classList.add('show');
  body.innerHTML = '<div class="kb-read-loading">加载全文…</div>';
  title.textContent = '文献';
  sub.textContent = '';
  try {
    const d = await jget('/api/kb/' + encodeURIComponent(S.kb.name) + '/documents/' + encodeURIComponent(docId));
    if (!d) throw new Error('无返回');
    const nm = String(d.source || '').split(/[\\/]/).pop();
    title.textContent = nm;
    sub.textContent = d.chunk_count + ' 分块' + (d.path ? (' · ' + d.path) : '');
    body.innerHTML = (d.chunks || []).map(c =>
      '<div class="kb-chunk" data-idx="' + c.chunk_idx + '">' +
      '<span class="kb-chunk-n">#' + (Number(c.chunk_idx) + 1) + '</span>' +
      '<div class="kb-chunk-t">' + esc(c.text || '') + '</div></div>').join('');
  } catch (e) {
    body.innerHTML = '<div class="kb-read-loading" style="color:var(--ml-danger)">加载失败：' +
      esc(e.message || e) + '</div>';
  }
}

export function closeDocReader() {
  const mask = $id('kb-read-mask'), panel = $id('kb-read-panel');
  if (mask) mask.classList.remove('show');
  if (panel) panel.classList.remove('show');
}

/* ── 本地导入 ────────────────────────────────────────── */
export async function importByPaths() {
  if (!S.kb) { toast('请先选择知识库'); return; }
  const v = prompt('输入本地文件的绝对路径（多个用逗号分隔）\n' +
    '例如 D:////MatLens////papers////a.pdf, D:////MatLens////data////b.txt');
  if (!v || !v.trim()) return;
  const paths = v.split(/[,，;；\n]/).map(x => x.trim()).filter(Boolean);
  if (!paths.length) return;
  toast('正在导入 ' + paths.length + ' 个路径…');
  try {
    const r = await jpost('/api/kb/' + encodeURIComponent(S.kb.name) + '/import', { paths });
    if (r && r.ok !== false) {
      toast('导入完成：' + (r.added != null ? r.added : paths.length) + ' 篇', 'ok');
      loadDocs(S.kb.name); loadKb();
      switchKbTab('docs');
    } else {
      toast('导入失败：' + ((r && (r.error || r.detail)) || '未知错误'), 'err');
    }
  } catch (e) { toast('导入失败：' + (e.message || e), 'err'); }
}

export async function createKb() {
  const name = prompt('知识库名称（中文亦可，内部自动转 slug）：');
  if (!name) return;
  const d = await jpost('/api/kb', { name: name });
  if (d && d.ok) {
    toast('已创建「' + (d.display_name || d.name) + '」', 'ok');
    if (d.name) { S.kb = { name: d.name, display_name: d.display_name }; }
    loadKb();
  } else toast('创建失败：' + ((d && (d.detail || d.error)) || '未知错误'), 'err');
}

export function pickUpload() {
  if (!S.kb) { toast('请先选择知识库'); return; }
  const fi = document.createElement('input');
  fi.type = 'file';
  fi.multiple = true;
  fi.accept = '.pdf,.txt,.md,.csv,.xlsx,.xls,.docx';
  fi.onchange = async () => {
    const files = Array.from(fi.files || []);
    if (!files.length) return;
    toast('正在上传并索引 ' + files.length + ' 个文件…');
    let ok = 0, fail = 0;
    for (const f of files) {
      try {
        const fd = new FormData();
        fd.append('file', f);
        const r = await fetch('/api/kb/' + encodeURIComponent(S.kb.name) + '/documents',
          { method: 'POST', body: fd });
        const d = await r.json().catch(() => ({}));
        if (d && d.ok !== false) ok++; else fail++;
      } catch (e) { fail++; }
    }
    toast('完成：成功 ' + ok + ' 篇' + (fail ? ('，失败 ' + fail + ' 篇') : ''), fail ? 'err' : 'ok');
    loadKb(); loadDocs(S.kb.name);
  };
  fi.click();
}

/* ── 本地检索 ────────────────────────────────────────── */
export async function queryKb() {
  if (!S.kb) { toast('请先选择知识库'); return; }
  const q = $id('kb-query').value.trim();
  if (!q) return;
  const el = $id('kb-results');
  const topk = parseInt(($id('kb-topk') || {}).value || '4', 10);
  el.innerHTML = '<div class="kb-loading">检索中…</div>';
  switchKbTab('results');
  const badge = $id('kb-hit-n');
  try {
    const d = await jpost('/api/kb/' + encodeURIComponent(S.kb.name) + '/query',
      { question: q, top_k: topk });
    const hits = (d && d.results) || [];
    if (badge) {
      if (hits.length) { badge.textContent = ' ' + hits.length; badge.style.display = ''; }
      else badge.style.display = 'none';
    }
    if (!hits.length) {
      el.innerHTML = '<div class="kb-empty"><div class="kb-empty-t">没有命中</div>' +
        '<div class="kb-empty-h">试试更短的关键词，或换个说法（离线嵌入对长句匹配较弱）。</div></div>';
      return;
    }

    /* score 相对化：离线哈希嵌入余弦实测 0.10–0.21，绝对值无判优意义。
       旧代码按 ≥0.7/≥0.5 分档 → 全落进「低」红色，让用户以为检索全错。
       现只用相对位次标「最相关」，原始值如实展示。 */
    const best = Math.max(...hits.map(h => Number(h.score || 0))) || 1;
    el.innerHTML = '<div class="kb-hit-note">命中 ' + hits.length + ' 条 ·' +
      '相似度为离线嵌入的余弦值，绝对值偏低属正常，请按下方排序取用</div>' +
      hits.map((r, i) => {
        const srcName = String(r.source || '').split(/[\\/]/).pop();
        const score = Number(r.score || 0);
        const near = score >= best * 0.9;
        const text = String(r.text || '');
        const cut = text.length > 260;
        return '<div class="kb-hit' + (i === 0 ? ' is-best' : '') + '">' +
          '<div class="kb-hit-top">' +
            '<span class="kb-rank' + (i === 0 ? ' r1' : '') + '">' + (i + 1) + '</span>' +
            '<span class="kb-hit-src" title="' + esc(r.source || '') + '">' + esc(srcName) + '</span>' +
            (near ? '<span class="kb-badge">最相关</span>' : '') +
            '<span class="kb-score" title="余弦相似度">相似度 ' + score.toFixed(3) + '</span>' +
          '</div>' +
          '<div class="kb-hit-text">' + esc(cut ? text.slice(0, 260) + '…' : text) + '</div>' +
          (cut ? '<button class="kb-more">展开全文</button>' : '') +
          '</div>';
      }).join('');
    el.querySelectorAll('.kb-more').forEach(b => {
      b.onclick = () => {
        const t = b.previousElementSibling;
        const full = t.dataset.full || '';
        if (!t.dataset.full) {
          t.dataset.full = t.textContent.replace(/…$/, '');
        }
        const open = b.dataset.on === '1';
        if (open) { t.textContent = t.dataset.full.slice(0, 260) + '…'; b.textContent = '展开全文'; }
        else { t.textContent = t.dataset.full; b.textContent = '收起'; }
        b.dataset.on = open ? '0' : '1';
      };
    });
  } catch (e) {
    el.innerHTML = '<div class="kb-loading" style="color:var(--ml-danger)">检索失败：' +
      esc(e.message || e) + '</div>';
  }
}

/* ══════════════════════════════════════════════════════════
 * 三、云端学术 API
 * ══════════════════════════════════════════════════════════ */

/** 拉取源目录（含本地库清单与不可用源说明）。 */
export async function loadSources() {
  let d = null;
  try { d = await jget('/api/kb/sources'); } catch (e) { return; }
  if (!d) return;
  const items = (d.cloud && d.cloud.items) || [];
  // 勾选状态以后端 default_on 为准（唯一真相来源，避免两边默认值漂移）
  _sources = items;
  _srcChecked = {};
  items.forEach(s => { _srcChecked[s.id] = !!s.default_on && s.configured !== false; });
  _unavailable = d.unavailable || [];
  _rootPath = (d.local && d.local.root) || '';
  const n = $id('km-cloud-n');
  if (n) n.textContent = items.filter(s => s.configured !== false).length;
  if (_kbMode === 'cloud') _renderSrcList();
}

let _unavailable = [];
let _rootPath = '';

function _renderSrcList() {
  const el = $id('kb-list');
  if (!el) return;
  const avail = _sources.filter(s => s.configured !== false);
  const locked = _sources.filter(s => s.configured === false);
  let h = '<div class="kb-sec">可用学术 API · ' + avail.length + '</div>';
  h += avail.map(s => {
    const on = !!_srcChecked[s.id];
    return '<div class="kb-src' + (on ? ' on' : ' off') + '" data-src="' + esc(s.id) + '" title="点击勾选/取消">' +
      '<div class="kb-src-top">' +
        '<input class="kb-src-cb" type="checkbox"' + (on ? ' checked' : '') + ' tabindex="-1">' +
        '<span class="kb-src-name">' + esc(s.label) + '</span>' +
      '</div>' +
      '<div class="kb-src-meta">' +
        '<span class="kb-tag">' + esc(s.cover || '') + '</span>' +
        (s.cn_coverage ? '<span class="kb-tag cn">中文较好</span>' : '') +
        (s.key_required ? '<span class="kb-tag key">需密钥</span>' : '') +
        '<span class="kb-tag ' + (on ? 'on' : 'off') + '">' + (on ? '已启用' : '未启用') + '</span>' +
        '<span class="kb-src-dot" data-dot="' + esc(s.id) + '" title="未测试"></span>' +
      '</div>' +
      '<div class="kb-src-note">' + esc(s.note || '') + '</div>' +
      '</div>';
  }).join('');
  if (locked.length) {
    h += '<div class="kb-sec">需凭据 · ' + locked.length + '</div>';
    h += locked.map(s =>
      '<div class="kb-src locked" title="点击复制配置说明">' +
        '<div class="kb-src-top">' +
          '<input class="kb-src-cb" type="checkbox" disabled tabindex="-1">' +
          '<span class="kb-src-name">' + esc(s.label) + '</span>' +
          '<span class="kb-tag key">未配置</span>' +
        '</div>' +
        '<div class="kb-src-note">' + esc(s.note || '') + '</div>' +
      '</div>').join('');
  }
  if (_unavailable.length) {
    h += '<div class="kb-sec">无公开接口 · 如实说明</div>';
    h += _unavailable.map(s =>
      '<div class="kb-src-na">' +
        '<div class="kb-src-na-top">' +
          '<span class="kb-src-na-name">' + esc(s.label) + '</span>' +
          '<span class="kb-tag" style="color:var(--ml-warn)">' + esc(s.reason) + '</span>' +
        '</div>' +
        '<div class="kb-src-na-why">' + esc(s.detail) + '</div>' +
        '<div class="kb-src-na-how">替代：' + esc(s.workaround) + '</div>' +
      '</div>').join('');
  }
  if (_rootPath) {
    h += '<div class="kb-storeinfo" style="margin-top:11px">' +
      '<b>本地索引根目录</b><br><code>' + esc(_rootPath) + '</code></div>';
  }
  el.innerHTML = h;

  // 勾选交互
  el.querySelectorAll('.kb-src[data-src]').forEach(row => {
    row.onclick = (e) => {
      const id = row.dataset.src;
      _srcChecked[id] = !_srcChecked[id];
      _renderSrcList();
    };
  });
  // 需凭据的源：点击给配置指引，而不是让用户点了却只看到一个报错
  el.querySelectorAll('.kb-src.locked').forEach(row => {
    row.onclick = () => { toast(_lockedHint(row), 'err'); };
  });
}

function _lockedHint(row) {
  const name = row.querySelector('.kb-src-name');
  const label = name ? name.textContent : '该源';
  const s = _sources.find(x => x.label === label);
  if (s && s.key_env) return label + ' 需要环境变量 ' + s.key_env;
  return label + ' 需要 API Key';
}

function _renderWebEmpty() {
  const el = $id('kb-web-results');
  if (!el) return;
  el.innerHTML = '<div class="kb-empty">' +
    '<svg viewBox="0 0 24 24"><path d="M17.5 19a4.5 4.5 0 0 0 .5-8.97A6 6 0 0 0 6.1 9.4A4.5 4.5 0 0 0 6.5 19z"/></svg>' +
    '<div class="kb-empty-t">联网检索开放学术数据库</div>' +
    '<div class="kb-empty-h">左侧勾选数据源（默认 OpenAlex / Crossref / arXiv），<br>' +
    '输入检索式后点「检索云端」，勾中的文献可一键沉淀进本地库</div></div>';
}

function _renderSrcStat(perSource, elapsed) {
  const box = $id('kb-srcstat');
  if (!box) return;
  const keys = Object.keys(perSource || {});
  if (!keys.length) {
    box.innerHTML = '';
    document.querySelectorAll('[data-dot]').forEach(d => {
      d.className = 'kb-src-dot';
      d.title = '未测试';
    });
    return;
  }
  box.innerHTML = '<span class="kb-srcstat-i">' + esc(String(elapsed || 0)) + ' ms</span>' +
    keys.map(k => {
      const v = perSource[k];
      const ok = v.ok;
      const dotCls = ok ? 'ok' : 'bad';
      return '<span class="kb-srcstat-i ' + (ok ? 'ok' : 'bad') + '" title="' +
          esc(ok ? ('返回 ' + v.n + ' 条') : v.error) + '">' +
        '<span class="kb-src-dot ' + dotCls + '"></span>' + esc(v.label || k) +
        (ok ? (' · ' + v.n) : '') +
        (ok ? '' : ('<span class="ss-e">' + esc(v.error || '') + '</span>')) +
        '</span>';
    }).join('');
  // 同步左栏圆点状态
  document.querySelectorAll('[data-dot]').forEach(d => {
    const v = (perSource || {})[d.dataset.dot];
    d.className = 'kb-src-dot' + (v ? (v.ok ? ' ok' : ' bad') : '');
    d.title = v ? (v.ok ? '返回 ' + v.n + ' 条 · ' + v.ms + 'ms' : v.error) : '未测试';
  });
}

/** 云端多源检索。 */
export async function webSearch() {
  const inp = $id('kb-web-query');
  const q = inp.value.trim();
  if (!q) { toast('请输入检索式'); return; }
  const srcs = Object.keys(_srcChecked).filter(k => _srcChecked[k]);
  if (!srcs.length) { toast('请至少勾选一个数据源'); return; }
  const per = parseInt(($id('kb-web-topk') || {}).value || '5', 10);
  const box = $id('kb-web-results');
  box.innerHTML = '<div class="kb-loading">正在向 ' + srcs.length + ' 个学术源并发检索…</div>';
  $id('kb-srcstat').innerHTML = '';
  _webItems = [];
  _picked.clear();
  _syncPickBar();
  _renderSrcStat(null, 0);   // 清空上一轮的状态条，否则旧耗时/旧错误会一直挂在结果上方
  try {
    const d = await jpost('/api/kb/web-search', { query: q, sources: srcs, per_source: per });
    _webItems = (d && d.items) || [];
    _renderSrcStat(d && d.per_source, d && d.elapsed_ms);
    _renderWebResults();
  } catch (e) {
    box.innerHTML = '<div class="kb-empty"><div class="kb-empty-t" style="color:var(--ml-danger)">检索失败</div>' +
      '<div class="kb-empty-h">' + esc(e.message || e) + '</div></div>';
  }
}

/** 只放行 http/https 链接。
 *
 *  云端 API 的 url / oa_url 属于**外部输入**：esc() 已防住引号注入，
 *  但拦不住 `javascript:alert(1)` 这类伪协议。这里做协议白名单，
 *  避免把可执行伪协议写进 href。
 */
function _safeUrl(u) {
  const s = String(u || '').trim();
  return /^https?:\/\//i.test(s) ? s : '';
}

function _renderWebResults() {  const el = $id('kb-web-results');
  if (!el) return;
  if (!_webItems.length) {
    el.innerHTML = '<div class="kb-empty"><div class="kb-empty-t">没有命中</div>' +
      '<div class="kb-empty-h">所有勾选源都未返回结果。可尝试更短的英文检索式，' +
      '或在上方状态条查看各源的具体失败原因。</div></div>';
    return;
  }
  el.innerHTML = '<div class="kb-hit-note">共 ' + _webItems.length + ' 条（跨源按 DOI 去重，' +
    '有 DOI 与开放获取全文的优先）· 勾选后导入本地库即可被写作时 RAG 引用</div>' +
    _webItems.map((it, i) => {
      const id = esc(String(i));
      const picked = _picked.has(i);
      const abs = it.abstract || it.snippet || '';
      /* 跳转链接优先级：OA 全文 PDF > 来源页 landing > doi.org 兜底。
         云端 API 并不保证都带 url（Crossref 的 URL 字段常缺），
         但只要有 DOI 就能构造出可点的 doi.org 链接 —— 否则这条结果
         在界面上就是个死条目，用户想去看原文却无处可点。 */
      const oa = _safeUrl(it.oa_url);
      const landing = _safeUrl(it.url);
      const doiLink = it.doi
        ? (/^https?:\/\//i.test(it.doi) ? it.doi : 'https://doi.org/' + it.doi)
        : '';
      const jump = oa || landing || _safeUrl(doiLink);
      const jumpLabel = oa ? 'OA 全文' : (landing ? '来源页' : 'DOI 页面');
      const titleHtml = jump
        ? '<a class="kb-web-title kb-web-title-link" href="' + esc(jump) + '" target="_blank" rel="noopener" ' +
          'title="在新标签页打开：' + esc(jump) + '">' + esc(it.title || '（无标题）') + '</a>'
        : '<div class="kb-web-title kb-web-title-dead" title="该条结果未提供任何可用链接">' +
          esc(it.title || '（无标题）') + '</div>';
      return '<div class="kb-web' + (picked ? ' picked' : '') + '" data-i="' + id + '">' +
        '<div class="kb-web-top">' +
          '<input class="kb-web-pick" type="checkbox"' + (picked ? ' checked' : '') + '>' +
          titleHtml +
        '</div>' +
        '<div class="kb-web-meta">' +
          '<span class="km-src">' + esc(it.source_label || it.source || '') + '</span>' +
          (it.year ? '<span>' + esc(it.year) + '</span>' : '') +
          (it.venue ? '<span title="' + esc(it.venue) + '">' + esc(String(it.venue).slice(0, 40)) + '</span>' : '') +
          (it.authors ? '<span title="' + esc(it.authors) + '">' + esc(String(it.authors).slice(0, 46)) + '</span>' : '') +
          (it.cited_by ? '<span>被引 ' + it.cited_by + '</span>' : '') +
        '</div>' +
        (abs ? '<div class="kb-web-abs">' + esc(String(abs).slice(0, 400)) + '</div>'
              : '<div class="kb-web-abs none">该源未返回摘要（OpenAlex/Crossref 对老文献与付费墙期刊常缺摘要，属正常）</div>') +
        '<div class="kb-web-acts">' +
          (jump ? '<a class="kb-web-act' + (oa ? ' oa' : '') + '" href="' + esc(jump) + '" target="_blank" rel="noopener"' +
            ' title="在新标签页打开' + (oa ? '（开放获取全文）' : '（出版商页面，可能需要机构订阅）') + '">' +
            jumpLabel + ' ↗</a>' : '<span class="kb-web-act dead">无可用链接</span>') +
          (it.doi && !oa ? '<button class="kb-web-act" data-oa="' + id + '" title="按 DOI 查询合法开放获取版本（Unpaywall）">找 OA 全文</button>' : '') +
          (it.doi ? '<button class="kb-web-act" data-cite="' + id + '" title="复制 BibTeX 引用，可直接粘进 LaTeX / Zotero">复制引用</button>' : '') +
          (doiLink ? '<button class="kb-web-act" data-copylink="' + id + '" title="复制 DOI 链接：' +
            esc(doiLink) + '">复制链接</button>' : '') +
        '</div>' +
        '</div>';
    }).join('');

  el.querySelectorAll('.kb-web').forEach(row => {
    const i = row.dataset.i;
    row.querySelector('.kb-web-pick').onchange = () => {
      const n = Number(i);
      if (row.querySelector('.kb-web-pick').checked) _picked.add(n);
      else _picked.delete(n);
      row.classList.toggle('picked', _picked.has(n));
      _syncPickBar();
    };
  });
  el.querySelectorAll('[data-oa]').forEach(b => {
    b.onclick = () => resolveOa(b, Number(b.dataset.oa));
  });
  el.querySelectorAll('[data-cite]').forEach(b => {
    b.onclick = () => copyCite(b, Number(b.dataset.cite));
  });
  el.querySelectorAll('[data-copylink]').forEach(b => {
    b.onclick = () => {
      const it = _webItems[Number(b.dataset.copylink)];
      if (!it) return;
      const raw = String(it.doi || '');
      const link = /^https?:\/\//i.test(raw) ? raw : 'https://doi.org/' + raw;
      const old = b.textContent;
      const ok = _copyText(link);
      b.textContent = ok ? '已复制 ✓' : '复制失败';
      if (!ok) {
        b.title = '请手动复制：' + link;
        console.log('[MatLens] DOI 链接：' + link);
      }
      setTimeout(() => { b.textContent = old; }, 1600);
    };
  });
}

/** 通用文本复制（clipboard + execCommand 降级）。 */
function _copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).catch(() => { /* 静默降级 */ });
      return true;
    }
  } catch (e) { /* 降级 */ }
  return _copyFallback(text);
}

/** 复制引用（BibTeX，便于直接粘进 LaTeX / Zotero）。 */
function copyCite(btn, idx) {
  const it = _webItems[idx];
  if (!it) return;
  const old = btn.textContent;
  const bib = buildCite(it);
  const ok = _copyText(bib);
  if (ok) {
    btn.textContent = '已复制 ✓';
  } else {
    // 最后兜底：放进 title 供手动复制，并在控制台留一份
    btn.textContent = '复制失败';
    btn.title = '请手动复制：' + bib;
    console.log('[MatLens] 引用信息（复制失败，手动取用）:\n' + bib);
  }
  setTimeout(() => { btn.textContent = old; }, ok ? 1600 : 2400);
}

/** execCommand 降级复制。返回是否成功。 */
function _copyFallback(text) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-999px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return !!ok;
  } catch (e) {
    return false;
  }
}

/** 生成 BibTeX（字段缺失时留空，不编造内容）。 */
function buildCite(it) {
  const key = (String(it.authors || it.title || 'ref')
    .split(/[,;]/)[0].trim().split(/\s+/).pop() || 'ref').replace(/[^A-Za-z]/g, '') || 'ref';
  const first = (it.authors || '').split(',')[0].trim();
  const year = String(it.year || '').slice(0, 4);
  const fields = [
    '  title = {' + String(it.title || '').replace(/[{}]/g, '') + '}',
    it.authors ? '  author = {' + String(it.authors).replace(/[{}]/g, '') + '}' : '',
    it.venue ? '  journal = {' + String(it.venue).replace(/[{}]/g, '') + '}' : '',
    year ? '  year = {' + year + '}' : '',
    it.doi ? '  doi = {' + String(it.doi).replace(/[{}]/g, '') + '}' : '',
    it.url ? '  url = {' + it.url + '}' : '',
  ].filter(Boolean);
  return '@article{' + key + year + ',\n' + fields.join(',\n') + '\n}';
}

function _syncPickBar() {
  const bar = $id('kb-importbar');
  if (!bar) return;
  const n = _picked.size;
  const target = $id('kb-import-target');
  if (target) target.textContent = S.kb ? (S.kb.display_name || S.kb.name) : '（未选择本地库）';
  const el = $id('kb-picked-n');
  if (el) el.textContent = n;
  if (bar) bar.style.display = n ? '' : 'none';
  const btn = $id('btn-kb-web-import');
  if (btn) btn.disabled = !n || !S.kb;
}

/** 按 DOI 查合法开放获取全文（Unpaywall）。 */
async function resolveOa(btn, idx) {
  const it = _webItems[idx];
  if (!it || !it.doi) return;
  const old = btn.textContent;
  btn.textContent = '查询中…';
  btn.disabled = true;
  try {
    const r = await jget('/api/kb/sources/oa?doi=' + encodeURIComponent(it.doi));
    const safe = _safeUrl(r && r.oa_url);
    if (r && r.is_oa && safe) {
      const a = document.createElement('a');
      a.className = 'kb-web-act oa';
      a.href = safe;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = 'OA 全文 · ' + (r.oa_status || '');
      btn.replaceWith(a);
    } else {
      btn.textContent = '无 OA 版本';
      btn.title = '该 DOI 没有合法开放获取的全文版本（' + (r && r.oa_status || 'closed') + '）';
    }
  } catch (e) {
    btn.textContent = old;
    btn.title = '查询失败：' + (e.message || e);
    toast('OA 查询失败：' + (e.message || e), 'err');
  } finally {
    if (btn.parentNode) { btn.disabled = false; }
  }
}

/** 把勾选的云端文献沉淀进本地知识库。 */
export async function webImport() {
  if (!S.kb) { toast('请先在左侧选择一个本地知识库'); switchKbMode('local'); return; }
  if (!_picked.size) return;
  const items = Array.from(_picked).map(i => _webItems[i]).filter(Boolean);
  if (!items.length) { toast('没有可导入的条目'); return; }
  toast('正在导入 ' + items.length + ' 篇到「' + (S.kb.display_name || S.kb.name) + '」…');
  try {
    const r = await jpost('/api/kb/' + encodeURIComponent(S.kb.name) + '/web-import', { items });
    if (r && r.ok !== false) {
      toast('已导入 ' + (r.imported || items.length) + ' 篇，' +
        ((r.added != null) ? ('新增索引 ' + r.added + ' 篇') : '') , 'ok');
      _picked.clear(); _syncPickBar();
      _webItems = []; _renderWebEmpty();
      await loadKb();                       // 刷新本地库计数
      if (S.kb) loadDocs(S.kb.name);
    } else {
      toast('导入失败：' + ((r && (r.error || r.detail)) || '未知错误'), 'err');
    }
  } catch (e) { toast('导入失败：' + (e.message || e), 'err'); }
}

export function clearPicked() {
  _picked.clear(); _syncPickBar(); _renderWebResults();
}

/* ══════════════════════════════════════════════════════════
 * 四、绑定（供 main.js 调用，避免污染主文件）
 * ══════════════════════════════════════════════════════════ */
export function bindKbCloud() {
  document.querySelectorAll('#page-kb .kb-mode').forEach(b =>
    b.addEventListener('click', () => switchKbMode(b.dataset.kbmode)));
  const ws = $id('btn-kb-web-search'); if (ws) ws.addEventListener('click', webSearch);
  const wq = $id('kb-web-query');
  if (wq) wq.addEventListener('keydown', e => { if (e.key === 'Enter') webSearch(); });
  const wi = $id('btn-kb-web-import'); if (wi) wi.addEventListener('click', webImport);
  const wc = $id('btn-kb-web-clear'); if (wc) wc.addEventListener('click', clearPicked);
}
