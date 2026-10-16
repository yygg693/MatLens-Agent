/* ═══════════════════════════════════════════════════════════════
 * MatLens 前端 · tools.js（工具中心：工具网格 + 技能库 + 详情抽屉）
 *
 * 2026-10-15 升级要点
 * ────────────────────
 * 1. 通用工具改为**逐条展示**（旧版只画6 张分类卡，81 个里只有 18 个可见）；
 * 2. 新增**技能库**分区 —— 后端 /api/tools/skills 列出 agent 真实可用的
 *    skill（当前 186 个），agent 新装/自更新的 skill 会自动出现在这里；
 * 3. 点卡片开**详情抽屉**：参数 schema（名/类型/必填/说明）、示例调用、
 *    来源；不再只复制一个工具名；
 * 4. 分类标签由后端动态下发（29 个），不再写死。
 * ═══════════════════════════════════════════════════════════════ */
import { esc, $id, toast, jget, psCard, toolCatColor } from './core.js';
import { setToolData } from './chat.js';

export let TOOL_DATA = { material: [], general: null, skills: [] };
export const TOOL_FILTER = { cat: '全部', q: '', onlyAvailable: false };
let _current = null;          // 当前详情抽屉条目
let _drawerOpen = false;

/* ── 工具大类配色（与 core.js toolCatColor 协同） ── */
function catColor(cat) {
  return toolCatColor(cat) || '#64748b';
}

function _isGeneral(t) { return !!(t && t.source === 'Agent 核心'); }

/* ══════════════════════════════════════════════════════════
 * 详情抽屉
 * ══════════════════════════════════════════════════════════ */
function _drawerHtml(t) {
  if (!_current) return '';
  const p = t.params_detail || [];
  // 参数 schema 表格保留为「参考」：填参表单已含字段名/类型/说明，
  // 但它一次列全所有参数（含未填的可选项），便于核对与查阅文档。
  const paramsHtml = p.length
    ? '<details class="tw-schema-box"><summary>参数 schema（' + p.length + ' 项，参考用）</summary>' +
      '<table class="tw-params"><thead><tr><th>参数</th><th>类型</th><th>必填</th><th>说明</th></tr></thead><tbody>' +
      p.map(x => '<tr><td class="mono">' + esc(x.name) + '</td><td class="mono">' + esc(x.type) +
        '</td><td>' + (x.required ? '<span class="tw-req">必填</span>' : '<span class="tw-opt">可选</span>') +
        '</td><td>' + esc(x.desc || '—') + '</td></tr>').join('') +
      '</tbody></table></details>'
    : '';

  const exHtml = (t.examples && t.examples.length)
    ? '<details class="tw-schema-box"><summary>示例调用（' + t.examples.length + '）</summary>' +
      t.examples.slice(0, 3).map(e =>
        '<pre class="tw-ex">' + esc(t.name + '(\n' +
          Object.entries(e).map(([k, v]) => '  ' + k + ': ' + JSON.stringify(v)).join(',\n') + '\n)') + '</pre>').join('') +
      '</details>'
    : '';

  return _tagsHtml(t) +
    '<div class="tw-desc">' + esc(t.desc_cn || t.desc || '（无描述）') + '</div>' +
    (t.desc_cn && t.desc ? '<div class="tw-desc-en">' + esc(t.desc) + '</div>' : '') +
    _formHtml(t, p) +
    paramsHtml +
    exHtml +
    '<div class="tw-actions">' +
      '<button class="btn btn-primary btn-sm" id="tw-send"' + (t.available === false ? ' disabled' : '') +
        '>发送到对话框</button>' +
      '<button class="btn btn-ghost btn-sm" id="tw-copy">复制工具名</button>' +
      '<button class="btn btn-ghost btn-sm" id="tw-schema">复制 JSON Schema</button>' +
    '</div>';
}

function _tagsHtml(t) {
  return '<div class="tw-tags">' +
      '<span class="tw-tag">' + esc(t.category_cn || t.cat || '未分类') + '</span>' +
      '<span class="tw-tag tw-tag-src">' + esc(t.source || t.scope || '') + '</span>' +
      (t.available === false ? '<span class="tw-warn">当前不可用</span>' : '') +
    '</div>';
}

/** 把当前工具同步到抽屉固定头部（标题/图标/分类）。
 *  头部在 HTML 里是固定的，body 由 _drawerHtml 渲染 —— 两者分开放才能避免
 *  「顶部死文案 + 半截真标题」的重复渲染问题。 */
function _syncDrawerHead(t) {
  const title = $id('tw-head-title');
  const sub = $id('tw-head-sub');
  const icon = $id('tw-head-icon');
  if (!title || !sub || !icon) return;
  if (!t) {
    title.textContent = '工具详情';
    sub.textContent = '';
    icon.textContent = '⚡';
    icon.style.background = 'rgba(56,189,248,.12)';
    icon.style.color = 'var(--ml-accent)';
    return;
  }
  const cn = t.cn || t.name || '工具';
  title.textContent = cn;
  sub.textContent = t.name || '';
  const cat = t.category_cn || t.cat;
  const c = cat ? catColor(cat) : 'var(--ml-accent)';
  icon.textContent = t.emoji || (cn[0] || '⚡');
  icon.style.background = c + '1f';
  icon.style.color = c;
}

/** 填参表单（2026-10-16 新增）。
 *  此前抽屉只能「看参数表 + 复制工具名」，用户要手动把参数敲进对话框 ——
 *  这就是「工具不能真正用起来」的根因。现在直接在抽屉里填，一键送进对话框。 */
function _formHtml(t, params) {
  if (!params.length) {
    return '<div class="tw-run-note">该工具无需参数，点「发送到对话框」即可让 Agent 调用。</div>';
  }
  return '<div class="tw-sec-title">填写参数</div>' +
    '<div class="tw-form" id="tw-form">' +
    params.map((x, i) => {
      const id = 'twp-' + i;
      const req = x.required ? '<span class="tw-req-inline">必填</span>' : '<span class="tw-tag">可选</span>';
      // 示例值来自 examples（若有），可一键填入
      let ex = '';
      if (t.examples && t.examples.length && t.examples[0] && x.name in t.examples[0]) {
        const v = t.examples[0][x.name];
        ex = '<button class="tw-web-act" data-fill="' + id + '" data-val="' +
          esc(typeof v === 'string' ? v : JSON.stringify(v)) + '" style="font-size:10px;padding:2px 7px">用示例值</button>';
      }
      const multi = x.type === 'array' || (typeof x.desc === 'string' && x.desc.includes('['));
      return '<div class="tw-field">' +
        '<label for="' + id + '"><code>' + esc(x.name) + '</code>' +
          '<span class="tw-tag">' + esc(x.type || 'string') + '</span>' + req + ex + '</label>' +
        (multi
          ? '<textarea id="' + id + '" data-pname="' + esc(x.name) + '" rows="2" placeholder="' +
            esc(x.desc || '') + '"></textarea>'
          : '<input id="' + id + '" data-pname="' + esc(x.name) + '" type="text" placeholder="' +
            esc(x.desc || '') + '">') +
        '<div class="tw-fhint">' + esc(x.desc || '') + '</div>' +
      '</div>';
    }).join('') + '</div>';
}

/** 收集表单值。空的可选参数直接不带，避免给 Agent 塞一堆 null。 */
function _collectParams(t) {
  const form = $id('tw-form');
  if (!form) return {};
  const out = {};
  let missing = [];
  form.querySelectorAll('[data-pname]').forEach(el => {
    const n = el.getAttribute('data-pname');
    const v = (el.value || '').trim();
    if (!v) {
      const req = el.closest('.tw-field') &&
        el.closest('.tw-field').querySelector('.tw-req-inline');
      if (req) missing.push(n);
      return;
    }
    // 能解析成 JSON 的尽量解析（数字/数组/对象）
    try { out[n] = JSON.parse(v); }
    catch (e) { out[n] = v; }
  });
  return { args: out, missing };
}

function _openDrawer(t) {
  _current = t;
  _drawerOpen = true;
  const mask = $id('tool-detail-mask');
  const body = $id('tw-body');
  if (!mask || !body) return;
  _syncDrawerHead(t);
  body.innerHTML = _drawerHtml(t);
  mask.classList.add('show');

  // 「用示例值」一键填充
  body.querySelectorAll('[data-fill]').forEach(b => {
    b.onclick = (e) => {
      e.preventDefault();
      const el = $(b.getAttribute('data-fill'));
      if (el) { el.value = b.getAttribute('data-val'); el.focus(); }
    };
  });

  // 发送到对话框：让工具真正能被「用起来」
  const sd = $id('tw-send');
  if (sd) {
    sd.onclick = () => {
      if (t.available === false) { toast('该工具当前不可用', 'err'); return; }
      const { args, missing } = _collectParams(t);
      if (missing && missing.length) {
        toast('还需填写必填参数：' + missing.join('、'), 'err');
        const el = body.querySelector('[data-pname="' + CSS.escape(missing[0]) + '"]');
        if (el) el.focus();
        return;
      }
      const payload = { tool: t.name, cn: t.cn || t.name, args };
      let text;
      try {
        const json = JSON.stringify(args);
        text = Object.keys(args).length
          ? ('调用工具 ' + (t.cn || t.name) + '（' + t.name + '），参数：' + json)
          : ('调用工具 ' + (t.cn || t.name) + '（' + t.name + '）');
      } catch (e) {
        text = '调用工具 ' + (t.cn || t.name) + '（' + t.name + '）';
      }
      _sendToChat(text, payload);
      closeToolDrawer();
    };
  }

  const cp = $id('tw-copy');
  if (cp) cp.onclick = () => _copy(t.name, '已复制工具名 ' + t.name + '，去「智能对话」中调用');
  const sc = $id('tw-schema');
  if (sc) sc.onclick = () => {
    const schema = { type: 'object', properties: {}, required: [] };
    (t.params_detail || []).forEach(x => {
      schema.properties[x.name] = { type: x.type, description: x.desc };
      if (x.required) schema.required.push(x.name);
    });
    _copy(JSON.stringify(schema, null, 2), '已复制参数 schema');
  };
}

/** 把工具调用送进对话框。
 *  只填入框、不自动发送 —— 让用户先看一眼再决定，避免误触发昂贵调用。 */
function _sendToChat(text, payload) {
  const box = $id('input');
  if (!box) { toast('对话框输入框不存在', 'err'); return; }
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  // 记录在 input 上，便于前端或其他模块识别这是一次「工具调用预填」
  box.dataset.toolPayload = JSON.stringify(payload || {});
  box.focus();
  const auto = box.offsetHeight;
  if (auto) box.style.height = 'auto';
  closeToolCatalog();
  toast('已填入对话框，确认后按 Enter 发送', 'ok');
}

export function closeToolDrawer() {
  _current = null;
  _drawerOpen = false;
  const mask = $id('tool-detail-mask');
  if (mask) mask.classList.remove('show');
  _syncDrawerHead(null);   // 复位标题，避免下次打开闪现上一条工具名
}

function _copy(text, msg) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => toast(msg, 'ok'))
      .catch(() => toast('复制失败，请手动选取', 'err'));
  } else {
    toast(msg);
  }
}

/* ══════════════════════════════════════════════════════════
 * 网格渲染
 * ══════════════════════════════════════════════════════════ */
function _match(t) {
  const q = TOOL_FILTER.q;
  if (TOOL_FILTER.onlyAvailable && t.available === false) return false;
  if (TOOL_FILTER.cat !== '全部' && TOOL_FILTER.cat !== '全部技能' && t.cat !== TOOL_FILTER.cat) return false;
  if (!q) return true;
  // 搜索覆盖：中英文名 + 中英文描述 + 分类（skill 走category_cn）
  const hay = [t.name, t.cn, t.desc, t.desc_cn, t.category, t.category_cn, t.scope]
    .filter(Boolean).join(' ').toLowerCase();
  return hay.indexOf(q) >= 0;
}

export function renderToolGrid() {
  const grid = $id('tool-grid');
  if (!grid) return;

  const isSkillMode = TOOL_FILTER.cat === '全部技能';
  const src = isSkillMode
    ? (TOOL_DATA.skills || [])
    : (TOOL_DATA.material || []).concat((TOOL_DATA.general && TOOL_DATA.general.items) || []);
  const list = src.filter(_match);

  if (!list.length) {
    grid.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">' +
      (TOOL_FILTER.q ? '没有匹配「' + esc(TOOL_FILTER.q) + '」的条目' : '暂无条目') + '</div>';
    return;
  }

  grid.innerHTML = list.map(t => {
    const isSkill = isSkillMode;
    // 分类显示：skill 用中文分类，普通工具用 cat
    const catLabel = isSkill
      ? (t.category_cn || t.category || '未分类')
      : (t.cat || '未分类');
    const c = catColor(catLabel);
    // 标题/描述：中文优先，缺失回落英文
    const label = (isSkill ? (t.cn || t.name) : (t.cn || t.name));
    const descText = (isSkill ? (t.desc_cn || t.desc) : (t.desc)) || '';
    const meta = isSkill
      ? (t.scope + (t.category ? ' / ' + t.category : ''))
      : (t.cat + (t.available === false ? ' · 不可用' : ''));
    const badge = (t.params_detail && t.params_detail.length)
      ? '<span class="tt-badge">' + t.params_detail.length + ' 参数</span>' : '';
    return '<div class="tool-tile" data-name="' + esc(t.name) + '" data-kind="' +
      (isSkill ? 'skill' : 'tool') + '" tabindex="0" title="点击查看详情">' +
      '<div class="tt-icon" style="background:' + c + '1f;color:' + c + '">' + esc(label[0]) + '</div>' +
      '<div class="tt-name">' + esc(label) + '</div>' +
      '<div class="tt-mono">' + esc(t.name) + '</div>' +
      '<div class="tt-desc">' + esc(descText) + '</div>' +
      '<div class="tt-foot"><span class="tt-cat">' + esc(meta) + '</span>' + badge + '</div>' +
      '</div>';
  }).join('');
}

/* ══════════════════════════════════════════════════════════
 * 数据加载
 * ══════════════════════════════════════════════════════════ */
export async function loadTools() {
  const grid = $id('tool-grid');
  if (grid) grid.innerHTML = '<div style="color:var(--ml-text-faint);font-size:13px;padding:40px;text-align:center">加载中…</div>';

  let d = null;
  try {
    d = await jget('/api/tools');
  } catch (e) {
    d = null;
  }
  if (!d || !d.ok) {
    if (grid) grid.innerHTML = '<div style="color:var(--ml-danger);font-size:13px;padding:40px;text-align:center">工具目录加载失败，请确认服务已启动</div>' +
      '<div style="text-align:center;margin-top:10px"><button class="btn btn-ghost btn-sm" id="btn-tools-retry">重试</button></div>';
    const rb = $id('btn-tools-retry'); if (rb) rb.onclick = () => loadTools();
    return;
  }

  // 技能目录独立请求：失败不影响工具展示
  let skills = [];
  try {
    const s = await jget('/api/tools/skills');
    if (s && s.ok) skills = s.skills || [];
  } catch (e) { /* 技能端点不可用时静默降级 */ }

  const gen = d.general || {};
  TOOL_DATA = { material: d.material || [], general: gen, skills };
  setToolData(TOOL_DATA);

  // 副标题：用后端 totals（已去重的真实数字）
  const sub = $id('tool-subtitle');
  if (sub) {
    const t = d.totals || { material: d.material_count, general: gen.count };
    sub.textContent = '材料 ' + (t.material || 0) + ' 个 · 通用 ' + (t.general || 0) +
      ' 个' + (gen.available ? '（当前可用 ' + gen.available + '）' : '') +
      ' · 技能 ' + skills.length + ' 个';
  }

  // 分类标签（后端动态下发，避免前端写死）
  const tags = $id('tool-tags');
  if (tags) {
    const cats = ['全部'].concat(d.categories || []);
    if (skills.length) cats.push('全部技能');
    tags.innerHTML = cats.map(c =>
      '<span class="tag' + (c === TOOL_FILTER.cat ? ' active' : '') + '" data-cat="' + esc(c) + '">' +
      esc(c) + '</span>').join('') +
      '<label class="tw-avail" title="只显示当前真有 key / 服务可调用的工具"><input type="checkbox" id="tool-avail"' +
      (TOOL_FILTER.onlyAvailable ? ' checked' : '') + '> 仅可用</label>';
  }

  // 侧栏统计
  const ts = $id('tools-side');
  if (ts) {
    const catRows = (gen.categories || []).slice(0, 6).map(c =>
      '<div class="ps-stat"><span>' + esc(c.cn) + '</span><b>' + c.count + '</b></div>').join('');
    const skillRows = Object.entries(
      (skills.reduce((a, s) => { a[s.scope] = (a[s.scope] || 0) + 1; return a; }, {}))
    ).map(([k, v]) => '<div class="ps-stat"><span>技能 · ' + esc(k) + '</span><b>' + v + '</b></div>').join('');
    ts.innerHTML =
      psCard('能力统计', 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z',
        '<div class="ps-stat"><span>材料科研工具</span><b>' + (d.totals ? d.totals.material : d.material_count) + '</b></div>' +
        '<div class="ps-stat"><span>通用能力</span><b>' + (d.totals ? d.totals.general : gen.count) + '</b></div>' +
        '<div class="ps-stat"><span>技能</span><b>' + skills.length + '</b></div>' +
        (catRows ? '<div class="ps-sec">通用能力分类</div>' + catRows : '') +
        (skillRows ? '<div class="ps-sec">技能来源</div>' + skillRows : '')) +
      psCard('使用说明', 'M12 8v4M12 16h.01',
        '<div style="font-size:12px;line-height:1.9;color:var(--ml-text-dim)">' +
        '· 点任意卡片<b>查看详情</b>：参数、示例、来源<br>' +
        '· 点「复制工具名」到智能对话中调用<br>' +
        '· 技能库：agent 新装/自更新的 skill <b>自动出现</b>在此<br>' +
        '<span style="color:var(--ml-text-faint);font-size:11px">材料工具由插件注册；通用能力来自 Agent 核心（已按可调用性过滤）。</span>' +
        '</div>');
  }

  renderToolGrid();
}

/* ══════════════════════════════════════════════════════════
 * 技能与连接器查看器（弹窗全量清单）
 * ══════════════════════════════════════════════════════════ */
/** 渲染一条工具/技能条目。
 *  可点击 → 打开详情抽屉填参执行（2026-10-16 重做：此前是无样式的纯文本，
 *  且完全不可点，用户只能复制工具名去手敲）。 */
function _tcItemHtml(t, kind) {
  const cn = t.cn || t.name;
  const name = t.name || '';
  const desc = t.desc_cn || t.desc || '（无描述）';
  const avail = t.available !== false;
  const cls = kind === 'skill' ? 'skill' : (kind === 'general' ? 'general' : 'material');
  const icon = t.emoji || (kind === 'skill' ? 'S' : (kind === 'general' ? 'G' : (cn[0] || 'T')));
  const tags = [];
  const cat = t.category_cn || t.cat;
  if (cat) tags.push('<span class="tc-tag">' + esc(cat) + '</span>');
  const nParams = (t.params_detail || []).length;
  if (nParams) tags.push('<span class="tc-tag">' + nParams + ' 参数</span>');
  if (!avail) tags.push('<span class="tc-tag off">不可用</span>');
  return '<div class="tc-item' + (avail ? '' : ' is-disabled') + '" data-name="' + esc(name) +
      '" data-kind="' + kind + '" role="button" tabindex="0"' +
      ' title="' + esc(cn + ' · ' + name) + '">' +
    '<span class="tc-ic ' + cls + '">' + esc(icon) + '</span>' +
    '<div class="tc-info">' +
      '<div class="tc-name">' + esc(cn) + (name ? '<span>' + esc(name) + '</span>' : '') + '</div>' +
      '<div class="tc-desc">' + esc(desc) + '</div>' +
      (tags.length ? '<div class="tc-tags">' + tags.join('') + '</div>' : '') +
    '</div>' +
    (avail ? '<span class="tc-go">打开 ›</span>' : '') +
  '</div>';
}

export async function openToolCatalog() {
  const mask = $id('tool-cat-mask');
  if (!mask) { toast('工具目录未挂载（页面结构缺失）', 'err'); return; }
  const body = $id('tc-body');
  if (!body) { toast('工具目录内容区缺失', 'err'); return; }
  mask.classList.add('show');
  body.innerHTML = '<div style="padding:30px;text-align:center;color:var(--ml-text-faint)">加载中…</div>';
  try {
    const [d, s] = await Promise.all([
      fetch('/api/tools').then(r => r.json()),
      fetch('/api/tools/skills').then(r => r.json()).catch(() => ({ skills: [] })),
    ]);
    const gen = d.general || {};
    const skills = s.skills || [];
    if ($id('tc-sub')) {
      $id('tc-sub').textContent = (d.totals ? d.totals.all : ((d.material || []).length + (gen.count || 0))) +
        ' 个条目 · 技能 ' + skills.length + ' 个';
    }
    let html = '';
    const mat = d.material || [];
    const gitems = gen.items || [];
    html += '<div class="tc-sec-title">🧪 材料科研工具<span class="tc-sec-count">' + mat.length + '</span></div>';
    html += '<div class="tc-list">' +
      (mat.length ? mat.map(t => _tcItemHtml(t, 'material')).join('')
        : '<div class="tc-empty">暂无材料工具</div>') + '</div>';
    html += '<div class="tc-sec-title">🤖 通用能力<span class="tc-sec-count">' + (gitems.length) + '</span></div>';
    html += '<div class="tc-list">' +
      (gitems.length ? gitems.map(t => _tcItemHtml(t, 'general')).join('')
        : '<div class="tc-empty">暂无通用能力</div>') + '</div>';
    if (skills.length) {
      html += '<div class="tc-sec-title">🎓 技能<span class="tc-sec-count">' + skills.length + '</span></div>';
      html += '<div class="tc-list">' + skills.map(x => _tcItemHtml(x, 'skill')).join('') + '</div>';
    }
    html += '<div class="tc-run-hint">点任意条目 → 填参数 → 「发送到对话框」，Agent 即可执行</div>';
    body.innerHTML = html;

    // 事件委托：点条目开详情抽屉
    const onOpen = (e) => {
      const tile = e.target.closest('.tc-item');
      if (!tile || tile.classList.contains('is-disabled')) return;
      const name = tile.getAttribute('data-name');
      const kind = tile.getAttribute('data-kind');
      const src = kind === 'skill'
        ? (skills || [])
        : (kind === 'general'
            ? (gitems || [])
            : (mat || []));
      const hit = src.find(x => (x.name || '') === name);
      if (hit) {
        // 关掉目录，让详情抽屉在前
        closeToolCatalog();
        _openDrawer(hit);
      }
    };
    body.onclick = onOpen;
    body.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(e); } };
  } catch (e) {
    body.innerHTML = '<div style="padding:30px;text-align:center;color:var(--ml-danger)">加载失败：' + esc(e.message) + '</div>';
  }
}

export function closeToolCatalog() {
  const mask = $id('tool-cat-mask'); if (mask) mask.classList.remove('show');
}

/* ══════════════════════════════════════════════════════════
 * 事件绑定
 * ══════════════════════════════════════════════════════════ */
export function bindToolsPage() {
  const tSearch = $id('tool-search');
  if (tSearch) tSearch.addEventListener('input', e => {
    TOOL_FILTER.q = e.target.value.trim().toLowerCase();
    renderToolGrid();
  });

  const tTags = $id('tool-tags');
  if (tTags) {
    tTags.addEventListener('click', e => {
      const av = e.target.closest('#tool-avail');
      if (av) { TOOL_FILTER.onlyAvailable = av.checked; renderToolGrid(); return; }
      const tag = e.target.closest('.tag');
      if (!tag) return;
      tTags.querySelectorAll('.tag').forEach(x => x.classList.remove('active'));
      tag.classList.add('active');
      TOOL_FILTER.cat = tag.getAttribute('data-cat');
      renderToolGrid();
    });
  }

  const tGrid = $id('tool-grid');
  if (tGrid) {
    const open = e => {
      const tile = e.target.closest('.tool-tile');
      if (!tile) return;
      const name = tile.getAttribute('data-name');
      const kind = tile.getAttribute('data-kind');
      const src = kind === 'skill'
        ? (TOOL_DATA.skills || [])
        : (TOOL_DATA.material || []).concat((TOOL_DATA.general && TOOL_DATA.general.items) || []);
      const hit = src.find(x => x.name === name);
      if (hit) _openDrawer(hit);
    };
    tGrid.addEventListener('click', open);
    tGrid.addEventListener('keydown', e => { if (e.key === 'Enter') open(e); });
  }

  // 抽屉遮罩点击关闭 + 关闭按钮
  const dm = $id('tool-detail-mask');
  if (dm) dm.addEventListener('click', e => { if (e.target === dm) closeToolDrawer(); });
  const xb = $id('tw-close');
  if (xb) xb.onclick = e => { e.stopPropagation(); closeToolDrawer(); };

  // ESC 关闭
  if (!bindToolsPage._escBound) {
    bindToolsPage._escBound = true;
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeToolDrawer(); });
  }
}
