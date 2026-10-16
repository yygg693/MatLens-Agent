/* ═══════════════════════════════════════════════════════════════
 * MatLens 知识库页 · 题录导入（2026-10-16）
 *
 * 背景：知网无公开 API（服务条款禁止自动化抓取），官网人工检索 →
 *       导出题录 → 本地导入是**中文文献唯一合规入口**。此模块把
 *       后端已就绪的解析能力接到界面上。
 *
 * 设计要点：
 *  1. **先预览再入库**。题录解析可能因格式识别错误而全错，用户
 *     不该等到入库后才发现。解析完先展示条目，确认无误再导入。
 *  2. **说清题录 ≠ 正文**。导入的是元数据，界面上必须讲明白，
 *     否则用户会以为「导了就能读全文」。
 *  3. **失败原因逐条展示**。哪些条目没 DOI、哪些被跳过（重复），
 *     都要让用户看见，而不是只给一个数字。
 * ═══════════════════════════════════════════════════════════════ */
import { $id, esc, toast, jpost, S } from './core.js';

const MAX_PREVIEW = 60;      // 预览最多展示多少条（再多界面也没法看）
let _citeState = null;       // {text, filename, items, format}

const FORMAT_LABEL = {
  refworks: 'RefWorks（知网/万方）',
  endnote: 'EndNote',
  ris: 'RIS',
  bibtex: 'BibTeX',
  auto: '自动识别',
  file: '题录文件',
  unknown: '未知格式',
};

/* ── 绑定 ────────────────────────────────────────────── */
export function bindCiteImport() {
  const drop = $id('cite-drop');
  const file = $id('cite-file');
  if (!drop || !file) return;

  drop.onclick = () => file.click();
  file.onchange = () => {
    if (file.files && file.files.length) _readFiles(file.files);
    file.value = '';
  };

  // 拖拽
  ['dragenter', 'dragover'].forEach(ev =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add('over');
    }));
  ['dragleave', 'drop'].forEach(ev =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove('over');
    }));
  drop.addEventListener('drop', (e) => {
    const fs = e.dataTransfer && e.dataTransfer.files;
    if (fs && fs.length) _readFiles(fs);
  });
}

/** 读取题录文件内容并预览解析结果。
 *  题录文件通常很小（几 KB），直接读全文传后端最简单可靠；
 *  大于 2MB 的一律拒绝 —— 那不是题录文件，很可能是误拖了 PDF。
 */
async function _readFiles(fileList) {
  const files = Array.from(fileList);
  if (!files.length) return;

  const merged = [];
  const tooBig = [];
  for (const f of files) {
    if (f.size > 2 * 1024 * 1024) {
      tooBig.push(`${f.name}（${(f.size / 1048576).toFixed(1)}MB）`);
      continue;
    }
    try {
      merged.push({ name: f.name, text: await _readText(f) });
    } catch (e) {
      toast(`读取 ${f.name} 失败：${e.message || e}`, 'err');
    }
  }

  if (tooBig.length) {
    toast('以下文件过大，已跳过（题录文件通常 < 2MB）：' + tooBig.join('、'), 'err');
  }
  if (!merged.length) return;

  // 多文件时按名称拼接：各格式都以新记录起始，拼接后仍能正确切分
  const text = merged.map(x => x.text).join('\n');
  const filename = merged.length === 1 ? merged[0].name : `${merged.length} 个文件`;
  await _preview(text, filename);
}

function _readText(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error('读取失败'));
    fr.onload = () => {
      // 题录导出常见 GB18030（知网 Windows 版），UTF-8 失败则退中文编码
      try {
        resolve(new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(fr.result)));
      } catch (e) {
        try {
          resolve(new TextDecoder('gb18030').decode(new Uint8Array(fr.result)));
        } catch (e2) {
          resolve(String(fr.result || ''));
        }
      }
    };
    fr.readAsArrayBuffer(file);
  });
}

/* ── 预览 ────────────────────────────────────────────── */
async function _preview(text, filename) {
  const box = $id('cite-preview');
  if (!box) return;
  box.style.display = '';
  box.innerHTML = '<div class="cite-pv-msg">解析中…</div>';

  let r;
  try {
    r = await jpost('/api/kb/citations/preview', { text, filename });
  } catch (e) {
    box.innerHTML = '<div class="cite-pv-msg" style="color:var(--ml-danger)">解析失败：' +
      esc(e.message || e) + '</div>';
    return;
  }

  const items = r.items || [];
  _citeState = { text, filename, items, format: r.format };

  if (!items.length) {
    box.innerHTML = '<div class="cite-pv-msg">' +
      '未能从该文件解析出题录。<br>' +
      '请确认是从知网 / 万方 / PubMed 用「导出题录」得到的文件，' +
      '且内容形如 <code>%T 标题</code>（RefWorks）或 <code>TI  - 标题</code>（RIS）。</div>';
    return;
  }

  const fmt = FORMAT_LABEL[r.format] || r.format;
  const withDoi = items.filter(x => x.doi).length;
  const shown = items.slice(0, MAX_PREVIEW);
  const noDoi = items.filter(x => !x.doi).length;
  const kbName = (S.kb && (S.kb.display_name || S.kb.name)) || '未选择';

  box.innerHTML =
    '<div class="cite-pv-head">' +
      '<span class="cv-fmt">' + esc(fmt) + '</span>' +
      '<span class="cv-n">解析出 <b>' + items.length + '</b> 条</span>' +
      '<span class="cv-n">带 DOI <b>' + withDoi + '</b> 条</span>' +
      (noDoi ? '<span class="cv-n">无 DOI <b>' + noDoi + '</b> 条</span>' : '') +
      '<span class="cv-n">目标库 <b>' + esc(kbName) + '</b></span>' +
    '</div>' +
    '<div class="cite-pv-list">' +
      shown.map((it, i) =>
        '<div class="cite-pv-item">' +
          '<span class="cite-pv-i">' + (i + 1) + '</span>' +
          '<div class="cite-pv-main">' +
            '<div class="cite-pv-t">' + esc(it.title || '（无题名）') + '</div>' +
            '<div class="cite-pv-m">' +
              esc([it.authors && it.authors.slice(0, 3).join('、'),
                it.journal || it.booktitle, it.year].filter(Boolean).join(' · ')) +
              (it.doi ? ' <span class="cv-doi">' + esc(it.doi) + '</span>'
                      : ' <span class="cv-nodoi">无 DOI</span>') +
            '</div>' +
          '</div>' +
        '</div>').join('') +
    '</div>' +
    (items.length > shown.length
      ? '<div class="cite-more">还有 ' + (items.length - shown.length) + ' 条未展示，导入时全部包含</div>'
      : '') +
    '<div class="cite-pv-acts">' +
      '<button class="btn btn-primary btn-sm" id="cite-do-import">确认导入 ' + items.length + ' 条</button>' +
      '<button class="btn btn-ghost btn-sm" id="cite-cancel">取消</button>' +
    '</div>';

  const doBtn = $id('cite-do-import');
  if (doBtn) doBtn.onclick = () => _doImport();
  const cBtn = $id('cite-cancel');
  if (cBtn) cBtn.onclick = () => _clear();
}

async function _doImport() {
  if (!_citeState || !_citeState.items.length) return;
  if (!S.kb || !S.kb.name) {
    toast('请先在左侧选择一个知识库', 'err');
    return;
  }
  const btn = $id('cite-do-import');
  if (btn) { btn.disabled = true; btn.textContent = '导入中…'; }
  try {
    const r = await jpost(
      '/api/kb/' + encodeURIComponent(S.kb.name) + '/import-citations',
      { text: _citeState.text, filename: _citeState.filename });
    const dup = r.duplicates || 0;
    // ⚠️ add_documents 返回 {items:[{doc_id, chunks, skipped, source, reason}]}，
    // **没有顶层 chunks 字段**（早期误读成 r.chunks，提示成「索引 0 个分块」）。
    // ⚠️ ``imported`` 是「写盘条数」，不等于「真正新建索引条数」——
    //    重复文献会被底层按文件名跳过（items[].skipped=True）。
    //    所以成功数要自己数，否则会对着 0 条说「已导入 N 条」。
    const items = Array.isArray(r.items) ? r.items : [];
    const added = items.filter(x => !x.skipped).length;
    const skipped = items.filter(x => x.skipped);
    const chunks = items.reduce((a, x) => a + (x.chunks || 0), 0);

    let msg;
    if (added === 0) {
      msg = `全部 ${items.length} 条都已在此库中，未新增` +
        (dup ? `（题录内去重 ${dup} 条）` : '');
    } else {
      msg = `新增 ${added} 条题录` +
        (dup ? `（题录内去重 ${dup} 条）` : '') +
        (chunks ? `，索引 ${chunks} 个分块` : '');
      if (skipped.length) msg += `；${skipped.length} 条此前已导入`;
    }
    toast(msg, added === 0 ? 'err' : (skipped.length ? 'err' : 'ok'));
    _clear();
    switchKbTabSafe('docs');
    // 刷新文献列表与计数
    try {
      const mod = await import('./kb.js');
      if (mod.loadKb) await mod.loadKb();
    } catch (e) { /* 模块已加载过则忽略 */ }
  } catch (e) {
    toast('导入失败：' + (e.message || e), 'err');
    if (btn) { btn.disabled = false; btn.textContent = '重试导入'; }
  }
}

function _clear() {
  _citeState = null;
  const box = $id('cite-preview');
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
}

function switchKbTabSafe(tab) {
  const t = document.querySelector('#page-kb .kb-tab[data-kbtab="' + tab + '"]');
  if (t) t.click();
}