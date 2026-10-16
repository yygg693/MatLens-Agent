/* ═══════════════════════════════════════════════════════════════
 * MatLens 设置页 · 网络隐私（proxy / Tor 换 IP）
 *
 * 设计要点：
 *  1. **状态先行**。这块设置最怕「以为已经匿名了」。面板顶部常驻一张状态卡，
 *     明确显示：当前走不走代理、直连出口 IP 是多少、经代理出口 IP 是多少。
 *     两个 IP 不同才算真的被保护。
 *  2. **不假装成功**。换 IP 失败（Tor 没跑）、代理未生效（出口 IP 没变），
 *     都如实标红并给出原因，绝不显示成「已完成」。
 *  3. **自动/手动同一套机制**。手动按钮与自动轮换走的是同一个后端
 *     Tor NEWNYM 信号，不存在「手动是假功能」的可能。
 * ═══════════════════════════════════════════════════════════════ */
import { $id, esc, toast, jget, jput, jpost } from './core.js';

const SEC = 'network';
let _npCfg = null;          // 后端返回的配置 + 轮换状态
let _npLoaded = false;

/* ── 保存 ────────────────────────────────────────────── */
async function _npSave(patch) {
  const body = {};
  body[SEC] = patch;
  try {
    const r = await jput('/api/config', body);
    return r || {};
  } catch (e) {
    toast('保存失败：' + (e.message || e), 'err');
    return null;
  }
}

function _npPatchFromInputs() {
  return {
    proxy_enabled: !!$id('np-enabled').classList.contains('on'),
    proxy_url: ($id('np-proxy-url').value || '').trim(),
    tor_control: ($id('np-tor-control').value || '').trim(),
    rotate_enabled: !!$id('np-rotate-enabled').classList.contains('on'),
    rotate_every: parseInt($id('np-rotate-every').value || '0', 10) || 0,
    rotate_max_requests: parseInt($id('np-rotate-max').value || '0', 10) || 0,
  };
}

/* ── 加载面板 ────────────────────────────────────────── */
export async function loadNetworkPane() {
  if (!_npLoaded) {
    _npLoaded = true;
    _npBind();
  }
  // 配置与检测**并发**发起：proxy-check 本身要 3-4s（要探测直连与代理两个出口），
  // 若串行等待会明显卡住面板首屏；两者互不依赖。
  await Promise.all([_npFetchConfig(), _npRefreshStatus(), _npLoadBlocked()]);
}

async function _npFetchConfig() {
  let d = null;
  try { d = await jget('/api/web/proxy/config'); } catch (e) { d = null; }
  if (!d) { _npSetStatus('bad', '读取配置失败，请确认服务已启动'); return; }
  _npCfg = d;
  const c = (d && d.config) || {};
  const en = $id('np-enabled'); if (en) en.classList.toggle('on', !!c.enabled);
  const pu = $id('np-proxy-url'); if (pu && document.activeElement !== pu) pu.value = c.url || '';
  const tc = $id('np-tor-control'); if (tc && document.activeElement !== tc) tc.value = c.tor_control || '';
  const re = $id('np-rotate-enabled'); if (re) re.classList.toggle('on', !!c.rotate_enabled);
  const rv = $id('np-rotate-every'); if (rv && document.activeElement !== rv) rv.value = c.rotate_every != null ? c.rotate_every : 30;
  const rm = $id('np-rotate-max'); if (rm && document.activeElement !== rm) rm.value = c.rotate_max_requests != null ? c.rotate_max_requests : 50;
  _npRenderRotate(d.rotate);
}

function _npSetStatus(cls, text) {
  const box = $id('np-status');
  const dot = $id('np-dot');
  const txt = $id('np-status-txt');
  if (box) box.className = 'np-status' + (cls ? ' ' + cls : '');
  if (dot) dot.className = 'np-dot' + (cls ? ' ' + cls : '');
  if (txt) txt.textContent = text;
}

function _npShowIPs(direct, via) {
  const row = $id('np-ip-row');
  if (!row) return;
  row.style.display = '';
  const dEl = $id('np-ip-direct');
  const pEl = $id('np-ip-proxy');
  if (dEl) dEl.textContent = direct || '获取失败';
  if (pEl) {
    pEl.textContent = via || '获取失败';
    const box = pEl.parentElement;
    if (box) box.classList.toggle('alt', !!via && via !== direct);
  }
}

/** 实测出口 IP：这是「有没有被保护」的唯一事实依据。 */
let _npCheckSeq = 0;   // 请求序号：丢弃过期响应，避免先发后到的旧响应覆盖新状态

export async function _npRefreshStatus() {
  const seq = ++_npCheckSeq;
  _npSetStatus('wait', '正在检测出口 IP…');
  let r = null;
  try { r = await jget('/api/web/proxy-check'); } catch (e) { r = null; }
  // 期间用户可能又触发了一次检测（耗时可达十几秒），过期的直接丢弃，
  // 否则状态卡会停在「检测中」或显示上一次的过期结果
  if (seq !== _npCheckSeq) return;
  if (!r) { _npSetStatus('bad', '检测失败：服务未响应'); return; }

  _npShowIPs(r.direct_ip || '', r.proxy_ip || '');
  if (r.proxy_configured) {
    if (!r.ok) {
      _npSetStatus('bad', '代理不可用：' + (r.error || '未知错误') +
        (r.advice ? '。' + r.advice : ''));
    } else if (r.protected) {
      _npSetStatus('ok', '出口 IP 已改变，隐私保护生效。目标站点看到的是代理 IP（' +
        (r.proxy_ip || '') + '），不是你的本机 IP。');
    } else {
      _npSetStatus('bad', '⚠️ 出口 IP 与直连相同，代理未实际生效，你仍在裸奔。' +
        (r.advice ? ' ' + r.advice : ''));
    }
  } else {
    _npSetStatus('', '未启用代理：目标站点看到的是你的本机出口 IP（' +
      (r.direct_ip || '未知') + '）。需要隐藏 IP 请开启代理并填入 Tor 地址。');
  }
  _npRenderRotate(null);
}

function _npRenderRotate(rot) {
  const el = $id('np-rotstat');
  if (!el) return;
  const r = rot || (_npCfg && _npCfg.rotate) || null;
  if (!r) { el.textContent = '轮换状态未知'; return; }
  const bits = [];
  bits.push('自动换 IP ' + (r.rotate_enabled ? '已开启' : '未开启'));
  bits.push('本次请求 <b>' + (r.requests_since_rotate || 0) + '</b> 次');
  if (r.seconds_since_rotate >= 0) {
    bits.push('距上次换 IP <b>' + (r.seconds_since_rotate || 0) + '</b> s');
  } else {
    bits.push('尚未换过 IP');
  }
  if (r.due) bits.push('· <span style="color:var(--ml-warn)">待轮换：' + (r.due_reason || '') + '</span>');
  const last = r.last_result || {};
  if (last.ok) bits.push('· 上次换 IP 成功');
  else if (last.reason) bits.push('· 上次失败：' + (last.reason || '').slice(0, 60));
  el.innerHTML = bits.join(' · ');
}

/** 立即换 IP（Tor NEWNYM）。 */
export async function _npRotateNow() {
  if (_npCfg && !_npCfg.in_use) {
    toast('请先启用代理并填入 Tor 地址', 'err');
    return;
  }
  const btn = $id('np-btn-rotate');
  if (btn) { btn.disabled = true; btn.textContent = '请求中…'; }
  try {
    const r = await jpost('/api/web/proxy/rotate', {});
    if (r && r.ok) {
      toast('已请求新出口 IP。' + (r.note || '几秒后点「测试连接」确认是否生效'), 'ok');
    } else if (r && r.skipped) {
      toast('暂不能换：' + (r.reason || ''), 'err');
    } else {
      toast('换 IP 失败：' + ((r && (r.reason || r.error)) || '未知错误'), 'err');
    }
    if (r && r.status) { _npCfg.rotate = r.status; _npRenderRotate(r.status); }
    else await _npRefreshStatus();
  } catch (e) {
    toast('换 IP 失败：' + (e.message || e), 'err');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '立即换 IP'; }
  }
}

async function _npLoadBlocked() {
  const box = $id('np-blocked-list');
  if (!box) return;
  try {
    const d = await jget('/api/web/blocked-sites');
    const sites = (d && d.sites) || [];
    if (!sites.length) { box.textContent = '（无）'; return; }
    box.innerHTML = '<div style="margin-bottom:7px">以下 <b>' + sites.length +
      '</b> 个站点在代码层面禁止抓取（拦截发生在 robots 检查之前，' +
      '因服务条款效力高于 robots 文件）：</div>' +
      sites.map(s => '<div style="margin:5px 0"><span class="np-host">' +
        esc(s.host) + '</span><span class="np-why">' + esc((s.reason || '').slice(0, 90)) +
        '</span></div>').join('');
  } catch (e) {
    box.textContent = '读取失败';
  }
}

/* ── 事件绑定 ────────────────────────────────────────── */
function _npBind() {
  const bindToggle = (id, key, label) => {
    const el = $id(id);
    if (!el) return;
    el.onclick = async () => {
      el.classList.toggle('on');
      const v = el.classList.contains('on');
      const r = await _npSave({ [key]: v });
      if (r === null) { el.classList.toggle('on'); return; }
      toast((v ? '已开启' : '已关闭') + label, v ? 'ok' : 'err');
      await _npRefreshStatus();
    };
  };
  bindToggle('np-enabled', 'proxy_enabled', '代理');
  bindToggle('np-rotate-enabled', 'rotate_enabled', '自动换 IP');

  const bindInput = (id, key) => {
    const el = $id(id);
    if (!el) return;
    const handler = async () => {
      const patch = _npPatchFromInputs();
      await _npSave({ [key]: patch[key] });
      await _npRefreshStatus();
    };
    el.onchange = handler;
    if (el.tagName === 'INPUT') {
      el.onkeydown = (e) => { if (e.key === 'Enter') { el.blur(); } };
    }
  };
  bindInput('np-proxy-url', 'proxy_url');
  bindInput('np-tor-control', 'tor_control');
  bindInput('np-rotate-every', 'rotate_every');
  bindInput('np-rotate-max', 'rotate_max_requests');

  const ck = $id('np-btn-check'); if (ck) ck.onclick = () => _npRefreshStatus();
  const rt = $id('np-btn-rotate'); if (rt) rt.onclick = () => _npRotateNow();
  const rs = $id('np-btn-rotstatus'); if (rs) rs.onclick = () => _npRefreshStatus();

  const pv = $id('np-btn-privacy');
  if (pv) pv.onclick = async () => {
    try {
      const d = await jget('/api/web/privacy');
      const h = (d && d.http_layer && d.http_layer.blocked) || [];
      const n = (d && d.network_layer && d.network_layer.reality) || '';
      toast('已阻断 ' + h.length + ' 项 HTTP 层追踪向量；' +
        (n ? 'IP 属于网络层，代码改不掉，需代理。' : ''), 'ok');
    } catch (e) { toast('读取失败', 'err'); }
  };
  const bl = $id('np-btn-blocked');
  if (bl) bl.onclick = () => _npLoadBlocked();
}
