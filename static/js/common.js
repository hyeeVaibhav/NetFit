/* common.js - helpers shared by every page */
'use strict';

const MODEL_ORDER = ['logistic_regression', 'logistic_regression_balanced', 'ann', 'random_forest'];
const MODEL_COLORS = {
  logistic_regression: '#8e99a6', logistic_regression_balanced: '#3b82f6',
  ann: '#ef4444', random_forest: '#16a34a', ann_tuned: '#8b5cf6',
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const fmtInt = (n) => (n === null || n === undefined || isNaN(n)) ? '-' : Number(n).toLocaleString('en-US');
const fmtPct = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? '-' : (v * 100).toFixed(d) + '%';
const fmtNum = (v, d = 4) => (v === null || v === undefined || isNaN(v)) ? '-' : Number(v).toFixed(d);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** fetch JSON; on failure throw an Error whose message is the server's explanation and whose .details is a list. */
async function api(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    const err = new Error('Could not reach the server. Is the app still running?');
    err.details = [];
    throw err;
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok || (data && data.ok === false)) {
    const err = new Error((data && data.error) || `Request failed (${res.status})`);
    err.details = (data && data.details) || [];
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(message, kind = '') {
  const stack = $('#toastStack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = 'toast-x ' + kind;
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function skeleton(el, h = 120) { if (el) el.innerHTML = `<div class="skeleton" style="height:${h}px"></div>`; }

/** theme toggle + mobile menu */
document.addEventListener('DOMContentLoaded', () => {
  const t = $('#themeToggle');
  if (t) t.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-bs-theme', next);
    try { localStorage.setItem('nids-theme', next); } catch (e) { /* private mode */ }
    document.dispatchEvent(new CustomEvent('themechange'));
  });
  const m = $('#menuBtn'), s = $('#sidebar');
  if (m && s) {
    m.addEventListener('click', () => s.classList.toggle('open'));
    document.addEventListener('click', (e) => { if (!s.contains(e.target) && e.target !== m) s.classList.remove('open'); });
  }
});

/** load /api/metrics and /api/curves once per page; resolves null for a missing file instead of throwing */
const Data = {
  _m: null, _c: null,
  async metrics() { if (!this._m) { try { this._m = await api('/api/metrics'); } catch (e) { this._m = null; } } return this._m; },
  async curves() { if (!this._c) { try { this._c = await api('/api/curves'); } catch (e) { this._c = null; } } return this._c; },
};

function modelName(metrics, key) {
  const e = metrics && metrics.models && metrics.models[key];
  return (e && e.name) || key;
}

function emptyState(el, text) {
  if (el) el.innerHTML = `<div class="text-center text-secondary py-5">${esc(text)}</div>`;
}

function confusionHtml(cm) {
  // cm = [[tn, fp], [fn, tp]] ; colour intensity follows the share of each row
  const [[tn, fp], [fn, tp]] = cm;
  const r0 = (tn + fp) || 1, r1 = (fn + tp) || 1;
  const cell = (v, share, good, label) =>
    `<div class="cell ${good ? 'good' : 'badc'}" style="--a:${(0.12 + 0.55 * share).toFixed(2)}"><b>${fmtInt(v)}</b><span>${label} · ${fmtPct(share, 1)} of row</span></div>`;
  return `<div class="cm">
    <div></div><div class="h">Predicted<br>Normal</div><div class="h">Predicted<br>Attack</div>
    <div class="h">Actual<br>Normal</div>${cell(tn, tn / r0, true, 'correct')}${cell(fp, fp / r0, false, 'false alarm')}
    <div class="h">Actual<br>Attack</div>${cell(fn, fn / r1, false, 'MISSED')}${cell(tp, tp / r1, true, 'caught')}
  </div>`;
}
