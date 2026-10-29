/* ═══════════════════════════════════════════════════════════════
 * MatLens · 源健康面板（2026-10-29）
 *
 * 解决什么：
 *   此前只能「用的时候才知道」某个源挂了 —— 用户勾 5 个源去搜，
 *   结果少了一半却不知道为什么少。本面板让状态**主动可见**。
 *
 * 设计取舍：
 *  - **不自动频繁探测**。自检是网络操作，会消耗免费 API 配额，
 *    也会拖慢首屏。故：进页面读缓存（10 分钟 TTL），用户点「立即检测」
 *    才强制刷新。
 *  - **失败原因分类展示**。「连接超时」和「配额耗尽」用户的处置完全不同，
 *    只说「不可用」等于没说。
 *  - **need_key 与 down 分开**。没配密钥不是源坏了，是用户还没配置。
 * ═══════════════════════════════════════════════════════════════ */
import { $id, esc, toast, jget, jpost } from './core.js';

const STATUS_LABEL = {
  ok: '可用',
  degraded: '降级',
  down: '不可用',
  need_key: '需密钥',
  off: '未启用',
};

let _health = null;         // {at, items, summary}
let _healthTimer = null;

export function initHealthPanel() {
  const btn = $id('btn-health-refresh');
  if (btn) {
    btn.onclick = () => refreshHealth(true);
  }
  // 进页面读缓存（后端 10 分钟 TTL，不会真的重新探测）
  loadHealth(false);
}

async function loadHealth(force) {
  const btn = $id('btn-health-refresh');
  if (btn) { btn.disabled = true; btn.textContent = force ? '检测中…' : '加载中…'; }
  try {
    const r = force
      ? await jpost('/api/kb/sources/health/refresh', {})
      : await jget('/api/kb/sources/health-all');
    _health = r;
    renderHealth();
  } catch (e) {
    _health = null;
    renderHealth(String(e.message || e));
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '立即检测'; }
  }
}

async function refreshHealth(force) {
  if (force) {
    toast('正在检测各源可用性…');
  }
  await loadHealth(force);
  if (force && _health) {
    const s = _health.summary || {};
    toast(`检测完成：可用 ${s.ok || 0} · 降级 ${s.degraded || 0} · `
        + `不可用 ${s.down || 0} · 需密钥 ${s.need_key || 0}`,
      (s.down || s.degraded) ? 'err' : 'ok');
  }
}

function _statusOf(id) {
  const items = (_health && _health.items) || {};
  return items[id] || null;
}

function renderHealth(errMsg) {
  const box = $id('kb-health');
  if (!box) return;

  if (errMsg) {
    box.innerHTML = '<div class="kb-health-head"><b>源健康</b>' +
      '<span class="kb-hs down">检测失败</span>' +
      '<span class="kb-health-msg">' + esc(errMsg) + '</span></div>';
    return;
  }
  if (!_health || !_health.items) {
    box.innerHTML = '<div class="kb-health-head"><b>源健康</b>' +
      '<span class="kb-hs">未检测</span></div>';
    return;
  }

  const s = _health.summary || {};
  const items = _health.items || {};
  const order = ['down', 'degraded', 'need_key', 'off', 'ok'];
  const rows = Object.keys(items)
    .sort((a, b) => order.indexOf(items[a].status) - order.indexOf(items[b].status))
    .map(id => {
      const v = items[id];
      const st = v.status || 'down';
      const msg = v.error || v.hint || '';
      const isBad = st === 'down';
      return '<div class="kb-hl" title="' + esc(v.label || id) + '">' +
        '<span class="kb-src-dot ' + esc(st) + '" style="margin-top:5px"></span>' +
        '<span class="kb-hl-name">' + esc(v.label || id) + '</span>' +
        '<span class="kb-hl-msg">' +
          (msg ? (isBad ? '<b>' + esc(msg) + '</b>' : esc(msg)) : STATUS_LABEL[st] || st) +
        '</span>' +
        '<span class="kb-hl-ms">' + (v.ms ? v.ms + 'ms' : '') + '</span>' +
        '</div>';
    }).join('');

  const when = _health.at
    ? new Date(_health.at * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    : '';

  box.innerHTML = '<div class="kb-health-head">' +
    '<b>源健康</b>' +
    '<span class="kb-health-sum">' +
      (s.ok ? '<span class="kb-hs ok">可用 ' + s.ok + '</span>' : '') +
      (s.degraded ? '<span class="kb-hs degraded">降级 ' + s.degraded + '</span>' : '') +
      (s.down ? '<span class="kb-hs down">不可用 ' + s.down + '</span>' : '') +
      (s.need_key ? '<span class="kb-hs need_key">需密钥 ' + s.need_key + '</span>' : '') +
      (s.off ? '<span class="kb-hs off">未启用 ' + s.off + '</span>' : '') +
    '</span>' +
    '<span class="kb-health-time">' + (when ? '检测于 ' + when : '') + '</span>' +
    '<button class="kb-health-btn" id="btn-health-refresh">立即检测</button>' +
    '</div>' +
    '<div class="kb-health-list">' + rows + '</div>';

  const rb = $id('btn-health-refresh');
  if (rb) rb.onclick = () => refreshHealth(true);

  syncDots();
}

/** 同步左栏各源的小圆点。
 *  ⚠️ 只在**左栏已渲染源目录**时才有 data-dot 元素 ——
 *    本地库模式下左栏是库列表，没有圆点，同步是空操作（不是 bug）。
 */
function syncDots() {
  document.querySelectorAll('[data-dot]').forEach(d => {
    const v = _statusOf(d.dataset.dot);
    if (!v) return;
    d.className = 'kb-src-dot ' + v.status;
    d.title = (v.label || d.dataset.dot) + '：' +
      (STATUS_LABEL[v.status] || v.status) +
      (v.ms ? ' · ' + v.ms + 'ms' : '') +
      (v.error ? ' · ' + v.error : (v.hint ? ' · ' + v.hint : ''));
  });
}

/** 供其它模块调用：取某源的健康状态（用于「这个源怎么没结果」提示）。 */
export function healthOf(sourceId) {
  return _statusOf(sourceId);
}

/** 左栏重新渲染后调用，把健康状态刷到新渲染的圆点上。
 *  切到「云端 API」模式时左栏才会渲染出源目录（带 data-dot），
 *  此时才需要重新同步（实测：本地库模式下没有圆点，同步是空操作）。
 */
export function resyncHealthDots() {
  syncDots();
}
