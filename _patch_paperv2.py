# -*- coding: utf-8 -*-
"""论文工坊前端补丁 v2（app.js）：双模式 / 删除按钮 / 导出闭环。幂等。"""
import io

p = r"D:\MatLens\design\prototype\app.js"
s = io.open(p, encoding="utf-8").read()
orig = s

# A) 模块级状态：_paperMode + pError（修复 handlePaperEvent 引用局部 pError 的隐患）
old_a = "  let _paperAbort = null;\n  async function runPaperStep(stage) {"
new_a = "  let _paperAbort = null;\n  let _paperMode = 'view'; // 论文内容区：view(Markdown 渲染) | edit(textarea)\n  let pError = ''; // 当前步骤生成错误（模块级，handlePaperEvent 与 runPaperStep 共享）\n  async function runPaperStep(stage) {"
assert old_a in s, "anchor A missing"
s = s.replace(old_a, new_a, 1)

# B) runPaperStep 局部声明改赋值
old_b = "    let pError = '';\n    let cancelled = false;"
new_b = "    pError = '';\n    let cancelled = false;"
assert old_b in s, "anchor B missing"
s = s.replace(old_b, new_b, 1)

# C) runPaperStep 完成：切回查看模式
old_c = """    // 完成刷新
    await selectPaper(curPaper.id);
    if (curStage === stage) renderPaperPanel();
    if (pError) toast('「' + PAPER_LABELS[stage] + '」失败：' + pError, 'err');
    else if (!cancelled) toast(stage === 'export' ? '导出完成' : '「' + PAPER_LABELS[stage] + '」已完成', 'ok');
  }"""
new_c = """    // 完成刷新
    if (!cancelled && !pError) _paperMode = 'view';
    await selectPaper(curPaper.id);
    if (curStage === stage) renderPaperPanel();
    if (pError) toast('「' + PAPER_LABELS[stage] + '」失败：' + pError, 'err');
    else if (!cancelled) toast(stage === 'export' ? '导出完成' : '「' + PAPER_LABELS[stage] + '」已完成', 'ok');
  }"""
assert old_c in s, "anchor C missing"
s = s.replace(old_c, new_c, 1)

# D) togglePaperMode + delPaper（放 cancelPaperRun 后）
old_d = """  async function cancelPaperRun() {
    const btn = $id('btn-p-cancel');
    if (btn) btn.disabled = true;
    if (_paperAbort) _paperAbort.abort();
  }
  window.cancelPaperRun = cancelPaperRun;"""
new_d = """  async function cancelPaperRun() {
    const btn = $id('btn-p-cancel');
    if (btn) btn.disabled = true;
    if (_paperAbort) _paperAbort.abort();
  }
  window.cancelPaperRun = cancelPaperRun;

  function togglePaperMode() {
    _paperMode = _paperMode === 'edit' ? 'view' : 'edit';
    renderPaperPanel();
  }
  window.togglePaperMode = togglePaperMode;

  async function delPaper(id, title) {
    if (!confirm('删除课题「' + (title || '') + '」？\\n该操作不可恢复，将同时删除全部 7 步产物。')) return;
    const d = await jpost('/api/papers/' + id + '/delete', {});
    if (!d || !d.ok) { toast('删除失败', 'err'); return; }
    if (curPaper && curPaper.id === id) { curPaper = null; curStage = 'topic'; renderPaperPanel(); }
    loadPapers();
    toast('课题已删除', 'ok');
  }
  window.delPaper = delPaper;"""
assert old_d in s, "anchor D missing"
s = s.replace(old_d, new_d, 1)

# E) selectPaper 重置 view
old_e = """    curPaper = d;
    curStage = firstPendingStage(d.stages) || 'export';
    renderPaperSteps();"""
new_e = """    curPaper = d;
    curStage = firstPendingStage(d.stages) || 'export';
    _paperMode = 'view';
    renderPaperSteps();"""
assert old_e in s, "anchor E missing"
s = s.replace(old_e, new_e, 1)

# F) renderPaperPanel：查看/编辑切换按钮 + p-view
old_f = """        <div style="display:flex;gap:8px">
          <button class="btn btn-ghost btn-sm" onclick="savePaperStep()">保存编辑</button>
          ${!isLast ? `<button class="btn btn-primary btn-sm" onclick="runPaperStep('${curStage}')" id="btn-p-run" ${prevDone ? '' : 'disabled title="先完成上一步"'} style="${prevDone ? '' : 'opacity:.45;cursor:not-allowed'}">${prevDone ? (status === 'done' ? '重新生成' : '▶ 生成') : '⚠ 先完成上一步'}</button>` : ''}
          <button class="btn btn-ghost btn-sm" id="btn-p-cancel" style="display:none" onclick="cancelPaperRun()">停止</button>
          ${['write','quality','review','export'].includes(curStage) ? `<select class="btn btn-ghost btn-sm" style="appearance:none;cursor:pointer" onchange="exportPaper(this.value);this.value=''">
            <option value="">导出成稿 ▾</option>
            <option value="md">Markdown (.md)</option>
            <option value="tex">LaTeX (.tex)</option>
            <option value="docx">Word (.docx)</option>
          </select>` : ''}
        </div>"""
new_f = """        <div style="display:flex;gap:8px">
          ${content ? `<button class="btn btn-ghost btn-sm" onclick="togglePaperMode()">${_paperMode === 'edit' ? '👁 查看' : '✎ 编辑'}</button>` : ''}
          <button class="btn btn-ghost btn-sm" onclick="savePaperStep()">保存编辑</button>
          ${!isLast ? `<button class="btn btn-primary btn-sm" onclick="runPaperStep('${curStage}')" id="btn-p-run" ${prevDone ? '' : 'disabled title="先完成上一步"'} style="${prevDone ? '' : 'opacity:.45;cursor:not-allowed'}">${prevDone ? (status === 'done' ? '重新生成' : '▶ 生成') : '⚠ 先完成上一步'}</button>` : ''}
          <button class="btn btn-ghost btn-sm" id="btn-p-cancel" style="display:none" onclick="cancelPaperRun()">停止</button>
          ${['write','quality','review','export'].includes(curStage) ? `<select class="btn btn-ghost btn-sm" style="appearance:none;cursor:pointer" onchange="exportPaper(this.value);this.value=''">
            <option value="">导出成稿 ▾</option>
            <option value="md">Markdown (.md)</option>
            <option value="tex">LaTeX (.tex)</option>
            <option value="docx">Word (.docx)</option>
          </select>` : ''}
        </div>"""
assert old_f in s, "anchor F missing"
s = s.replace(old_f, new_f, 1)

# G) renderPaperPanel：内容区双模式
old_g = """      <div style="flex:1;min-height:0;display:flex;flex-direction:column">
        <div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:6px" id="p-gen-label"></div>
        <div id="p-stream" style="display:none;font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--ml-text);max-height:45%;overflow-y:auto;background:rgba(255,255,255,.03);border:1px solid var(--ml-card-border);border-radius:10px;padding:12px;margin-bottom:10px"></div>
        <textarea id="p-editor" spellcheck="false" style="flex:1;min-height:200px;background:transparent;border:1px solid var(--ml-card-border);border-radius:10px;padding:13px;color:var(--ml-text);font:13px/1.7 Consolas,Menlo,monospace;resize:none;outline:none">${esc(content)}</textarea>
      </div>`;"""
new_g = """      <div style="flex:1;min-height:0;display:flex;flex-direction:column">
        <div style="font-size:12px;color:var(--ml-text-faint);margin-bottom:6px" id="p-gen-label"></div>
        <div id="p-stream" style="display:none;font-size:13px;line-height:1.7;white-space:pre-wrap;color:var(--ml-text);max-height:45%;overflow-y:auto;background:rgba(255,255,255,.03);border:1px solid var(--ml-card-border);border-radius:10px;padding:12px;margin-bottom:10px"></div>
        <div id="p-view" style="${_paperMode === 'edit' ? 'display:none' : ''};flex:1;min-height:200px;overflow-y:auto;border:1px solid var(--ml-card-border);border-radius:10px;padding:13px;color:var(--ml-text);font-size:13px;line-height:1.75;background:var(--ml-input-bg)">${content ? renderMarkdown(content) : '<span style="color:var(--ml-text-faint)">（该步骤暂无内容，点击「▶ 生成」或「保存编辑」开始）</span>'}</div>
        <textarea id="p-editor" spellcheck="false" style="${_paperMode === 'edit' ? '' : 'display:none'};flex:1;min-height:200px;background:transparent;border:1px solid var(--ml-card-border);border-radius:10px;padding:13px;color:var(--ml-text);font:13px/1.7 Consolas,Menlo,monospace;resize:none;outline:none">${esc(content)}</textarea>
      </div>`;"""
assert old_g in s, "anchor G missing"
s = s.replace(old_g, new_g, 1)

# H) savePaperStep：保存后回查看
old_h = """  async function savePaperStep() {
    if (!curPaper) return;
    const content = $id('p-editor') ? $id('p-editor').value : '';
    const d = await jpost('/api/papers/' + curPaper.id + '/save', { stage: curStage, content: content });
    if (d && d.ok) { toast('已保存「' + PAPER_LABELS[curStage] + '」', 'ok'); selectPaper(curPaper.id); }
    else toast('保存失败');
  }"""
new_h = """  async function savePaperStep() {
    if (!curPaper) return;
    const content = $id('p-editor') ? $id('p-editor').value : '';
    const d = await jpost('/api/papers/' + curPaper.id + '/save', { stage: curStage, content: content });
    if (d && d.ok) {
      _paperMode = 'view';
      toast('已保存「' + PAPER_LABELS[curStage] + '」', 'ok');
      selectPaper(curPaper.id);
    }
    else toast('保存失败');
  }"""
assert old_h in s, "anchor H missing"
s = s.replace(old_h, new_h, 1)

# I) loadPapers：列表加删除按钮
old_i = """    el.innerHTML = d.papers.map(p => {
      const act = curPaper && p.id === curPaper.id ? 'active' : '';
      return `<div class="kb-item ${act}" style="cursor:pointer" onclick="selectPaper('${p.id}')">
        <div class="k-name" style="font-size:12.5px">${esc(p.title).slice(0, 18)}</div>
        <div class="k-meta"><span>${p.progress.pct}%</span><span>${PAPER_LABELS[lastDoneStage(p.stages)] || ''}</span></div>
      </div>`;
    }).join('');"""
new_i = """    el.innerHTML = d.papers.map(p => {
      const act = curPaper && p.id === curPaper.id ? 'active' : '';
      return `<div class="kb-item ${act}" style="cursor:pointer;position:relative" onclick="selectPaper('${p.id}')">
        <div class="k-name" style="font-size:12.5px;padding-right:18px">${esc(p.title).slice(0, 18)}</div>
        <div class="k-meta"><span>${p.progress.pct}%</span><span>${PAPER_LABELS[lastDoneStage(p.stages)] || ''}</span></div>
        <span title="删除课题" style="position:absolute;top:6px;right:10px;font-size:12px;opacity:.45;cursor:pointer;color:var(--ml-text-faint)" onmouseover="this.style.opacity=1;this.style.color='var(--ml-danger)'" onmouseout="this.style.opacity=.45;this.style.color='var(--ml-text-faint)'" onclick="event.stopPropagation();delPaper('${p.id}','${esc(p.title).replace(/'/g, "\\\\'")}')">✕</span>
      </div>`;
    }).join('');"""
assert old_i in s, "anchor I missing"
s = s.replace(old_i, new_i, 1)

# J) exportPaper：成功后把 export 步标 done（7 步闭环）
old_j = """      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast('已导出：' + fname, 'ok');"""
new_j = """      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      // 导出成功 → 自动把 export 步标记完成（7 步闭环全绿）
      try {
        await jpost('/api/papers/' + curPaper.id + '/save', { stage: 'export', content: '已导出成稿：' + fname });
        await selectPaper(curPaper.id);
      } catch (_) { /* 标记失败不影响下载 */ }
      toast('已导出：' + fname, 'ok');"""
assert old_j in s, "anchor J missing"
s = s.replace(old_j, new_j, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("app.js patch v2 applied, changed:", orig != s)
