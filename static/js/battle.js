'use strict';
(async () => {
  const m = await Data.metrics();
  const table = $('#battleTable');

  // ------------------------------------------------------------------ saved evaluation table
  if (!m || !m.models) {
    emptyState(table, 'metrics.json is not available, so the saved comparison cannot be shown.');
    emptyState($('#bMetrics').parentElement, 'No metrics to chart.');
    emptyState($('#bMissed').parentElement, 'No metrics to chart.');
  } else {
    const keys = [...Charts.keysOf(m), ...(m.models.ann_tuned ? ['ann_tuned'] : [])];
    const cols = [
      { k: 'accuracy', t: 'Accuracy', best: 'max', f: (v) => fmtPct(v) },
      { k: 'precision', t: 'Precision', best: 'max', f: (v) => fmtPct(v) },
      { k: 'recall', t: 'Recall', best: 'max', f: (v) => fmtPct(v) },
      { k: 'f1', t: 'F1', best: 'max', f: (v) => fmtPct(v) },
      { k: 'fpr', t: 'False alarm rate', best: 'min', f: (v) => fmtPct(v) },
      { k: 'fn', t: 'Missed attacks', best: 'min', f: fmtInt },
      { k: 'fp', t: 'False alarms', best: 'min', f: fmtInt },
      { k: 'roc_auc', t: 'ROC-AUC', best: 'max', f: (v) => fmtNum(v, 4) },
      { k: 'pr_auc', t: 'PR-AUC', best: 'max', f: (v) => fmtNum(v, 4) },
    ];
    let sortKey = null, asc = false;
    const draw = () => {
      let rows = keys.slice();
      if (sortKey) rows.sort((a, b) => (m.models[a].metrics[sortKey] - m.models[b].metrics[sortKey]) * (asc ? 1 : -1));
      const best = {};
      cols.forEach((c) => {
        const vals = keys.map((k) => m.models[k].metrics[c.k]);
        best[c.k] = c.best === 'max' ? Math.max(...vals) : Math.min(...vals);
      });
      table.innerHTML = '<thead><tr><th>Model</th>' + cols.map((c) =>
        `<th role="button" data-sort="${c.k}" class="text-end">${c.t}${sortKey === c.k ? (asc ? ' ▲' : ' ▼') : ''}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map((k) => {
          const e = m.models[k], col = MODEL_COLORS[k];
          return `<tr><td><span class="d-inline-block rounded-circle me-2" style="width:10px;height:10px;background:${col}"></span><b>${esc(e.name)}</b></td>` +
            cols.map((c) => { const v = e.metrics[c.k];
              return `<td class="text-end mono ${v === best[c.k] ? 'best' : ''}">${c.f(v)}</td>`; }).join('') + '</tr>';
        }).join('') + '</tbody>';
    };
    table.addEventListener('click', (e) => {
      const th = e.target.closest('[data-sort]'); if (!th) return;
      if (sortKey === th.dataset.sort) asc = !asc; else { sortKey = th.dataset.sort; asc = false; }
      draw();
    });
    draw();
    Charts.metricBars('bMetrics', m);
    Charts.missedFalse('bMissed', m);
  }

  // ------------------------------------------------------------------ live battle
  let useSample = false;
  const fileIn = $('#bFile'), chosen = $('#bChosen'), errBox = $('#bError'), out = $('#bResult');
  fileIn.addEventListener('change', () => {
    useSample = false;
    chosen.textContent = fileIn.files[0] ? `${fileIn.files[0].name} (${(fileIn.files[0].size / 1024).toFixed(1)} KB)` : 'Nothing chosen yet.';
  });
  const sb = $('#bSample');
  if (sb) sb.addEventListener('click', () => { useSample = true; fileIn.value = ''; chosen.textContent = 'sample_flows.csv (bundled sample)'; });

  $('#bRun').addEventListener('click', async () => {
    errBox.classList.add('d-none');
    if (!useSample && !fileIn.files[0]) { errBox.textContent = 'Choose a CSV file or use the sample file first.'; errBox.classList.remove('d-none'); return; }
    const fd = new FormData();
    if (useSample) fd.append('sample', '1'); else fd.append('file', fileIn.files[0]);
    $$('[data-thr]').forEach((i) => fd.append('thr_' + i.dataset.thr, i.value));
    skeleton(out, 160);
    try {
      render(await api('/api/battle', { method: 'POST', body: fd }));
    } catch (e) {
      out.innerHTML = '';
      errBox.innerHTML = `<strong>${esc(e.message)}</strong>` + (e.details && e.details.length ? `<ul class="mb-0 mt-2 small">${e.details.map((d) => `<li>${esc(d)}</li>`).join('')}</ul>` : '');
      errBox.classList.remove('d-none');
    }
  });

  function render(r) {
    const hl = r.has_labels;
    let html = `<div class="small text-secondary mb-3">${fmtInt(r.n_rows)} flows from <b>${esc(r.filename)}</b>` +
      (hl ? ` · ${fmtInt(r.true_attacks)} are real attacks (from your Label column)` : ' · no valid Label column, so only the number flagged is shown') + '</div>';
    html += '<div class="row g-3">' + r.models.map((x) => {
      const mt = x.metrics;
      return `<div class="col-md-6 col-xl-3"><div class="card-x" style="border-top:4px solid ${MODEL_COLORS[x.key]}">
        <div class="fw-bold">${esc(x.name)}</div>
        <div class="text-secondary small mb-2">threshold ${x.threshold.toFixed(2)} · ${x.ms} ms</div>
        <div class="kpi"><div class="label">Flagged as attack</div><div class="value">${fmtInt(x.flagged)}</div><div class="note">${fmtPct(x.flag_rate, 2)} of flows</div></div>
        ${mt ? `<hr class="my-2"><div class="small">Missed attacks: <b class="text-danger">${fmtInt(mt.fn)}</b><br>False alarms: <b class="text-warning">${fmtInt(mt.fp)}</b><br>
          Recall <b>${fmtPct(mt.recall, 1)}</b> · Precision <b>${fmtPct(mt.precision, 1)}</b><br>F1 <b>${fmtPct(mt.f1, 1)}</b> · Accuracy <b>${fmtPct(mt.accuracy, 1)}</b></div>` : ''}
        </div></div>`;
    }).join('') + '</div>';
    if (hl && r.models.length) {
      const fewestMiss = r.models.reduce((a, b) => (b.metrics.fn < a.metrics.fn ? b : a));
      const fewestFalse = r.models.reduce((a, b) => (b.metrics.fp < a.metrics.fp ? b : a));
      html += `<div class="insight good mt-3"><h6>Result of this battle</h6><p>Fewest missed attacks: <b>${esc(fewestMiss.name)}</b> (${fmtInt(fewestMiss.metrics.fn)}).
        Fewest false alarms: <b>${esc(fewestFalse.name)}</b> (${fmtInt(fewestFalse.metrics.fp)}). These are counts on your file at the thresholds above.</p></div>`;
      html += '<div class="chart-box mt-3"><canvas id="bLive"></canvas></div>';
    }
    out.innerHTML = html;
    if (hl) Charts.draw('bLive', () => ({
      type: 'bar',
      data: { labels: r.models.map((x) => x.name), datasets: [
        { label: 'Attacks missed', data: r.models.map((x) => x.metrics.fn), backgroundColor: '#dc2626', borderRadius: 4 },
        { label: 'False alarms', data: r.models.map((x) => x.metrics.fp), backgroundColor: '#f59e0b', borderRadius: 4 } ] },
      options: { scales: { y: { beginAtZero: true } }, plugins: { valueLabels: { fmt: (v) => fmtInt(v) } } },
    }));
  }
})();
