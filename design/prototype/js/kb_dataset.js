/* ═══════════════════════════════════════════════════════════════
 * MatLens 知识库页 · 开放数据集检索（2026-10-29）
 *
 * 为什么单独一栏：
 *   论文源（OpenAlex/Crossref/arxiv）只能找到**文献**。但材料实验的
 *   关键数据 —— SCAPS 模拟输出、DFT 结果、XRD 原始谱、电池循环数据 ——
 *   大量发布在公开数据集仓库（Zenodo 等），不在论文正文里。
 *
 * 与云端 API 栏的差异（这些差异必须在界面上讲清）：
 *   1. 只导入**元数据**（题名/描述/关键词/许可/文件清单），不下载文件
 *      —— 数据集动辄几百 MB，是否下载必须由用户显式决定。
 *   2. 每条要显示**许可证**与**文件体积** —— 用户要先判断能不能引用、
 *      大概要下多少，才好决定要不要沉淀。
 *   3. 没有「找 OA 全文」的概念（数据集没有全文版），改为「看文件清单」。
 * ═══════════════════════════════════════════════════════════════ */
import { $id, esc, toast, jget, jpost, S } from './core.js';

const MAX_DS = 40;
let _dsItems = [];
let _dsPicked = new Set();
let _dsSources = [];

function _safeUrl(u) {
  if (typeof u !== 'string') return '';
  const s = u.trim();
  if (!/^https?:\/\//i.test(s)) return '';
  try {
    const parsed = new URL(s);
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') ? s : '';
  } catch (e) {
    return '';
  }
}

/* ── 绑定 ────────────────────────────────────────────── */
export function bindDatasetPane() {
  const btn = $id('btn-kb-ds-search');
  if (btn) btn.onclick = () => doDatasetSearch();

  const inp = $id('kb-ds-query');
  if (inp) {
    inp.onkeydown = (e) => { if (e.key === 'Enter') doDatasetSearch(); };
  }

  const clr = $id('btn-kb-ds-clear');
  if (clr) clr.onclick = () => {
    _dsPicked.clear();
    _renderDatasetResults();
    _syncDsPickBar();
  };

  const imp = $id('btn-kb-ds-import');
  if (imp) imp.onclick = () => doDatasetImport();
}

/* ── 源目录 ──────────────────────────────────────────── */
export async function loadDatasetSources() {
  try {
    const r = await jget('/api/kb/datasets/sources');
    _dsSources = r.items || [];
    const n = $id('km-dataset-n');
    if (n) n.textContent = String(_dsSources.length);
    _renderDsSrcStat();
    // 若当前正处于数据集模式，左栏要换成数据集源目录
    if (_isDatasetMode()) renderDatasetSrcList();
  } catch (e) {
    _dsSources = [];
  }
}

function _isDatasetMode() {
  const b = document.querySelector('#page-kb .kb-mode.active');
  return !!b && b.dataset.kbmode === 'dataset';
}

function _renderDsSrcStat() {
  const el = $id('kb-ds-srcstat');
  if (!el) return;
  if (!_dsSources.length) { el.innerHTML = ''; return; }
  el.innerHTML = _dsSources.map(s => {
    const on = s.default_on;
    return '<span class="ks' + (on ? ' on' : '') + '" title="' + esc(s.note || '') + '">' +
      esc(s.label) +
      (on ? '' : '<em class="ks-off">默认关闭</em>') +
      '</span>';
  }).join('') +
  '<span class="ks-note">数据集仓库有公开 API 且多为开放许可（Zenodo 常为 CC-BY），' +
  '与知网/维普不同 —— 那两个无公开接口，只能官网检索后导出题录导入。</span>';
}

/** 左栏：数据集模式显示**数据集源**目录。
 *  否则左栏会沿用云端模式的学术 API 目录（OpenAlex/Crossref…），
 *  用户在「数据集」标签下却看到文献源 —— 完全是两回事。
 */
export function renderDatasetSrcList() {
  const el = $id('kb-list');
  if (!el) return;
  if (!_dsSources.length) {
    el.innerHTML = '<div class="kb-sec">开放数据集源</div>' +
      '<div class="kb-empty" style="padding:22px 10px">' +
      '<div class="kb-empty-t">加载中…</div></div>';
    return;
  }
  let h = '<div class="kb-sec">开放数据集源 · ' + _dsSources.length + '</div>';
  h += _dsSources.map(s => {
    const on = !!s.default_on;
    return '<div class="kb-src' + (on ? ' on' : ' off') + '" title="' + esc(s.note || '') + '">' +
      '<div class="kb-src-top">' +
        '<span class="kb-src-name">' + esc(s.label) + '</span>' +
      '</div>' +
      '<div class="kb-src-meta">' +
        '<span class="kb-tag">' + (s.kind === 'dataset' ? '数据集' : s.kind) + '</span>' +
        (s.needs_key ? '<span class="kb-tag key">需密钥</span>' : '') +
        '<span class="kb-tag ' + (on ? 'on' : 'off') + '">' + (on ? '已启用' : '未启用') + '</span>' +
      '</div>' +
      '<div class="kb-src-note">' + esc(s.note || '') + '</div>' +
      '</div>';
  }).join('');
  h += '<div class="kb-sec" style="margin-top:14px">本地知识库</div>';
  h += '<div class="kb-empty" style="padding:16px 10px">' +
    '<div class="kb-empty-h">切回「本地库」标签可管理与查看已建库。' +
    '导入数据集时需要先选中一个本地库。</div></div>';
  el.innerHTML = h;
}

/* ── 检索 ────────────────────────────────────────────── */
async function doDatasetSearch() {
  const q = ($id('kb-ds-query') || {}).value || '';
  const query = q.trim();
  if (!query) { toast('请输入检索词', 'err'); return; }

  const topk = parseInt((($id('kb-ds-topk') || {}).value) || '5', 10);
  const box = $id('kb-ds-results');
  if (box) box.innerHTML = '<div class="kb-empty"><div class="kb-empty-h">检索中…</div></div>';

  const btn = $id('btn-kb-ds-search');
  if (btn) { btn.disabled = true; btn.textContent = '检索中…'; }

  try {
    const r = await jpost('/api/kb/datasets/search', {
      query: query,
      per_source: topk,
    });
    _dsItems = (r.items || []).slice(0, MAX_DS);
    _dsPicked.clear();
    _renderDatasetResults();
    _syncDsPickBar();
    // 各源失败原因如实展示
    const ps = r.per_source || {};
    const stat = $id('kb-ds-srcstat');
    if (stat) {
      const bad = Object.keys(ps).filter(k => !ps[k].ok);
      if (bad.length) {
        stat.innerHTML += '<span class="ks-bad">失败：' +
          bad.map(k => esc(ps[k].label || k) + '（' + esc((ps[k].error || '').slice(0, 60)) + '）').join('；') +
          '</span>';
      }
    }
    if (!_dsItems.length) {
      const box2 = $id('kb-ds-results');
      if (box2) {
        box2.innerHTML = '<div class="kb-empty"><div class="kb-empty-t">没有命中有文件的数据集</div>' +
          '<div class="kb-empty-h">试试更具体的英文关键词（如 \"solid oxide cell microstructure\"），' +
          '或更短的词。Zenodo 上论文数量远多于数据集，系统已自动只保留带实际文件的记录。</div></div>';
      }
    }
  } catch (e) {
    const box2 = $id('kb-ds-results');
    if (box2) box2.innerHTML = '<div class="kb-empty"><div class="kb-empty-t">检索失败</div>' +
      '<div class="kb-empty-h">' + esc(e.message || e) + '</div></div>';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '检索数据集'; }
  }
}

/* ── 渲染结果 ────────────────────────────────────────── */
function _renderDatasetResults() {
  const el = $id('kb-ds-results');
  if (!el) return;
  if (!_dsItems.length) { el.innerHTML = ''; return; }

  const pickedN = _dsPicked.size;
  el.innerHTML = '<div class="kb-hit-note">共 ' + _dsItems.length +
    ' 个数据集 · 勾选后可把<b>元数据</b>（含文件清单与许可）沉淀进本地库</div>' +
    _dsItems.map((it, i) => {
      const picked = _dsPicked.has(i);
      const page = _safeUrl(it.landing_page) || _safeUrl(it.url);
      const doiLink = it.doi
        ? (/^https?:\/\//i.test(it.doi) ? it.doi : 'https://doi.org/' + it.doi) : '';
      const titleHtml = page
        ? '<a class="kb-web-title kb-web-title-link" href="' + esc(page) + '" target="_blank" rel="noopener" ' +
          'title="在新标签页打开数据集页面">' + esc(it.title || '（无标题）') + '</a>'
        : '<div class="kb-web-title kb-web-title-dead">' + esc(it.title || '（无标题）') + '</div>';

      const lic = it.license || '';
      const licCls = /cc0|public/i.test(lic) ? 'lic-open'
        : (/cc-by/i.test(lic) ? 'lic-by' : (lic ? 'lic-other' : 'lic-none'));

      const files = it.files || [];
      const fileBrief = files.length
        ? (files.length <= 2
            ? files.map(f => esc(f.key) + '（' + esc(f.size_human || '') + '）').join('、')
            : esc(files[0].key) + ' 等 ' + files.length + ' 个文件')
        : '';

      return '<div class="kb-web kb-ds' + (picked ? ' picked' : '') + '" data-i="' + i + '">' +
        '<div class="kb-web-top">' +
          '<input class="kb-web-pick" type="checkbox"' + (picked ? ' checked' : '') + '>' +
          titleHtml +
          (lic ? '<span class="kb-ds-lic ' + licCls + '" title="许可证：' + esc(lic) + '">' + esc(lic) + '</span>' : '') +
        '</div>' +
        '<div class="kb-web-meta">' +
          '<span class="km-src">' + esc(it.source || 'Zenodo') + '</span>' +
          (it.resource_label ? '<span>' + esc(it.resource_label) + '</span>' : '') +
          (it.year ? '<span>' + esc(it.year) + '</span>' : '') +
          (it.authors ? '<span title="' + esc(it.authors) + '">' + esc(String(it.authors).slice(0, 42)) + '</span>' : '') +
          (it.file_count ? '<span>' + it.file_count + ' 个文件 · ' + esc(it.total_size_human || '') + '</span>' : '') +
        '</div>' +
        (it.description
          ? '<div class="kb-web-abs">' + esc(String(it.description).slice(0, 320)) + '</div>'
          : '<div class="kb-web-abs none">该记录未提供描述</div>') +
        (fileBrief ? '<div class="kb-ds-files">' + fileBrief + '</div>' : '') +
        '<div class="kb-web-acts">' +
          (page ? '<a class="kb-web-act" href="' + esc(page) + '" target="_blank" rel="noopener" ' +
            'title="在新标签页打开数据集页面">数据集页面 ↗</a>' : '') +
          (doiLink ? '<a class="kb-web-act" href="' + esc(doiLink) + '" target="_blank" rel="noopener" ' +
            'title="DOI 页面：' + esc(doiLink) + '">DOI</a>' : '') +
          '<button class="kb-web-act" data-ds-files="' + i + '" title="查看完整文件清单与体积">文件清单</button>' +
          (doiLink ? '<button class="kb-web-act" data-ds-copy="' + i + '" title="复制数据集的 BibTeX 引用">复制引用</button>' : '') +
        '</div>' +
        '</div>';
    }).join('');

  el.querySelectorAll('.kb-web').forEach(row => {
    const i = row.dataset.i;
    const cb = row.querySelector('.kb-web-pick');
    if (cb) {
      cb.onchange = () => {
        const n = Number(i);
        if (cb.checked) _dsPicked.add(n); else _dsPicked.delete(n);
        row.classList.toggle('picked', _dsPicked.has(n));
        _syncDsPickBar();
      };
    }
  });
  el.querySelectorAll('[data-ds-files]').forEach(b => {
    b.onclick = () => showDsFiles(b, Number(b.dataset.dsFiles));
  });
  el.querySelectorAll('[data-ds-copy]').forEach(b => {
    b.onclick = () => copyDsCite(b, Number(b.dataset.dsCopy));
  });
}

function _syncDsPickBar() {
  const bar = $id('kb-ds-importbar');
  if (!bar) return;
  const n = _dsPicked.size;
  bar.style.display = n ? '' : 'none';
  const el = $id('kb-ds-picked-n');
  if (el) el.textContent = String(n);
  const tgt = $id('kb-ds-target');
  if (tgt) {
    const kb = S.kb || null;
    tgt.textContent = (kb && (kb.display_name || kb.name)) || '未选择知识库';
  }
  const btn = $id('btn-kb-ds-import');
  if (btn) btn.disabled = !(S.kb && S.kb.name);
}

/* ── 文件清单 ────────────────────────────────────────── */
async function showDsFiles(btn, i) {
  const it = _dsItems[i];
  if (!it) return;
  const old = btn.textContent;
  btn.textContent = '读取中…';
  try {
    const r = await jget('/api/kb/datasets/' + encodeURIComponent(it.id) + '/files');
    const files = r.files || [];
    const lines = files.length
      ? files.map(f => '<div class="kb-ds-file"><span class="kb-ds-fk">' + esc(f.key) + '</span>' +
        '<span class="kb-ds-fs">' + esc(f.size_human || '') + '</span>' +
        (f.url ? '<a class="kb-ds-fu" href="' + esc(f.url) + '" target="_blank" rel="noopener">下载 ↗</a>' : '') +
        '</div>').join('')
      : '<div class="kb-ds-file">（无文件）</div>';
    _dsOverlay('数据集文件清单', '<div class="kb-ds-fmeta">' +
      esc(r.title || it.title) +
      (r.license ? ' · 许可 ' + esc(r.license) : '') +
      ' · ' + files.length + ' 个文件 · 共 ' + esc(r.total_size_human || '') +
      '</div><div class="kb-ds-flist">' + lines + '</div>' +
      '<div class="kb-ds-fnote">MatLens <b>不会自动下载</b>这些文件 —— 数据集动辄上百 MB，' +
      '请确认需要哪些再自行下载；下载后走「添加文献」上传通道即可被检索。</div>');
  } catch (e) {
    toast('读取文件清单失败：' + (e.message || e), 'err');
  } finally {
    btn.textContent = old;
  }
}

function _dsOverlay(title, html) {
  let ov = $id('kb-ds-overlay');
  if (!ov) {
    ov = document.createElement('div');
    ov.id = 'kb-ds-overlay';
    ov.className = 'kb-ds-overlay';
    ov.innerHTML = '<div class="kb-ds-ovbox"><div class="kb-ds-ovhead"><b></b>' +
      '<button class="kb-ds-ovx" title="关闭">✕</button></div><div class="kb-ds-ovbody"></div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('click', (e) => { if (e.target === ov) ov.remove(); });
    ov.querySelector('.kb-ds-ovx').onclick = () => ov.remove();
  }
  ov.querySelector('.kb-ds-ovhead b').textContent = title;
  ov.querySelector('.kb-ds-ovbody').innerHTML = html;
  ov.style.display = 'flex';
}

/* ── 复制引用 ────────────────────────────────────────── */
function copyDsCite(btn, i) {
  const it = _dsItems[i];
  if (!it) return;
  const key = 'zenodo:' + (it.id || '');
  const tex = `@dataset{${key.replace(/[^A-Za-z0-9:_]/g, '_')},
  title   = {${it.title || ''}},
  author  = {${(it.authors || '').split(',')[0] || ''}},
  year    = {${it.year || ''}},
  doi     = {${it.doi || ''}},
  url     = {${it.landing_page || it.url || ''}},
  note    = {${it.license || ''}}
}`;
  const done = () => toast('已复制 BibTeX 引用（可粘进 LaTeX / Zotero）', 'ok');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(tex).then(done).catch(() => fallbackCopy(tex, done));
  } else {
    fallbackCopy(tex, done);
  }
}

function fallbackCopy(text, cb) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); cb(); }
  catch (e) { toast('复制失败，请手动选择', 'err'); }
  ta.remove();
}

/* ── 导入 ────────────────────────────────────────────── */
async function doDatasetImport() {
  if (!_dsPicked.size) { toast('请先勾选要导入的数据集', 'err'); return; }
  const kb = S.kb || null;
  if (!kb || !kb.name) { toast('请先在左侧选择一个本地知识库', 'err'); return; }

  const items = Array.from(_dsPicked).map(i => _dsItems[i]).filter(Boolean);
  const btn = $id('btn-kb-ds-import');
  if (btn) { btn.disabled = true; btn.textContent = '导入中…'; }
  try {
    const r = await jpost('/api/kb/datasets/import', { name: kb.name, items: items });
    toast('已导入 ' + (r.imported || 0) + ' 个数据集的元数据（含文件清单与许可）', 'ok');
    _dsPicked.clear();
    _renderDatasetResults();
    _syncDsPickBar();
    // 刷新本地库统计
    try {
      const mod = await import('./kb.js');
      if (mod.loadKb) await mod.loadKb();
    } catch (e) { /* 忽略 */ }
  } catch (e) {
    toast('导入失败：' + (e.message || e), 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '导入本地知识库'; }
  }
}
