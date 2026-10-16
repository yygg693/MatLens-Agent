# -*- coding: utf-8 -*-
"""论文工坊前端修复（app.js）：前置禁用按钮 / 错误 toast / quality 文案。幂等。"""
import io

p = r"D:\MatLens\design\prototype\app.js"
s = io.open(p, encoding="utf-8").read()
orig = s

# 1) 前置未完成：按钮禁用 + 文案提示
old1 = """${!isLast ? `<button class="btn btn-primary btn-sm" onclick="runPaperStep('${curStage}')" id="btn-p-run">${prevDone ? (status === 'done' ? '重新生成' : '▶ 生成') : '生成'}</button>` : ''}"""
new1 = """${!isLast ? `<button class="btn btn-primary btn-sm" onclick="runPaperStep('${curStage}')" id="btn-p-run" ${prevDone ? '' : 'disabled title="先完成上一步"'} style="${prevDone ? '' : 'opacity:.45;cursor:not-allowed'}">${prevDone ? (status === 'done' ? '重新生成' : '▶ 生成') : '⚠ 先完成上一步'}</button>` : ''}"""
assert old1 in s, "anchor1 missing"
s = s.replace(old1, new1, 1)

# 2) runPaperStep：quality 文案 + 错误跟踪 + 正确 toast
old2 = """    $id('p-gen-label').textContent = '● 正在生成（AI 流式输出）…';"""
new2 = """    $id('p-gen-label').textContent = stage === 'quality' ? '● 本地规则巡检中…' : '● 正在生成（AI 流式输出）…';
    let pError = '';"""
assert old2 in s, "anchor2 missing"
s = s.replace(old2, new2, 1)

# 3) handlePaperEvent 记录错误
old3 = """      case 'stage_error': {
        $id('p-gen-label').textContent = '✕ ' + ((d.data && d.data.message) || '生成失败');
        break;
      }
      case 'error': {
        $id('p-gen-label').textContent = '✕ ' + ((d.data && d.data.message) || '未知错误');
        break;
      }
      case 'done': {
        const r = d.data || {};
        if (!r.ok) { $id('p-gen-label').textContent = '✕ ' + (r.error || '前置未完成'); }
        else { $id('p-gen-label').textContent = '✓ 生成完成'; }
        break;
      }"""
new3 = """      case 'stage_error': {
        pError = (d.data && d.data.message) || '生成失败';
        $id('p-gen-label').textContent = '✕ ' + pError;
        break;
      }
      case 'error': {
        pError = (d.data && d.data.message) || '未知错误';
        $id('p-gen-label').textContent = '✕ ' + pError;
        break;
      }
      case 'done': {
        const r = d.data || {};
        if (!r.ok) { pError = r.error || '前置未完成'; $id('p-gen-label').textContent = '✕ ' + pError; }
        else { $id('p-gen-label').textContent = '✓ 生成完成'; }
        break;
      }"""
assert old3 in s, "anchor3 missing"
s = s.replace(old3, new3, 1)

# 4) 完成 toast 按错误区分
old4 = """    await selectPaper(curPaper.id);
    if (curStage === stage) renderPaperPanel();
    toast(stage === 'export' ? '导出完成' : '「' + PAPER_LABELS[stage] + '」已完成', 'ok');"""
new4 = """    await selectPaper(curPaper.id);
    if (curStage === stage) renderPaperPanel();
    if (pError) toast('「' + PAPER_LABELS[stage] + '」失败：' + pError, 'err');
    else toast(stage === 'export' ? '导出完成' : '「' + PAPER_LABELS[stage] + '」已完成', 'ok');"""
assert old4 in s, "anchor4 missing"
s = s.replace(old4, new4, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("app.js paper patches applied, changed:", orig != s)
