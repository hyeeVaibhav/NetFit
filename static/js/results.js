'use strict';
(() => {
  const run = JSON.parse($('#runData').textContent);
  const s = run.summary;
  const id = run.id;

  // ---------------------------------------------------------------- KPIs
  const kpi = (label, value, note, tone = '') =>
    `<div class="col-6 col-md-3"><div class="card-x kpi ${tone}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div></div>`;
  let html = kpi('Flows scanned', fmtInt(s.n_rows), 'rows in your file') +
    kpi('Flagged as attack', fmtInt(s.n_attack), fmtPct(s.attack_rate, 2) + ' of flows', s.n_attack ? 'bad' : 'good') +
    kpi('Normal', fmtInt(s.n_normal), fmtPct(1 - s.attack_rate, 2) + ' of flows', 'good') +
    kpi('Mean attack probability', fmtNum(s.mean_probability, 3), 'across all flows');
  if (s.has_labels) {
    const l = s.labels;
    html += kpi('Recall', fmtPct(l.recall, 1), `caught ${fmtInt(l.tp)} of ${fmtInt(l.tp + l.fn)} real attacks`, 'good') +
      kpi('Precision', fmtPct(l.precision, 1), `${fmtInt(l.fp)} false alarms`, 'warn') +
      kpi('Accuracy', fmtPct(l.accuracy, 1), `F1 ${fmtPct(l.f1, 1)}`) +
      kpi('Attacks missed', fmtInt(l.fn), 'false negatives', l.fn ? 'bad' : 'good');
  }
  $('#kpis').innerHTML = html;

  // ---------------------------------------------------------------- charts
  Charts.donut('chVerdict', ['Normal', 'Attack'], [s.n_normal, s.n_attack], ['#3b82f6', '#ef4444']);
  Charts.probHist('chHist', s.histogram);
  const rc = s.risk_counts || {};
  const bands = ['High', 'Medium', 'Low'].filter((b) => rc[b]);
  if (bands.length) Charts.simpleBars('chRisk', bands, bands.map((b) => rc[b]), ['#dc2626', '#f59e0b', '#3b82f6'], 'flows');
  else emptyState($('#chRisk').parentElement, 'No flows were flagged.');
  if ((s.top_ports || []).length) Charts.simpleBars('chPorts', s.top_ports.map((p) => 'port ' + p.value), s.top_ports.map((p) => p.count), '#ef4444', 'flagged flows');
  else emptyState($('#chPorts').parentElement, 'No flagged flows to summarise.');

  // ---------------------------------------------------------------- labelled evaluation
  if (s.has_labels) {
    const l = s.labels;
    $('#labelCard').classList.remove('d-none');
    $('#cmBox').innerHTML = confusionHtml([[l.tn, l.fp], [l.fn, l.tp]]);
    $('#labelStats').innerHTML =
      `Accuracy <b>${fmtPct(l.accuracy)}</b> · Precision <b>${fmtPct(l.precision)}</b> · Recall <b>${fmtPct(l.recall)}</b> · ` +
      `F1 <b>${fmtPct(l.f1)}</b> · False alarm rate <b>${fmtPct(l.fpr)}</b> · Miss rate <b>${fmtPct(l.fnr)}</b>`;
    if ((s.by_attack_type || []).length) {
      $('#typeCard').classList.remove('d-none');
      $('#typeTable').innerHTML = '<thead><tr><th>Attack type</th><th class="text-end">Flows</th><th class="text-end">Detected</th><th class="text-end">Recall</th></tr></thead><tbody>' +
        s.by_attack_type.map((t) => `<tr><td>${esc(t.attack_type)}</td><td class="text-end mono">${fmtInt(t.count)}</td>
        <td class="text-end mono">${fmtInt(t.detected)}</td><td class="text-end mono">${fmtPct(t.recall, 1)}</td></tr>`).join('') + '</tbody>';
    }
  }

  // ---------------------------------------------------------------- what-if threshold
  const wr = $('#wiRange'); let timer = null;
  async function whatIf() {
    $('#wiVal').textContent = Number(wr.value).toFixed(2);
    try {
      const r = await api(`/api/runs/${id}/threshold?value=${wr.value}`);
      const tile = (v, l) => `<div class="col-4 col-lg"><div class="stat"><b>${v}</b><span>${l}</span></div></div>`;
      let h = tile(fmtInt(r.n_attack), 'flagged as attack') + tile(fmtPct(r.attack_rate, 2), 'of all flows');
      if (r.labels) h += tile(fmtInt(r.labels.fn), 'attacks missed') + tile(fmtInt(r.labels.fp), 'false alarms') +
        tile(fmtPct(r.labels.recall, 1), 'recall') + tile(fmtPct(r.labels.precision, 1), 'precision');
      $('#wiStats').innerHTML = h;
    } catch (e) { toast(e.message, 'err'); }
  }
  wr.addEventListener('input', () => { clearTimeout(timer); $('#wiVal').textContent = Number(wr.value).toFixed(2); timer = setTimeout(whatIf, 120); });
  whatIf();

  // ---------------------------------------------------------------- table
  let page = 1, pages = 1;
  const NICE = { row_id: '#', IPV4_SRC_ADDR: 'Src IP', IPV4_DST_ADDR: 'Dst IP', L4_SRC_PORT: 'Src port', L4_DST_PORT: 'Dst port',
    PROTOCOL: 'Proto', IN_BYTES: 'In bytes', OUT_BYTES: 'Out bytes', TCP_FLAGS: 'Flags', FLOW_DURATION_MILLISECONDS: 'Duration ms',
    Label: 'True label', Attack: 'Attack type', P_attack: 'P(attack)', Verdict: 'Verdict', Confidence: 'Confidence', Risk: 'Risk' };

  function cellHtml(col, v) {
    if (v === null || v === undefined) return '<span class="text-secondary">-</span>';
    switch (col) {
      case 'Verdict': return `<span class="badge ${v === 'Attack' ? 'badge-attack' : 'badge-normal'}">${esc(v)}</span>`;
      case 'Risk': return v === '-' ? '<span class="text-secondary">-</span>' : `<span class="risk-${esc(v)}">${esc(v)}</span>`;
      case 'P_attack': return `<span class="mono">${Number(v).toFixed(4)}</span>`;
      case 'Confidence': {
        const pct = Math.round(v * 100);
        const color = v >= 0.9 ? '#16a34a' : (v >= 0.7 ? '#f59e0b' : '#94a3b8');
        return `<div class="d-flex align-items-center gap-2"><div class="conf-bar flex-grow-1"><span style="width:${pct}%;background:${color}"></span></div><span class="mono small">${pct}%</span></div>`;
      }
      case 'Label': return v === 1 ? 'Attack' : (v === 0 ? 'Normal' : esc(v));
      case 'IN_BYTES': case 'OUT_BYTES': case 'FLOW_DURATION_MILLISECONDS': return `<span class="mono">${fmtInt(v)}</span>`;
      default: return esc(v);
    }
  }

  async function loadRows() {
    const q = new URLSearchParams({ page, size: $('#fSize').value, filter: $('#fFilter').value, sort: $('#fSort').value, q: $('#fSearch').value });
    const t = $('#rowsTable'); skeleton(t, 160);
    try {
      const d = await api(`/api/runs/${id}/rows?${q}`);
      pages = d.pages; page = Math.min(page, pages);
      const li = d.columns.indexOf('Label'), vi = d.columns.indexOf('Verdict');
      t.innerHTML = '<thead><tr>' + d.columns.map((c) => `<th>${NICE[c] || c}</th>`).join('') + '</tr></thead><tbody>' +
        (d.rows.length ? d.rows.map((r) => {
          const wrong = li >= 0 && vi >= 0 && ((r[li] === 1) !== (r[vi] === 'Attack'));
          return `<tr${wrong ? ' style="background:rgba(220,38,38,.09)" title="prediction differs from the Label column"' : ''}>` +
            r.map((v, i) => `<td>${cellHtml(d.columns[i], v)}</td>`).join('') + '</tr>';
        }).join('') : `<tr><td colspan="${d.columns.length}" class="text-center text-secondary py-4">No flows match these filters.</td></tr>`) + '</tbody>';
      $('#pageInfo').textContent = `${fmtInt(d.total)} flows · page ${d.page} of ${fmtInt(d.pages)}`;
      $('#prevBtn').disabled = d.page <= 1; $('#nextBtn').disabled = d.page >= d.pages;
    } catch (e) { emptyState(t, e.message); }
  }
  let st = null;
  ['fFilter', 'fSort', 'fSize'].forEach((x) => $('#' + x).addEventListener('change', () => { page = 1; loadRows(); }));
  $('#fSearch').addEventListener('input', () => { clearTimeout(st); st = setTimeout(() => { page = 1; loadRows(); }, 300); });
  $('#prevBtn').addEventListener('click', () => { if (page > 1) { page--; loadRows(); } });
  $('#nextBtn').addEventListener('click', () => { if (page < pages) { page++; loadRows(); } });
  loadRows();

  $('#delBtn').addEventListener('click', async () => {
    if (!confirm(`Delete run #${id} and its results file?`)) return;
    try { await api(`/api/runs/${id}`, { method: 'DELETE' }); location.href = '/history'; } catch (e) { toast(e.message, 'err'); }
  });
})();
