/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · main.js（ESM 入口：组装各模块、绑定事件、暴露 window）
 * 由 index.html 的 <script type="module" src="/js/main.js"> 加载
 * ═══════════════════════════════════════════════════════════════ */
import {
  esc, $id, toast, jget, jpost, S, psCard,
  initErrorBoundary, initResponsiveDrawer, exposeGlobals,
} from './core.js';
import {
  setBusy, initInputTools,
  _hideToolPicker, _handleAtInput, _bindChatGlobals, _toolPickerKey,
} from './chat.js';
// 2026-10-15 拆分：SSE 主循环已移至 chat_sse.js
import { sendMsg, stop } from './chat_sse.js';
// 2026-10-15 拆分：面板类从 chat.js 移至 chat_panels.js（chat.js 1190→895 行）
import {
  bindChipPanels, loadModelChip, loadContextChip, loadApprovalChip,
  loadWsChip, renderWsPanel, _bindChatGlobals2,
} from './chat_panels.js';
// 2026-10-15 拆分：执行日志侧栏随工具卡一并移出
import { openExecLog, closeExecLog } from './chat_toolcards.js';
import {
  loadSessions, selectSession, newSession, renameSession, deleteSession, loadMessages,
  archiveSession,
} from './sessions.js';
import {
  loadKb, switchKb, loadDocs, createKb, pickUpload, queryKb,
  switchKbTab, filterDocs, importByPaths, closeDocReader,
  loadSources, bindKbCloud,
} from './kb.js';
import { loadTools, openToolCatalog, closeToolCatalog, bindToolsPage } from './tools.js';
import { bindCiteImport } from './kb_cite.js';
import { bindDatasetPane, loadDatasetSources } from './kb_dataset.js';
import { initChatUI, renderEmptyState } from './chat_ui.js';
// 2026-10-15 重做：右栏四panel 全部接真实数据（原三块是死占位）
import { initRightPanel, switchRightTab, refreshRightPanel } from './chat_right.js';
import {
  loadPapers, selectPaper, viewStage, runPaperStep, savePaperStep, exportPaper,
  cancelPaperRun, delPaper, toKb, fillPaperProgress, bindPaperUI, renderPaperPanel,
  createPaper,
} from './paper.js';
import { loadMemory, loadGraph, loadMemories, bindMemoryUI } from './graph.js';
import { loadSettings, saveSettings, testConnection, refreshModels } from './settings.js';
import {
  loadExpTemplates, selectExpTpl, generateExp, saveExpRecord,
  viewExpRecord, delExpRecord, loadExpRecords, initViz,
} from './exp.js';

/* ── 右侧辅助栏填充 ────────────────────────────────────── */
function fillSidePanels() {
  const kbSide = $id('kb-side');
  if (kbSide) {
    jget('/api/kb').then(d => {
      const kbs = (d && d.kbs) || [];
      const totalDocs = kbs.reduce((a, k) => a + (k.docs || 0), 0);
      const totalChunks = kbs.reduce((a, k) => a + (k.chunks || 0), 0);
      kbSide.innerHTML =
        psCard('知识库统计', 'M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z',
          '<div class="ps-stat"><span>知识库总数</span><b>' + kbs.length + '</b></div>' +
          '<div class="ps-stat"><span>文献总数</span><b>' + totalDocs + '</b></div>' +
          '<div class="ps-stat"><span>分块总数</span><b>' + totalChunks + '</b></div>' +
          '<div class="ps-stat"><span>激活库</span><b style="font-size:11px">' + esc((d && d.active) || '—') + '</b></div>') +
        psCard('快捷操作', 'M12 5v14M5 12h14',
          '<div class="ps-quick">' +
            '<button id="sp-go-chat">💬 去对话</button>' +
            '<button id="sp-new-kb">📚 新建知识库</button>' +
          '</div>');
      const gc = document.getElementById('sp-go-chat');
      if (gc) gc.onclick = () => newSession();
      const nk = document.getElementById('sp-new-kb');
      if (nk) nk.onclick = () => { const b = $id('btn-new-kb'); if (b) b.click(); };
    });
  }
  const expSide = $id('exp-side');
  if (expSide) {
    jget('/api/experiment/list').then(d => {
      const n = (d && d.records) ? d.records.length : 0;
      expSide.innerHTML =
        psCard('实验记录', 'M9 3h6M10 3v6L4 21h16L14 9V3M8 15h8',
          '<div class="ps-stat"><span>已保存方案</span><b>' + n + '</b></div>' +
          '<div style="font-size:11px;color:var(--ml-text-faint);margin-top:8px">生成方案后可一键保存为记录，供后续复现。</div>') +
        psCard('模板速览', 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20',
          '<div style="font-size:12px;line-height:1.9">水热 · 溶胶凝胶 · 高温煅烧 · 电化学<br><span style="color:var(--ml-text-faint);font-size:11px">点击左侧模板卡片切换</span></div>');
    });
  }
  const paperRight = $id('paper-side-right');
  if (paperRight) {
    paperRight.innerHTML = psCard('论文进度', 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z',
      '<div id="ps-paper-progress"><div style="font-size:12px;color:var(--ml-text-faint)">选择课题后显示进度</div></div>');
  }
  const setSide = $id('settings-side');
  if (setSide) {
    jget('/api/settings').then(d => {
      if (!d || !d.ok) return;
      const a = d.approval || {};
      setSide.innerHTML =
        psCard('系统状态', 'M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z',
          '<div class="ps-stat"><span>模型</span><b style="font-size:11px">' + esc((d.model || {}).default || '—') + '</b></div>' +
          '<div class="ps-stat"><span>记忆</span><b style="color:' + (d.memory && d.memory.enabled ? 'var(--ml-ok)' : 'var(--ml-text-faint)') + '">' + (d.memory && d.memory.enabled ? '已开启' : '已关闭') + '</b></div>' +
          '<div class="ps-stat"><span>审批</span><b style="color:' + (a.enabled ? 'var(--ml-warn)' : 'var(--ml-text-faint)') + '">' + (a.enabled ? '已启用' : '自动') + '</b></div>' +
          '<div class="ps-stat"><span>API Key</span><b style="color:' + (d.api_key_set ? 'var(--ml-ok)' : 'var(--ml-danger)') + ';font-size:11px">' + (d.api_key_set ? '已配置' : '未配置') + '</b></div>') +
        psCard('关于', 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z',
          '<div style="font-size:12px;line-height:1.8"><b>MatLens 材料之镜</b><br><span style="color:var(--ml-text-faint)">材料科研 AI Agent · v0.2.0<br>DeepSeek + FastAPI + 原生 JS</span></div>');
    });
  }
}

/* ── 事件绑定 ────────────────────────────────────────── */
function bindEvents() {
  // 技能查看器开关
  const tcClose = $id('tc-close');
  if (tcClose) tcClose.addEventListener('click', closeToolCatalog);
  const tcMask = $id('tool-cat-mask');
  if (tcMask) tcMask.addEventListener('click', (e) => { if (e.target === tcMask) closeToolCatalog(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeToolCatalog(); } });

  // 执行日志侧栏
  const btnExec = $id('btn-exec-log');
  if (btnExec) btnExec.addEventListener('click', () => { if (S.execPanelOpen) closeExecLog(); else openExecLog(); });
  const execClose = $id('exec-close');
  if (execClose) execClose.addEventListener('click', closeExecLog);
  const execMask = $id('exec-mask');
  if (execMask) execMask.addEventListener('click', closeExecLog);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.execPanelOpen) closeExecLog(); });

  // 会话列表事件委托
  const sessionList = $id('session-list');
  if (sessionList) {
    sessionList.addEventListener('click', (e) => {
      const node = e.target.closest('[data-act]');
      if (!node) return;
      const act = node.getAttribute('data-act');
      const item = node.closest('.session-item');
      if (!item) return;
      const sid = item.getAttribute('data-sid');
      if (!sid) return;
      e.stopPropagation();
      if (act === 'select') selectSession(sid);
      else if (act === 'rename') renameSession(sid);
      else if (act === 'delete') deleteSession(sid);
      // 归档相关（2026-10-15）：入口在侧栏，不在工作区弹层里重复渲染会话列表
      else if (act === 'archive') archiveSession(sid, true);
    });
  }

  // 归档箱管理入口 → 设置页「会话」面板
  const mbArch = $id('btn-manage-archive');
  if (mbArch) mbArch.addEventListener('click', async () => {
    try {
      // 与「设置」按钮同一路径：加载数据 → 显示弹窗 → 切到会话面板
      document.getElementById('page-settings').classList.add('open');
      const { loadSettings } = await import('./settings.js');
      await loadSettings();
      const nav = $id('stng-nav');
      const tab = nav && nav.querySelector('.stng-nav-item[data-tab="sessions"]');
      if (tab) tab.click();
    } catch (e) { toast('打开设置失败', 'err'); }
  });

  const nbKb = $id('btn-new-kb'); if (nbKb) nbKb.addEventListener('click', createKb);

  // ── 知识库页交互（2026-10-15）──
  document.querySelectorAll('#page-kb .kb-tab').forEach(t =>
    t.addEventListener('click', () => switchKbTab(t.dataset.kbtab)));
  // 云端学术 API 模式（数据源双模 + 云端检索/导入链路）
  bindKbCloud();
  loadSources();
  const kbFilter = $id('doc-filter');
  if (kbFilter) kbFilter.addEventListener('input', () => filterDocs(kbFilter.value));
  const kbImport = $id('btn-kb-import');
  if (kbImport) kbImport.addEventListener('click', () => importByPaths());
  // 题录导入（知网人工检索导出 → 本地入库，中文文献唯一合规入口）
  bindCiteImport();
  // 开放数据集检索（Zenodo 等；材料实验的模拟输出与原始数据常在此）
  bindDatasetPane();
  // 预取数据集源目录，让 tab 上的数字一开始就有（否则首次点击前是 0）
  loadDatasetSources();
  const kbReadClose = $id('kb-read-close');
  if (kbReadClose) kbReadClose.addEventListener('click', closeDocReader);
  const kbReadMask = $id('kb-read-mask');
  if (kbReadMask) kbReadMask.addEventListener('click', closeDocReader);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const pn = $id('kb-read-panel');
    if (pn && pn.classList.contains('show')) closeDocReader();
  });
  const nbPaper = $id('btn-new-paper'); if (nbPaper) nbPaper.addEventListener('click', createPaper);
  const btnSettings = $id('btn-settings');
  if (btnSettings) btnSettings.addEventListener('click', () => {
    document.getElementById('page-settings').classList.add('open');
    loadSettings().catch(() => {});
  });
  const stngModal = $id('page-settings');
  if (stngModal) stngModal.addEventListener('click', (e) => {
    if (e.target === stngModal) stngModal.classList.remove('open');
  });
  const btnExpGen = $id('btn-exp-generate'); if (btnExpGen) btnExpGen.addEventListener('click', generateExp);
  const expGoal = $id('exp-goal'); if (expGoal) expGoal.addEventListener('keydown', e => { if (e.key === 'Enter') generateExp(); });
  const btnKbQ = $id('btn-kb-query'); if (btnKbQ) btnKbQ.addEventListener('click', queryKb);
  const kbQuery = $id('kb-query'); if (kbQuery) kbQuery.addEventListener('keydown', e => { if (e.key === 'Enter') queryKb(); });
  const btnSaveSet = $id('btn-save-settings'); if (btnSaveSet) btnSaveSet.addEventListener('click', saveSettings);
  const btnTestKey = $id('btn-test-key'); if (btnTestKey) btnTestKey.addEventListener('click', testConnection);
  const btnRefreshModels = $id('btn-refresh-models'); if (btnRefreshModels) btnRefreshModels.addEventListener('click', refreshModels);

  bindToolsPage();

  // KB 上传拖拽
  const uz = $id('upload-zone');
  if (uz) {
    uz.addEventListener('dragover', e => { e.preventDefault(); uz.style.borderColor = 'var(--ml-sky)'; });
    uz.addEventListener('dragleave', () => { uz.style.borderColor = ''; });
    uz.addEventListener('drop', async e => {
      e.preventDefault(); uz.style.borderColor = '';
      if (!S.kb) { toast('请先选择知识库'); return; }
      if (!e.dataTransfer.files.length) return;
      const fd = new FormData();
      fd.append('file', e.dataTransfer.files[0]);
      toast('正在导入 …');
      try {
        const r = await fetch('/api/kb/' + encodeURIComponent(S.kb.name) + '/documents', { method: 'POST', body: fd });
        const d = await r.json().catch(() => ({}));
        if (d && d.ok) { toast('导入成功', 'ok'); loadDocs(S.kb.name); loadKb(); }
        else toast('导入失败：' + ((d && d.detail) || JSON.stringify(d).slice(0, 120)), 'err');
      } catch (err) { toast('导入异常：' + err.message, 'err'); }
    });
  }

  // 导航：点击「智能对话」开新对话
  document.querySelectorAll('.nav-item').forEach(it => {
    it.addEventListener('click', () => {
      if (it.dataset.page === 'chat') newSession();
    });
  });
  // 切到记忆页时自动加载
  document.addEventListener('click', (e) => {
    const nav = e.target.closest('.nav-item[data-page="memory"]');
    if (nav) setTimeout(() => loadMemories(), 50);
  });

  bindMemoryUI();
  bindPaperUI();
}

/* ── 暴露 window（供 index.html 内联 onclick / 事件处理器） ── */
function exposeWindow() {
  window.ML = {
    send: sendMsg, stop: stop, newSession: newSession, pickUpload: pickUpload,
    _tpActive: false, _hideToolPicker: _hideToolPicker, _handleAtInput: _handleAtInput,
    renderEmptyState: renderEmptyState,   // 2026-10-15：app.js 覆盖层用它渲染引导卡
    toolPickerKey: _toolPickerKey,        // @ 选择器键盘导航（↑↓/Enter/Esc）
  };
  window.selectSession = selectSession;
  window.renameSession = renameSession;
  window.deleteSession = deleteSession;
  window.switchKb = switchKb;
  window.selectPaper = selectPaper;
  window.viewStage = viewStage;
  window.runPaperStep = runPaperStep;
  window.savePaperStep = savePaperStep;
  window.exportPaper = exportPaper;
  window.toKb = toKb;
  window.cancelPaperRun = cancelPaperRun;
  window.delPaper = delPaper;
  window.selectExpTpl = selectExpTpl;
  window.saveExpRecord = saveExpRecord;
  window.viewExpRecord = viewExpRecord;
  window.delExpRecord = delExpRecord;
  window.loadMemories = loadMemories;
}

/* ── 初始化 ────────────────────────────────────────────── */
(async function init() {
  exposeGlobals();
  initErrorBoundary();
  initResponsiveDrawer();
  exposeWindow();

  // 注入 chat 跨模块引用
  _bindChatGlobals({
    pickUpload: pickUpload,
    openToolCatalog: openToolCatalog,
    queryKb: () => {
      // kb.js 的 queryKb() 依赖知识库页的 DOM（#kb-query / #kb-results），
      // 在对话页直接调会因元素不存在而静默失败。故改为：带问题跳到知识库页。
      const q = ($id('input') && $id('input').value.trim()) || '';
      if (!S.kb || !S.kb.name) { toast('请先在「知识库」页选一个库'); return; }
      document.querySelector('.nav-item[data-page="kb"]').click();
      setTimeout(() => {
        const box = $id('kb-query');
        if (!box) return;
        box.value = q || ('关于 ' + (S.kb.name || '本知识库') + ' 的内容');
        queryKb();
      }, 700);
      toast(q ? ('带着问题去检索：' + S.kb.name) : ('已打开知识库：' + S.kb.name));
    },
    openMemoryPanel: () => switchRightTab('mem'),
  });
  _bindChatGlobals2({
    selectSession: selectSession,
    activateWorkspace: async (wsId) => {
      try {
        const r = await jpost('/api/workspaces/' + encodeURIComponent(wsId) + '/activate', {});
        if (!r || !r.ok) { toast('切换失败', 'err'); return; }
        toast('工作区：' + r.workspace.name);
        await loadWsChip();
        await renderWsPanel();
      } catch (e) { toast('切换失败：' + (e.message || e), 'err'); }
    },
  });

  bindEvents();
  bindChipPanels();
  initInputTools();
  initChatUI();          // 侧栏折叠 / 引导卡 / 状态图标 / 字数提示
  initRightPanel();      // 右栏 tab 切换 + 记忆删除/展开

  await Promise.all([
    loadSessions().catch(() => {}),
    loadKb().catch(() => {}),
    loadSettings().catch(() => {}),
    loadMemory().catch(() => {}),
    loadGraph().catch(() => {}),
    loadPapers().catch(() => {}),
    loadExpTemplates().catch(() => {}),
    Promise.resolve(initViz()).catch(() => {}),
    loadExpRecords().catch(() => {}),
    loadTools().catch(() => {}),
    loadModelChip().catch(() => {}),
    loadContextChip().catch(() => {}),
    loadApprovalChip().catch(() => {}),
  ]);
  fillSidePanels();
  const cs = $id('chat-stream');
  if (cs && !cs.innerHTML.trim()) {
    cs.innerHTML = '<div id="chat-empty" style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">新会话 · 向 MatLens 提问开始科研协作</div>';
  }
})();
