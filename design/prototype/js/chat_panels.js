/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · chat_panels.js
 *
 * 2026-10-15 从 chat.js 抽离：功能性标签面板（模型 / 上下文 / 审批 / 工作区）
 *
 * 为什么先抽这一块：依赖分析显示它是 chat.js 里耦合最轻的部分
 * （19 个函数中绝大多数零内部依赖），是风险最低的拆分起点。
 *
 * 本模块只管「面板的开关 / 定位 / 内容渲染」，不碰 SSE 主循环，
 * 也不碰输入区——两者留在 chat.js 以免动到流式渲染的关键路径。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jpost, jput, jdel, S, TOOL_ICON, friendlyToolArgs } from './core.js';

/* ── 功能性标签面板：模型 / 上下文 / 审批 / 工作区 ─────── */
const _chipPanelChip = { 'model-panel': 'chip-model', 'context-panel': 'chip-context', 'approval-panel': 'chip-approval', 'ws-panel': 'chip-ws' };
let _activeChipPanel = null;
function _closeChipPanels() {
  Object.keys(_chipPanelChip).forEach(n => {
    const p = $id(n); if (p) p.style.display = 'none';
  });
  _activeChipPanel = null;
}
function _positionChipPanel(name) {
  const panel = $id(name), chip = $id(_chipPanelChip[name]);
  if (!panel || !chip) return;
  const wrap = document.querySelector('.input-box-wrap');
  const wrapW = wrap ? wrap.clientWidth : 600;
  const panelW = panel.offsetWidth || 310;
  const chipLeft = chip.offsetLeft || 0;
  let left = Math.min(chipLeft, Math.max(0, wrapW - panelW - 4));
  panel.style.left = left + 'px';
}
export function bindChipPanels() {
  const map = { 'chip-model': 'model-panel', 'chip-context': 'context-panel', 'chip-approval': 'approval-panel', 'chip-ws': 'ws-panel' };
  Object.keys(map).forEach(cid => {
    const chip = $id(cid);
    if (!chip) return;
    chip.onclick = (e) => {
      e.stopPropagation();
      const pn = map[cid];
      const target = $id(pn);
      if (!target) return;
      const willOpen = target.style.display !== 'flex';
      _closeChipPanels();
      if (willOpen) {
        target.style.display = 'flex';
        _positionChipPanel(pn);
        _activeChipPanel = pn;
        if (pn === 'model-panel') renderModelPanel();
        if (pn === 'context-panel') renderContextPanel();
        if (pn === 'approval-panel') renderApprovalPanel();
        if (pn === 'ws-panel') renderWsPanel();
      }
    };
  });
  document.addEventListener('click', (e) => {
    if (_activeChipPanel && !e.target.closest('#' + _activeChipPanel) && !e.target.closest('.' + (_chipPanelChip[_activeChipPanel] || ''))) {
      _closeChipPanels();
    }
  });
}

/* ── 模型 chip / 面板 ────────────────────────────────── */
let _modelProv = '';
export async function loadModelChip() {
  try {
    const cur = await jget('/api/settings/agent-model');
    if (cur && cur.ok) _modelProv = cur.provider || '';
    const m = (cur && cur.ok && cur.model) || '未配置';
    const tx = $id('chip-model-name');
    if (tx) { tx.textContent = String(m); tx.title = String(m); }
  } catch (e) { /* 静默 */ }
}
export async function renderModelPanel() {
  const provEl = $id('cp-providers'), modelsEl = $id('cp-models');
  if (!provEl) return;
  provEl.innerHTML = '<div style="color:var(--ml-text-faint);font-size:12px;padding:4px">加载中…</div>';
  modelsEl.innerHTML = '';
  let cfg = null, cur = null;
  try {
    [cfg, cur] = await Promise.all([jget('/api/settings'), jget('/api/settings/agent-model')]);
  } catch (e) { /* 静默 */ }
  if (!cfg || !cfg.ok) { provEl.innerHTML = '<div style="color:var(--ml-text-faint);font-size:12px;padding:4px">配置读取失败</div>'; return; }
  const pk = cfg.provider_keys || {};
  const catalog = cfg.model_catalog || {};
  window.MODEL_CATALOG = catalog;
  _modelProv = (cur && cur.ok && cur.provider) || _modelProv || (cfg.model && cfg.model.provider) || 'deepseek';
  const curModel = (cur && cur.ok && cur.model) || '';
  const provOrder = ['deepseek', 'openrouter', 'openai', 'ollama'];
  provEl.innerHTML = provOrder.map(pv => {
    const info = pk[pv] || {};
    const hasKey = !!info.set || pv === 'ollama';
    return '<div class="cp-prov' + (pv === _modelProv ? ' active' : '') + '" data-prov="' + pv + '">' +
      pv + '<span class="dot ' + (hasKey ? 'on' : 'off') + '"></span></div>';
  }).join('');
  provEl.querySelectorAll('.cp-prov').forEach(el => {
    el.onclick = () => switchProvider(el.dataset.prov);
  });
  let opts = (catalog && catalog[_modelProv]) || [];
  if (!opts.length && cfg.model && cfg.model.provider === _modelProv) opts = cfg.model.options || [];
  modelsEl.innerHTML = opts.map(m => {
    const act = m === curModel ? ' active' : '';
    return '<div class="cp-model' + act + '" data-model="' + esc(m) + '">' +
      '<span class="cm-name">' + esc(m) + '</span><span class="cm-check">✓</span></div>';
  }).join('') || '<div style="padding:14px;text-align:center;color:var(--ml-text-faint);font-size:12px">该供应商暂无模型（请检查 API Key / 网络）</div>';
  modelsEl.querySelectorAll('.cp-model').forEach(el => {
    el.onclick = () => { const m = el.dataset.model; if (m) switchModel(_modelProv, m); };
  });
  const eff = (cfg.agent && cfg.agent.reasoning_effort) || 'medium';
  const rtx = $id('reasoning-tx');
  if (rtx) rtx.textContent = { low: '低', medium: '中', high: '高' }[eff] || eff;
  document.querySelectorAll('#reasoning-chips .stc').forEach(el => {
    el.classList.toggle('active', el.dataset.eff === eff);
    el.onclick = () => switchReasoning(el.dataset.eff);
  });
  renderKeySection(pk);
  const ks = $id('key-save');
  if (ks) ks.onclick = saveProviderKey;
}
async function switchProvider(prov) {
  if (prov === _modelProv) return;
  const r = await jput('/api/settings', { model_provider: prov });
  if (r && r.ok) {
    _modelProv = prov;
    toast('已切换模型商：' + prov);
    loadModelChip();
    await renderModelPanel();
  } else {
    toast('切换失败：' + ((r && r.detail) || '未知错误'), 'err');
  }
}
async function switchReasoning(eff) {
  const r = await jput('/api/settings', { reasoning_effort: eff });
  const names = { low: '低', medium: '中', high: '高' };
  if (r && r.ok) {
    toast('思考强度：' + (names[eff] || eff));
    renderModelPanel();
  } else toast('保存失败：' + ((r && r.detail) || '未知错误'), 'err');
}
function renderKeySection(pk) {
  const tx = $id('key-status-tx'), row = $id('key-input-row');
  if (!tx) return;
  const info = (pk || {})[_modelProv] || {};
  if (_modelProv === 'ollama') {
    tx.textContent = '本地服务 · 无需密钥';
    if (row) row.style.display = 'none';
    return;
  }
  if (info.set) {
    tx.textContent = ((info.env || 'API Key')) + ' 已配置 ' + (info.masked || '');
    if (row) row.style.display = 'none';
  } else {
    tx.textContent = ((info.env || 'API Key')) + ' 未配置';
    if (row) row.style.display = 'flex';
  }
}
async function saveProviderKey() {
  const inp = $id('key-input');
  if (!inp) return;
  const v = inp.value.trim();
  if (!v) { toast('请输入 API Key'); return; }
  const r = await jput('/api/settings', { model_provider: _modelProv, api_key: v });
  if (r && r.ok) { toast('API Key 已保存'); loadModelChip(); renderModelPanel(); }
  else toast('保存失败：' + ((r && r.detail) || '未知错误'), 'err');
}
async function switchModel(prov, model) {
  // 2026-10-15 修正：settings 是 PUT 端点，此处原用 POST → 405，
  // 且 _fetchJson 对 405 返回 null，被 `if (r && r.ok)` 静默吞掉 ——
  // 表现为「点了切模型没反应也没报错」。
  const r = await jput('/api/settings', { model_provider: prov, model_default: model });
  if (r && r.ok) {
    _modelProv = prov;
    const tx = $id('chip-model-name');
    if (tx) { tx.textContent = model; tx.title = model; }
    _closeChipPanels();
    toast('已切换模型：' + model);
  } else {
    toast('切换失败：' + ((r && r.detail) || '未知错误'), 'err');
  }
}

/* ── 上下文用量 ───────────────────────────────────────── */
export async function loadContextChip() {
  const tx = $id('chip-ctx-tx');
  if (!tx) return;
  const led = $id('chip-ctx-led');
  const chip = $id('chip-context');
  const sid = (S.session && S.session.id) || '';
  const paint = (cls, alarm) => {
    if (led) led.className = 'chip-led' + (cls ? ' ' + cls : '');
    if (chip) chip.className = 'chip chip-stat' + (alarm ? ' ' + alarm : '');
  };
  try {
    const d = await jget('/api/chat/context?session_id=' + encodeURIComponent(sid));
    if (d && d.ok) {
      const pct = d.pct || 0;
      tx.textContent = pct < 10 ? pct + '%' : Math.round(pct) + '%';
      tx.title = d.tokens.toLocaleString() + ' tokens · ' + d.messages + ' 条消息 / ' + d.limit.toLocaleString();
      // A3：色点分级 —— <60% 绿（宽裕），60~85% 黄（注意），>85% 红（该开新会话了）
      if (pct < 60) paint('ok', '');
      else if (pct < 85) paint('warn', 'alarm');
      else paint('danger', 'alarm-danger');
    } else { tx.textContent = 'ctx —'; paint('', ''); }
  } catch (e) { tx.textContent = 'ctx —'; paint('', ''); }
}
export async function renderContextPanel() {
  const sid = (S.session && S.session.id) || '';
  const d = await jget('/api/chat/context?session_id=' + encodeURIComponent(sid));
  const bar = $id('ctx-bar-fill'), tx = $id('ctx-tx'), mx = $id('ctx-max'), msg = $id('ctx-msg');
  if (!bar) return;
  if (d && d.ok) {
    bar.style.width = Math.min(100, d.pct) + '%';
    if (tx) tx.textContent = d.tokens.toLocaleString() + ' tokens';
    if (mx) mx.textContent = '/ ' + d.limit.toLocaleString();
    if (msg) msg.textContent = '消息 ' + d.messages + ' 条 · 会话内累计（估算）';
  } else {
    bar.style.width = '0%';
    if (tx) tx.textContent = '—';
    if (msg) msg.textContent = '读取失败';
  }
}

/* ── 安全审批 chip / 面板 ─────────────────────────────── */
/* 2026-10-15 重做。旧版只有「开关 + 三档策略」，没有清单入口，
   而后端默认 allowlist=[] —— 开confirm_list 就要为**每个**工具点确认
   （连read_file 都不免），实际无法使用。旧版还把 enabled=false
   显示成「审批 关」，用户开了 auto 又发现毫无效果，却不知道原因。
   现补：① 清单可视化+ 可增删 ② 组合无效时给出明确警告 ③ 说明文案讲清后果。 */
let _approvalCfg = null;

export async function loadApprovalChip() {
  try {
    const cfg = await jget('/api/settings');
    if (!cfg || !cfg.ok || !cfg.approval) return;
    _approvalCfg = cfg.approval;
    const tx = $id('chip-approval-tx'), dot = $id('chip-approval-dot');
    const led = $id('chip-approval-led');
    const on = !!_approvalCfg.enabled;
    // 文案直说「是否真的在拦」，不再只报开关状态
    const effective = on && _approvalCfg.strategy !== 'auto';
    if (tx) tx.textContent = effective ? '审批 开' : (on ? '审批 空转' : '审批 关');
    if (dot) dot.classList.toggle('on', effective);
    if (led) led.className = 'chip-led' + (effective ? ' ok' : (on ? ' warn' : ''));
    const chip = $id('chip-approval');
    if (chip) {
      chip.className = 'chip chip-stat' + (on && !effective ? ' alarm' : '');
      chip.title = effective
        ? '白名单外工具执行前需你确认'
        : (on ? '已开启但策略是「全放行」，实际不拦截任何工具' : '工具直接执行，不做拦截');
    }
  } catch (e) { /* 静默 */ }
}

/** 渲染清单（免审 / 高危），带点击增删。 */
function _renderApprovalList(kind, arr) {
  const box = $id(kind === 'allow' ? 'ap-allowlist' : 'ap-denylist');
  const nEl = $id(kind === 'allow' ? 'ap-allow-n' : 'ap-deny-n');
  if (nEl) nEl.textContent = (arr || []).length;
  if (!box) return;
  const input = $id(kind === 'allow' ? 'ap-allow-input' : 'ap-deny-input');
  box.innerHTML = (arr || []).map(t =>
    '<span class="ap-tag' + (kind === 'deny' ? ' deny' : '') + '" data-rm="' + esc(t) + '" title="点击移除">' +
    esc(t) + '<i>✕</i></span>').join('')
    + '<input class="ap-input" id="' + (kind === 'allow' ? 'ap-allow-input' : 'ap-deny-input')
    + '" placeholder="工具名，回车添加">';
  const inp = box.querySelector('.ap-input');
  if (inp) {
    inp.onclick = (e) => e.stopPropagation();
    inp.onkeydown = (e) => {
      e.stopPropagation();
      if (e.key !== 'Enter') return;
      const v = inp.value.trim();
      if (!v) return;
      const list = _approvalCfg[kind === 'allow' ? 'allowlist' : 'denylist'] || [];
      if (!list.includes(v)) list.push(v);
      inp.value = '';
      switchApproval({ [(kind === 'allow' ? 'approval_allowlist' : 'approval_denylist')]: list });
    };
  }
  box.querySelectorAll('.ap-tag').forEach(t => {
    t.onclick = () => {
      const key = kind === 'allow' ? 'allowlist' : 'denylist';
      const list = (_approvalCfg[key] || []).filter(x => x !== t.dataset.rm);
      switchApproval({ [(kind === 'allow' ? 'approval_allowlist' : 'approval_denylist')]: list });
    };
  });
}

export async function renderApprovalPanel() {
  if (!_approvalCfg) {
    try {
      const cfg = await jget('/api/settings');
      if (cfg && cfg.ok && cfg.approval) _approvalCfg = cfg.approval;
    } catch (e) { /* 静默 */ }
  }
  const a = _approvalCfg || { enabled: false, strategy: 'auto', allowlist: [], denylist: [] };
  const tog = $id('approval-toggle');
  if (tog) {
    tog.classList.toggle('on', !!a.enabled);
    tog.onclick = (e) => { e.stopPropagation(); switchApproval({ approval_enabled: !a.enabled }); };
  }

  // 策略：改为可点按钮组（原来「策略」那行只是一行文字，看不出是可选的）
  document.querySelectorAll('#strategy-chips .stc').forEach(el => {
    el.classList.toggle('active', el.dataset.str === a.strategy);
    el.onclick = (e) => { e.stopPropagation(); switchApproval({ approval_strategy: el.dataset.str }); };
  });

  const note = $id('approval-note');
  if (note) {
    const notes = {
      auto: '所有工具直接执行，不做任何拦截。适合完全信任 Agent 的场景。',
      confirm_list: '只有「免审清单」里的工具直接执行，其余每次都要你点确认。清单越全越省事，但防护也越弱。',
      deny_list: '「高危拦截」里的工具直接拒绝，其余全部放行。适合防手滑，不适合精细管控。',
    };
    note.textContent = notes[a.strategy] || '';
  }

  // 组合无效警告：开了却选了 auto，用户会以为防护已生效
  const warn = $id('approval-warn');
  if (warn) {
    if (a.enabled && a.strategy === 'auto') {
      warn.style.display = '';
      warn.innerHTML = '开关已开，但策略是「全放行」——<b>实际不会拦截任何工具</b>。想真正生效请选「白名单外审批」。';
    } else if (!a.enabled) {
      warn.style.display = '';
      warn.innerHTML = '工具执行<b>不经过任何确认</b>，包括写文件、跑命令、删除操作。';
    } else {
      warn.style.display = 'none';
      warn.textContent = '';
    }
  }

  _renderApprovalList('allow', a.allowlist || []);
  _renderApprovalList('deny', a.denylist || []);
}

async function switchApproval(patch) {
  const r = await jput('/api/settings', patch);
  if (r && r.ok) {
    if (r.approval) _approvalCfg = r.approval;
    await loadApprovalChip();
    await renderApprovalPanel();
    toast('审批设置已更新');
  } else toast('保存失败：' + ((r && r.detail) || '未知错误'), 'err');
}

/* ── 工作区 chip / 面板 ───────────────────────────────── */
export async function loadWsChip() {
  // 2026-10-15：chip 文案从「新会话」改为「工作区」——
  // 新建会话已有侧栏「聊天历史 / +」这一入口，chip 的职责应是
  // 显示 **Agent 正在操作的本地目录**，这才是科研场景的关键上下文。
  const tx = $id('chip-ws-name');
  if (!tx) return;
  try {
    const d = await jget('/api/workspaces');
    const cur = (d && d.current && d.workspaces.find(w => w.id === d.current)) || null;
    const n = (d && d.count) || 0;
    const btn = $id('chip-ws');
    if (cur) {
      tx.textContent = cur.name || '工作区';
      const tip = '工作区 · Agent 读写的根目录\n' + cur.path + (cur.exists ? '' : '（目录已不存在）');
      tx.title = tip;
      if (btn) btn.title = tip;
    } else {
      tx.textContent = n ? '选择工作区' : '未设工作区';
      const tip = '工作区 · Agent 读写的根目录\n尚未设置——Agent 的文件读写与终端会落在服务进程的工作目录';
      tx.title = tip;
      if (btn) btn.title = tip;
    }
  } catch (e) {
    tx.textContent = '未设工作区';
  }
}

/** 工作区选择（浏览器不能直接取本地路径，用 prompt 手动输入绝对路径）。 */
function _promptWorkspacePath() {
  const v = window.prompt(
    '输入工作区的**绝对路径**（Agent 的文件读写与终端都会以它为根）\n' +
    '例如： D://MatLens//data// 实验数据',
    'D://');
  if (!v || !v.trim()) return;
  addWorkspaceGlobal(v.trim());
}

async function addWorkspaceGlobal(path) {
  try {
    const r = await jpost('/api/workspaces', { path });
    if (!r || !r.ok) { toast('添加失败：' + ((r && r.error) || '未知错误'), 'err'); return; }
    toast('工作区已切换：' + r.workspace.name);
    loadWsChip();
    renderWsPanel();
  } catch (e) {
    toast('添加失败：' + (e.message || e), 'err');
  }
}

export async function renderWsPanel() {
  const list = $id('ws-list');
  if (!list) return;
  list.innerHTML = '<div style="padding:10px;color:var(--ml-text-faint);font-size:12px">加载中…</div>';

  /* 2026-10-15 修正：这个面板此前同时塞了「工作区 + 历史会话 + 归档箱」，
     而侧栏本来就已有「聊天历史 + 搜索 + 重命名/删除」——
     **同一份会话列表渲染了两遍**，且 320px 宽的弹层塞 50 条会话没法用。
     现在面板只管工作区；会话相关的归档能力移到侧栏（见 sessions.js）。
     依据：会话管理的主入口是侧栏（常驻可见、可搜索），
     chip 面板是「上下文设置」，不该承担列表职责。 */
  let wsData = { workspaces: [], count: 0, current: null };
  try { wsData = (await jget('/api/workspaces')) || wsData; } catch (e) { /* 静默 */ }
  const wsArr = wsData.workspaces || [];

  let h = '<div class="cp-sec">工作区<span class="cp-sec-n">' + wsArr.length + '</span>' +
    '<span class="cp-sec-tip">Agent 读写与终端的根目录</span></div>';
  h += '<button class="ws-add" id="ws-add-btn"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg><span>添加本地文件夹…</span></button>';

  if (wsArr.length) {
    h += wsArr.map(w => {
      const act = w.id === wsData.current ? ' active' : '';
      const warn = w.exists ? '' : ' missing';
      return '<div class="ws-row' + act + warn + '" data-wsid="' + esc(w.id) + '" title="' + esc(w.path) + '">' +
        '<span class="ws-ic"><svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>' +
        '<span class="ws-meta"><span class="ws-name">' + esc(w.name || '工作区') +
        (w.is_git ? '<em class="ws-badge">git</em>' : '') +
        (w.exists ? '' : '<em class="ws-badge ws-bad">目录丢失</em>') + '</span>' +
        '<span class="ws-path">' + esc(w.path) + '</span></span>' +
        '<button class="ws-del" data-delws="' + esc(w.id) + '" title="从列表移除（不删磁盘目录）">✕</button>' +
        '</div>';
    }).join('');
  } else {
    h += '<div class="ws-empty">' +
      '<svg viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>' +
      '<div class="ws-empty-t">还没有工作区</div>' +
      '<div class="ws-empty-h">未设置时，Agent 读写文件会落在服务进程的工作目录' +
      '（通常是 D:\\MatLens），不一定是你的实验数据所在位置。</div></div>';
  }

  // 指向：会话管理与归档在侧栏，不在这个面板里
  h += '<div class="ws-foot">会话管理与归档在左侧「聊天历史」里' +
    '<button class="ws-jump" data-act="goto-sessions">前往</button></div>';

  list.innerHTML = h;

  const addBtn = $id('ws-add-btn');
  if (addBtn) addBtn.onclick = (e) => { e.stopPropagation(); _promptWorkspacePath(); };

  list.querySelectorAll('.ws-row').forEach(el => {
    el.onclick = (e) => {
      if (e.target.closest('[data-delws]')) return;
      activateWorkspaceGlobal(el.dataset.wsid);
    };
  });
  const jump = list.querySelector('[data-act="goto-sessions"]');
  if (jump) {
    jump.onclick = (e) => {
      e.stopPropagation();
      _closeChipPanels();
      const sb = $id('side-sessions');
      if (sb) sb.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
  }

  list.querySelectorAll('[data-delws]').forEach(b => {
    b.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm('从列表移除该工作区？\n（磁盘目录不会被删除）')) return;
      try {
        await jdel('/api/workspaces/' + encodeURIComponent(b.dataset.delws));
        toast('已移除工作区条目');
        await loadWsChip();
        await renderWsPanel();
      } catch (err) { toast('移除失败：' + (err.message || err), 'err'); }
    };
  });
}

let selectSessionGlobal = (sid) => {};
let activateWorkspaceGlobal = (path) => {};
export function _bindChatGlobals2(opts) {
  if (opts.selectSession) selectSessionGlobal = opts.selectSession;
  if (opts.activateWorkspace) activateWorkspaceGlobal = opts.activateWorkspace;
}
