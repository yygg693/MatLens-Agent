/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · settings.js（DeepSeek Harness 风格设置页）
 * 布局借 Harness 壳，内容为 MatLens 自有：
 *   左栏 模型 / 通用 / 记忆 / 安全；右栏内容
 *   模型 tab：provider 垂直卡片列表（DeepSeek/Ollama/OpenRouter/OpenAI），
 *             点「编辑」就地展开（API key 小眼睛 / base_url / 模型目录）
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, jpost, jput, jgetSilent } from './core.js';

const PROV_LABEL = {
  deepseek: 'DeepSeek', openai: 'OpenAI 兼容', openrouter: 'OpenRouter', ollama: 'Ollama（本地）'
};
const PROV_TYPE = {
  deepseek: 'deepseek-official', openai: 'openai-compatible',
  openrouter: 'openai-compatible', ollama: 'local'
};
const BUILTIN_PROVS = ['deepseek', 'openai', 'openrouter', 'ollama'];

/* 运行期状态 */
let ST = {
  data: null,        // GET /api/settings 全量返回
  editing: null,     // 正在就地编辑的 provider key
  _rows: [],        // 编辑态模型目录行 [{id,label}]
  _sel: '',         // 编辑态当前选中（候选默认）模型 id
};

/* ── 左栏 tab 切换 ─────────────────────────────────────── */
function bindNav() {
  const nav = $id('stng-nav');
  if (!nav) return;
  nav.querySelectorAll('.stng-nav-item').forEach(item => {
    item.addEventListener('click', () => {
      const tab = item.dataset.tab;
      nav.querySelectorAll('.stng-nav-item').forEach(n => n.classList.toggle('active', n === item));
      document.querySelectorAll('#page-settings .stng-pane').forEach(p => {
        p.classList.toggle('active', p.dataset.pane === tab);
      });
      // 2026-10-15：会话面板（归档箱）按需加载 —— 打开设置时不必打这个接口
      if (tab === 'sessions') {
        import('./settings_sessions.js').then(m => {
          m.initSettingsSessions();
        }).catch(() => {});
      }
      // 网络隐私面板：需调 /api/web/* 探测出口 IP，切到该 tab 时才加载
      if (tab === 'network') {
        import('./settings_network.js').then(m => {
          m.loadNetworkPane();
        }).catch(err => console.warn('网络隐私面板加载失败', err));
      }
    });
  });
}

/* ── 主题（首屏 localStorage 即时上色；加载以后端为准，切换同时 PUT） ── */
let _themeSwitchHandler = null;  // loadSettings 注入：切换时把 theme 写回后端

function applyTheme(t) {
  try { localStorage.setItem('ml-theme', t); } catch (e) {}
  let eff = t;
  if (t === 'system') {
    eff = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : '';
  }
  if (eff) document.documentElement.setAttribute('data-theme', eff);
  else document.documentElement.removeAttribute('data-theme');
  document.querySelectorAll('#theme-seg button').forEach(b =>
    b.classList.toggle('active', b.dataset.val === t));
  const ts = $id('theme-select'); if (ts) ts.value = t; // 不派发 change，避免内联脚本重复 toast
}

function bindTheme() {
  const seg = $id('theme-seg');
  if (!seg) return;
  let cur = 'dark';
  try { cur = localStorage.getItem('ml-theme') || 'dark'; } catch (e) {}
  applyTheme(cur);
  seg.querySelectorAll('button').forEach(b => {
    b.addEventListener('click', () => {
      applyTheme(b.dataset.val);
      // 切换时同时写回后端（失败不影响本地上色）
      if (_themeSwitchHandler) _themeSwitchHandler(b.dataset.val);
    });
  });
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      let t = 'dark'; try { t = localStorage.getItem('ml-theme') || 'dark'; } catch (e) {}
      if (t === 'system') applyTheme('system');
    });
  }
}

/* ── provider 卡片列表（折叠态） ────────────────────────── */
function renderProviderList() {
  const wrap = $id('prov-list');
  if (!wrap) return;
  const d = ST.data;
  if (!d || !d.ok) { wrap.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:20px 0">设置读取失败</div>'; return; }
  const keys = d.provider_keys || {};
  // 固定四个 provider，一个都不能少
  const provs = (d.providers && d.providers.length) ? d.providers : ['deepseek', 'openai', 'openrouter', 'ollama'];
  window.PROVIDER_KEYS = keys;
  window.MODEL_CATALOG = d.model_catalog || {};

  wrap.innerHTML = provs.map(p => {
    const k = keys[p] || {};
    const isLocal = p === 'ollama';
    const configured = isLocal || !!k.set;
    const label = PROV_LABEL[p] || p;
    // Ollama 本地可用，不强制绿点；其余已配 key 才显绿点
    const dot = isLocal ? '<span style="font-size:10.5px;color:var(--ml-text-faint);font-weight:400;border:1px solid var(--ml-card-border);border-radius:6px;padding:1px 6px;margin-left:2px">本地可用</span>'
                        : (configured ? '<span class="stng-dot"></span>' : '');
    const isCustom = !BUILTIN_PROVS.includes(p);
    const delBtn = isCustom ? '<button class="stng-btn-del" data-del="' + esc(p) + '">删除</button>' : '';
    if (ST.editing === p) return editorCardHtml(p, label, configured);
    return '<div class="stng-prov-card" data-prov="' + esc(p) + '">' +
      '<div class="stng-prov-head">' +
        '<div class="stng-prov-name">' + esc(label) + dot + '</div>' +
        '<div style="display:flex;align-items:center;gap:6px">' +
          delBtn +
          '<button class="stng-btn-edit" data-edit="' + esc(p) + '">编辑</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  }).join('');

  wrap.querySelectorAll('[data-edit]').forEach(b => {
    b.addEventListener('click', () => openEditor(b.dataset.edit));
  });
  wrap.querySelectorAll('[data-del]').forEach(b => {
    b.addEventListener('click', () => toast('删除自定义提供商：后续接入'));
  });
  if (ST.editing) bindEditor(ST.editing);
}

/* ── 编辑态卡片 HTML ────────────────────────────────────── */
function editorCardHtml(p, label, configured) {
  const d = ST.data || {};
  const m = d.model || {};
  const base = m.base_url || '';
  const ph = (p === 'ollama') ? '本地服务 · 无需密钥'
    : (configured ? '已配置——输入新值可替换' : 'sk-…');
  return '<div class="stng-prov-card" data-prov="' + esc(p) + '">' +
    '<div class="stng-prov-head">' +
      '<div class="stng-prov-name">' + esc(label) +
        (p === 'ollama'
          ? '<span style="font-size:10.5px;color:var(--ml-text-faint);font-weight:400;border:1px solid var(--ml-card-border);border-radius:6px;padding:1px 6px;margin-left:2px">本地可用</span>'
          : (configured ? '<span class="stng-dot"></span>' : '')) +
      '</div>' +
      '<button class="stng-btn-edit" data-collapse="' + esc(p) + '">收起</button>' +
    '</div>' +
    '<div class="stng-edit">' +
      '<div class="stng-edit-head"><b>' + esc(label) + '</b><span class="stng-type">' + esc(PROV_TYPE[p] || 'custom') + '</span></div>' +
      '<label class="stng-flabel">API 密钥</label>' +
      '<div style="position:relative">' +
        '<input class="stng-input" id="ed-key" type="password" placeholder="' + esc(ph) + '" autocomplete="off" style="padding-right:38px">' +
        '<button type="button" id="ed-key-eye" title="显示/隐藏" style="position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--ml-text-faint);cursor:pointer;padding:4px">' +
          '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="stng-divider"></div>' +
      '<div class="stng-caret" id="ed-custom-toggle">▾ 自定义设置</div>' +
      '<div id="ed-custom-body" style="display:none;margin-top:12px">' +
        '<label class="stng-flabel">API 地址</label>' +
        '<input class="stng-input" id="ed-base" type="text" value="' + esc(base) + '">' +
        '<div class="stng-fhint">OpenAI 兼容端点</div>' +
        '<div class="stng-divider"></div>' +
        '<label class="stng-flabel">默认模型</label>' +
        '<div style="display:flex;gap:6px;align-items:center">' +
          '<input class="stng-input" id="ed-model-input" type="text" placeholder="点右侧下载按钮拉取模型" value="' + esc(ST._sel || '') + '" style="flex:1">' +
          '<button class="stng-icon-btn" id="ed-fetch" title="从 API 获取模型列表">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
          '</button>' +
        '</div>' +
        '<div id="ed-model-menu" style="display:none;position:relative;margin-top:4px;max-height:180px;overflow-y:auto;background:rgba(20,22,28,.95);border:1px solid rgba(255,255,255,.1);border-radius:10px;backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);box-shadow:0 8px 24px rgba(0,0,0,.3)"></div>' +
        '<div class="stng-fhint">点下载图标实时拉取模型，点列表项选中</div>' +
      '</div>' +
      '<div class="stng-divider"></div>' +
      '<div class="stng-actions">' +
        '<button class="stng-btn-ghost" id="ed-test">测试连接</button>' +
        '<span class="spacer"></span>' +
        '<button class="stng-btn-ghost" id="ed-cancel">取消</button>' +
        '<button class="stng-btn-primary" id="ed-save">保存</button>' +
      '</div>' +
    '</div>' +
  '</div>';
}

/* 初始模型行：catalog[p] ∪ 当前 default（deepseek-chat 即使不在 catalog 也要显示） */
function initialRows(p) {
  // 新 UI 不用预填模型行，由 API 拉取后填充
  return [];
}

function renderModelRows() {
  const box = $id('ed-models');
  if (!box) return;
  const curDefault = (ST.data && ST.data.model && ST.data.model.default) || '';
  box.innerHTML = ST._rows.map((r, i) => {
    const isSel = r.id && r.id === (ST._sel || curDefault);
    return '<div class="stng-model-row' + (isSel ? ' sel' : '') + '" data-idx="' + i + '">' +
      '<span class="stng-radio"></span>' +
      '<input class="mid" placeholder="模型 ID，如 deepseek-chat" value="' + esc(r.id) + '">' +
      '<input class="mlab" placeholder="友好名（可留空）" value="' + esc(r.label) + '">' +
      (isSel ? '<span class="stng-cur">当前</span>' : '') +
      '<button class="stng-del" title="删除">🗑</button>' +
    '</div>';
  }).join('');
  box.querySelectorAll('.stng-model-row').forEach(row => {
    const idx = parseInt(row.dataset.idx, 10);
    const mid = row.querySelector('.mid'), lab = row.querySelector('.mlab');
    mid.addEventListener('input', () => { ST._rows[idx].id = mid.value.trim(); });
    lab.addEventListener('input', () => { ST._rows[idx].label = lab.value; });
    row.querySelector('.stng-del').addEventListener('click', e => {
      e.stopPropagation();
      ST._rows.splice(idx, 1);
      renderModelRows();
    });
    row.addEventListener('click', e => {
      if (e.target === mid || e.target === lab) return;
      ST._sel = ST._rows[idx].id;
      renderModelRows();
    });
  });
}

function openEditor(p) {
  ST.editing = p;
  ST._rows = initialRows(p);
  const curDefault = (ST.data && ST.data.model && ST.data.model.default) || '';
  ST._sel = curDefault || (ST._rows[0] && ST._rows[0].id) || '';
  renderProviderList();
}

function bindEditor(p) {
  const cancel = $id('ed-cancel');
  if (cancel) cancel.addEventListener('click', () => { ST.editing = null; renderProviderList(); });
  const collapse = document.querySelector('[data-collapse="' + CSS.escape(p) + '"]');
  if (collapse) collapse.addEventListener('click', () => { ST.editing = null; renderProviderList(); });

  // API key 显示/隐藏小眼睛
  const eye = $id('ed-key-eye');
  const keyInp = $id('ed-key');
  if (eye && keyInp) eye.addEventListener('click', () => {
    keyInp.type = keyInp.type === 'password' ? 'text' : 'password';
  });

  const customT = $id('ed-custom-toggle');
  if (customT) {
    // 默认展开（因为模型目录在里面）
    const body = $id('ed-custom-body');
    if (body) body.style.display = 'block';
    customT.textContent = '▾ 自定义设置';
    customT.addEventListener('click', () => {
      if (!body) return;
      const show = body.style.display === 'none';
      body.style.display = show ? 'block' : 'none';
      customT.textContent = (show ? '▾ ' : '▸ ') + '自定义设置';
    });
  }
  const fetchBtn = $id('ed-fetch');
  const modelInput = $id('ed-model-input');
  const dropdownBtn = $id('ed-model-dropdown');
  const menu = $id('ed-model-menu');

  function renderMenu() {
    if (!menu) return;
    const live = ST._liveModels || {};
    const ids = Object.keys(live);
    // 打开编辑时，如果输入框是 ID，显示成友好名
    if (modelInput && modelInput.value.trim() && live[modelInput.value.trim()]) {
      modelInput.value = live[modelInput.value.trim()];
    }
    const cur = modelInput ? modelInput.value.trim() : '';
    if (!ids.length) { menu.innerHTML = '<div style="padding:10px 14px;color:var(--ml-text-faint);font-size:12.5px">点下载图标从 API 拉取模型</div>'; return; }
    menu.innerHTML = ids.map(id => {
      const name = live[id] || id;
      return '<div class="stng-menu-item" data-id="' + esc(id) + '" data-name="' + esc(name) + '" style="padding:9px 14px;cursor:pointer;font-size:13px;color:' + (id === cur ? 'var(--ml-sky)' : 'var(--ml-text)') + ';border-bottom:1px solid rgba(255,255,255,.04)">' + esc(name) + (id === cur ? ' ✓' : '') + '</div>';
    }).join('');
    menu.querySelectorAll('.stng-menu-item').forEach(item => {
      item.addEventListener('mouseenter', () => item.style.background = 'rgba(56,189,248,.1)');
      item.addEventListener('mouseleave', () => item.style.background = 'transparent');
      item.addEventListener('click', () => {
        if (modelInput) modelInput.value = item.dataset.name;
        ST._sel = item.dataset.id;
        menu.style.display = 'none';
      });
    });
  }

  ST._renderMenu = renderMenu;
  if (modelInput) modelInput.addEventListener('input', () => { ST._sel = modelInput.value.trim(); });
  if (fetchBtn) fetchBtn.addEventListener('click', async () => {
    const old = fetchBtn.innerHTML;
    fetchBtn.innerHTML = '<span style="display:inline-block;animation:spin 1s linear infinite">⟳</span>';
    fetchBtn.disabled = true;
    await refreshModels();
    fetchBtn.innerHTML = old;
    fetchBtn.disabled = false;
    if (menu) { renderMenu(); menu.style.display = 'block'; }
  });
  renderMenu();
  const save = $id('ed-save');
  if (save) save.addEventListener('click', () => saveEditor(p));
  const test = $id('ed-test');
  if (test) test.addEventListener('click', async () => {
    const old = test.textContent;
    test.textContent = '测试中…'; test.disabled = true;
    const r = await jpost('/api/settings/test', { provider: p });
    test.textContent = old; test.disabled = false;
    if (r && r.ok) toast('连接成功 · ' + (r.model || '') + ' · ' + r.latency_ms + 'ms', 'ok');
    else toast('连接失败：' + ((r && r.error) || '未知错误'), 'err');
  });
  renderMenu();
}

async function saveEditor(p) {
  let modelDefault = ($id('ed-model-input') ? $id('ed-model-input').value.trim() : '');
  if (!modelDefault) { toast('请填写或选择一个模型名', 'err'); return; }
  // 友好名反查 ID
  const live = ST._liveModels || {};
  const hitId = Object.keys(live).find(id => live[id] === modelDefault);
  if (hitId) modelDefault = hitId;
  const body = {
    model_provider: p,
    model_default: modelDefault,
    model_base_url: ($id('ed-base') ? $id('ed-base').value.trim() : ''),
  };
  const key = $id('ed-key');
  const kv = key ? key.value.trim() : '';
  if (kv) body.api_key = kv;
  const btn = $id('ed-save');
  if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
  const d = await jput('/api/settings', body);
  if (btn) { btn.disabled = false; btn.textContent = '保存'; }
  if (d && d.ok) {
    toast('设置已保存', 'ok');
    if (ST.data && ST.data.model) ST.data.model.default = modelDefault;
    const mt = $id('chat-model-tag'); if (mt) mt.textContent = modelDefault;
    const foot = $id('foot-model'); if (foot) foot.textContent = modelDefault;
    ST.editing = null;
    renderProviderList();
  } else {
    toast('保存失败：' + ((d && d.detail) || ''), 'err');
  }
}

/* ── 审批（安全 tab）：变更即 PUT，复用现有字段 ─────────── */
function putApproval() {
  const ae = $id('approval-enabled');
  const astr = $id('approval-strategy');
  const allow = $id('approval-allowlist');
  const body = {
    approval_enabled: ae ? ae.classList.contains('on') : false,
    approval_strategy: astr ? astr.value : 'auto',
  };
  const al = allow ? allow.value.split(/[,，]/).map(s => s.trim()).filter(Boolean) : [];
  if (al.length) body.approval_allowlist = al;
  jput('/api/settings', body).then(d => {
    if (d && d.ok) toast('审批设置已保存', 'ok');
    else toast('审批设置保存失败', 'err');
  });
}

function bindApproval() {
  const ae = $id('approval-enabled');
  if (ae) ae.addEventListener('click', () => { ae.classList.toggle('on'); putApproval(); });
  const astr = $id('approval-strategy');
  if (astr) astr.addEventListener('change', putApproval);
  const allow = $id('approval-allowlist');
  if (allow) allow.addEventListener('blur', putApproval);
  if (allow) allow.addEventListener('keydown', e => { if (e.key === 'Enter') allow.blur(); });
}

/* ── 通用设置绑定表：控件 id -> [段, 键, 类型(toggle|select), 是否int] ──
 * 数据驱动：页面加载时从 GET 回填；变更时 PUT 嵌套部分更新。
 * 契约第 4 节。审批(approval)不在此表内，保持原有逻辑。 */
const BINDINGS = [
  // general
  ['gen-tool-progress', 'general', 'tool_progress', 'toggle', false],
  ['reasoning-effort', 'general', 'reasoning_effort', 'select', false],
  ['max-turns', 'general', 'max_turns', 'select', true],
  // memory
  ['mem-ext', 'memory', 'enabled', 'toggle', false],
  ['mem-auto-write', 'memory', 'auto_write', 'toggle', false],
  ['mem-graph', 'memory', 'graph_auto_build', 'toggle', false],
  // papers
  ['paper-export-format', 'papers', 'export_format', 'select', false],
  ['paper-cite-style', 'papers', 'cite_style', 'select', false],
  ['paper-autosave', 'papers', 'autosave', 'toggle', false],
  ['paper-tone', 'papers', 'tone', 'select', false],
  // kb
  ['kb-embed-model', 'kb', 'embed_model', 'select', false],
  ['kb-chunk-size', 'kb', 'chunk_size', 'select', true],
  ['kb-chunk-overlap', 'kb', 'chunk_overlap', 'select', true],
  ['kb-table-extract', 'kb', 'table_extract', 'toggle', false],
  // experiment
  ['exp-template', 'experiment', 'template', 'select', false],
  ['exp-autosave', 'experiment', 'autosave', 'toggle', false],
  ['exp-plot-format', 'experiment', 'plot_format', 'select', false],
  ['exp-dpi', 'experiment', 'dpi', 'select', true],
];

/* 只读路径回填：控件 id -> [段, 键] */
const READONLY_BINDINGS = [
  ['kb-path', 'kb', 'root'],
  ['exp-path', 'experiment', 'db_path'],
  ['about-home', 'about', 'home'],
];

function _putNested(section, key, value) {
  const body = {}; body[section] = {}; body[section][key] = value;
  return jput('/api/settings', body);
}

/* 从 GET 数据回填所有控件（toggle 切 .on；select 设隐藏 select.value；只读路径赋值）。
 * 必须在 mountMlSelect 之前调用，自定义下拉才能 sync 出正确值。 */
function backfillBindings(d) {
  BINDINGS.forEach(([id, section, key, kind, isInt]) => {
    const el = $id(id);
    if (!el) return;
    const val = d[section] ? d[section][key] : undefined;
    if (val === undefined || val === null) return;
    if (kind === 'toggle') {
      el.classList.toggle('on', !!val);
    } else {
      // select：设隐藏 select 的 value（String 比较）
      el.value = String(val);
    }
  });
  READONLY_BINDINGS.forEach(([id, section, key]) => {
    const el = $id(id);
    if (!el) return;
    const val = d[section] ? d[section][key] : undefined;
    if (val !== undefined && val !== null) el.value = String(val);
  });
}

/* 绑定变更事件：toggle 立即 PUT；select 防抖 ~300ms PUT。 */
function wireBindings() {
  BINDINGS.forEach(([id, section, key, kind, isInt]) => {
    const el = $id(id);
    if (!el) return;
    if (kind === 'toggle') {
      el.addEventListener('click', () => {
        const on = el.classList.contains('on'); // click 后 class 已切换，取新值
        _putNested(section, key, on).then(r => {
          if (!r || !r.ok) toast('设置保存失败', 'err');
        });
      });
    } else {
      let timer = null;
      el.addEventListener('change', () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          let v = el.value;
          if (isInt) v = parseInt(v, 10);
          _putNested(section, key, v).then(r => {
            if (!r || !r.ok) toast('设置保存失败', 'err');
          });
        }, 300);
      });
    }
  });
}

/* ── 记忆状态（静默探测，失败则用占位文案，不报错） ──────── */
async function probeMemory() {
  const el = $id('mem-status-text');
  if (!el) return;
  const d = await jgetSilent('/api/memory/status');
  if (d && d.ok) {
    const src = d.source || d.provider || 'mem0';
    const n = d.count != null ? (' · 已记录 ' + d.count + ' 条') : '';
    el.textContent = '记忆已开启 · 召回来源 ' + src + n;
  } else {
    el.textContent = '记忆已开启 · 召回来源 mem0（本地）';
  }
}

/* ── 自定义深色 select（供 approval/effort/turns 使用） ── */
export function mountMlSelect(uiId) {
  const ui = $id(uiId);
  if (!ui) return null;
  const sel = $id(ui.getAttribute('data-for'));
  if (!sel) return null;
  const ph = ui.getAttribute('data-placeholder') || '';
  ui.innerHTML = '';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ml-select-btn';
  btn.setAttribute('aria-haspopup', 'listbox');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = '<span class="ml-sel-val"></span>' +
    '<svg class="ml-sel-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>';
  const menu = document.createElement('div');
  menu.className = 'ml-menu';
  menu.setAttribute('role', 'listbox');
  const search = document.createElement('input');
  search.className = 'ml-menu-search';
  search.placeholder = '搜索…';
  search.setAttribute('aria-label', '搜索选项');
  const list = document.createElement('div');
  menu.append(search, list);
  ui.append(btn, menu);

  let hlIdx = -1;
  function syncBtn() {
    const o = sel.options[sel.selectedIndex];
    const txt = o ? o.textContent : ph;
    btn.querySelector('.ml-sel-val').textContent = txt;
    btn.title = o ? o.value : ph;
  }
  function _visibleOpts() { return [...list.querySelectorAll('.ml-opt')]; }
  function _setHl(i) {
    const opts = _visibleOpts();
    if (!opts.length) { hlIdx = -1; return; }
    hlIdx = (i + opts.length) % opts.length;
    opts.forEach((o, k) => o.classList.toggle('hl', k === hlIdx));
    opts[hlIdx].scrollIntoView({ block: 'nearest' });
  }
  function renderOpts(q) {
    let opts = [...sel.options].filter(o => !q || String(o.textContent).toLowerCase().includes(q.toLowerCase()));
    if (!opts.length) { list.innerHTML = '<div class="ml-menu-empty">无匹配选项</div>'; hlIdx = -1; return; }
    list.innerHTML = '';
    opts.forEach((o) => {
      const d = document.createElement('div');
      d.className = 'ml-opt' + (o.selected ? ' sel' : '');
      d.setAttribute('role', 'option');
      d.setAttribute('aria-selected', o.selected ? 'true' : 'false');
      d.innerHTML = '<span class="ml-opt-txt">' + esc(o.textContent) + '</span>';
      const pick = () => {
        sel.value = o.value;
        sel.dispatchEvent(new Event('change'));
        syncBtn();
        close();
      };
      d.onclick = pick;
      list.appendChild(d);
    });
    hlIdx = -1;
  }
  function open() { search.value = ''; renderOpts(''); menu.classList.add('show'); btn.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); search.focus(); }
  function close() { menu.classList.remove('show'); btn.classList.remove('open'); btn.setAttribute('aria-expanded', 'false'); hlIdx = -1; }
  btn.onclick = e => { e.stopPropagation(); menu.classList.contains('show') ? close() : open(); };
  btn.onkeydown = e => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!menu.classList.contains('show')) open(); }
    else if (e.key === 'Escape') close();
  };
  search.oninput = () => renderOpts(search.value.trim());
  search.onkeydown = e => {
    if (e.key === 'Escape') { e.preventDefault(); close(); btn.focus(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); _setHl(hlIdx < 0 ? 0 : hlIdx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); _setHl(hlIdx < 0 ? _visibleOpts().length - 1 : hlIdx - 1); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const opts = _visibleOpts();
      if (hlIdx >= 0 && opts[hlIdx]) opts[hlIdx].click();
      else if (opts.length === 1) opts[0].click();
    }
  };
  document.addEventListener('click', close);
  sel.addEventListener('change', syncBtn);
  syncBtn();
  return { syncBtn };
}

/* ── 加载设置（main.js 启动时调用一次） ────────────────── */
export async function loadSettings() {
  bindNav();
  bindTheme();        // 首屏 localStorage 即时上色
  bindApproval();

  const d = await jget('/api/settings');
  if (!d || !d.ok) { toast('设置读取失败', 'err'); return; }
  ST.data = d;
  const m = d.model || {};
  window.MODEL_CATALOG = d.model_catalog || {};

  const mt = $id('chat-model-tag'); if (mt && m.default) mt.textContent = m.default;
  const foot = $id('foot-model'); if (foot && m.default) foot.textContent = m.default;

  // 安全 tab 回填
  const a = d.approval || {};
  const ae = $id('approval-enabled'); if (ae) ae.classList.toggle('on', !!a.enabled);
  const astr = $id('approval-strategy'); if (astr) astr.value = a.strategy || 'auto';
  const allow = $id('approval-allowlist'); if (allow) allow.value = (a.allowlist || []).join(', ');

  // ── 主题：加载以后端为准（applyTheme 不触发 PUT，因为值本就是持久化的）──
  if (d.general && d.general.theme) applyTheme(d.general.theme);
  _themeSwitchHandler = (t) => jput('/api/settings', { general: { theme: t } });

  // ── 通用回填：必须先设隐藏 select.value，再 mountMlSelect（否则自定义下拉显示旧值）──
  backfillBindings(d);

  ST.editing = null;
  renderProviderList();

  // 自定义下拉：此时隐藏 select.value 已是后端值，mount 后 sync 出正确显示
  mountMlSelect('approval-strategy-ui');
  mountMlSelect('reasoning-effort-ui');
  mountMlSelect('max-turns-ui');
  mountMlSelect('paper-export-format-ui');
  mountMlSelect('paper-cite-style-ui');
  mountMlSelect('paper-tone-ui');
  mountMlSelect('kb-embed-model-ui');
  mountMlSelect('kb-chunk-size-ui');
  mountMlSelect('kb-chunk-overlap-ui');
  mountMlSelect('exp-template-ui');
  mountMlSelect('exp-plot-format-ui');
  mountMlSelect('exp-dpi-ui');

  // 变更事件：toggle 立即 PUT；select 防抖 ~300ms PUT
  wireBindings();

  const pa = $id('prov-add');
  if (pa) pa.addEventListener('click', () => toast('自定义提供商后续接入（内置：DeepSeek / OpenAI 兼容 / OpenRouter / Ollama）'));

  // 关于 tab 按钮
  const btnBackup = $id('about-backup');
  if (btnBackup) btnBackup.addEventListener('click', async () => {
    // 契约：backup 走 blob 下载 GET /api/settings/backup（后端由后续任务实现，当前可能 404）
    try {
      const resp = await fetch('/api/settings/backup');
      if (!resp.ok) { toast('备份接口未就绪（HTTP ' + resp.status + '）', 'err'); return; }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'matlens-backup.zip';
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast('备份已导出', 'ok');
    } catch (e) {
      toast('备份下载失败或接口未就绪', 'err');
    }
  });
  const btnClearSess = $id('about-clear-sessions');
  if (btnClearSess) btnClearSess.addEventListener('click', async () => {
    if (!confirm('确定清空所有会话历史？记忆不受影响。')) return;
    const r = await jpost('/api/sessions/clear', {});
    if (r && r.ok) toast('会话历史已清空', 'ok');
    else toast('清空失败或接口未就绪', 'err');
  });
  const btnReset = $id('about-reset');
  if (btnReset) btnReset.addEventListener('click', async () => {
    if (!confirm('重置全部设置？需重新填写 API Key。')) return;
    const r = await jpost('/api/settings/reset', {});
    if (r && r.ok) { toast('已重置，即将刷新', 'ok'); setTimeout(() => location.reload(), 1200); }
    else toast('重置接口未就绪', 'err');
  });

  probeMemory();
}

/* ── 兼容导出：旧全局保存按钮已移除，这里只 PUT 审批字段 ── */
export async function saveSettings() {
  putApproval();
}

/* ── 兼容导出：测试当前 provider ── */
export async function testConnection() {
  const p = (ST.data && ST.data.model && ST.data.model.provider) || ST.editing || 'deepseek';
  const r = await jpost('/api/settings/test', { provider: p });
  if (r && r.ok) toast('连接成功 · ' + (r.model || '') + ' · ' + r.latency_ms + 'ms', 'ok');
  else toast('连接失败：' + ((r && r.error) || '未知错误'), 'err');
}

/* ── 刷新模型目录（只拉当前 provider，快） ── */
export async function refreshModels() {
  const prov = ST.editing || 'deepseek';
  const r = await jget('/api/settings/catalog?provider=' + encodeURIComponent(prov));
  if (r && r.ok && r.models) {
    // r.models = {id: friendly_name}
    ST._liveModels = r.models;
    if (!ST._sel) ST._sel = (Object.keys(r.models)[0] || '');
    if (ST._renderMenu) ST._renderMenu();
    const n = Object.keys(r.models).length;
    toast('已从 API 拉取 ' + n + ' 个模型', 'ok');
  } else {
    toast('拉取失败：' + ((r && r.error) || '网络错误'), 'err');
  }
}
