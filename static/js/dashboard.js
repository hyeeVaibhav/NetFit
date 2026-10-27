'use strict';
(async () => {
  const m = await Data.metrics();
  const row = $('#kpiRow');
  if (!m || !m.models || !m.models.ann) {
    emptyState(row, 'Model evaluation (metrics.json) is not available yet.');
    emptyState($('#chartMetrics').parentElement, 'No metrics to chart.');
    emptyState($('#chartBalance').parentElement, 'No dataset summary.');
    return;
  }
  const a = m.models.ann.metrics;
  const kpi = (label, value, note, tone = '') =>
    `<div class="col-6 col-md-4 col-xl"><div class="card-x kpi ${tone}"><div class="label">${label}</div><div class="value">${value}</div><div class="note">${note}</div></div></div>`;
  row.innerHTML =
    kpi('ANN recall', fmtPct(a.recall, 1), `caught ${fmtInt(a.tp)} of ${fmtInt(a.tp + a.fn)} attacks`, 'good') +
    kpi('ANN precision', fmtPct(a.precision, 1), `${fmtInt(a.fp)} false alarms`, 'warn') +
    kpi('ANN F1 score', fmtPct(a.f1, 1), 'balance of both') +
    kpi('ANN accuracy', fmtPct(a.accuracy, 1), 'misleading alone') +
    kpi('Attacks missed', fmtInt(a.fn), `ANN, threshold ${a.threshold.toFixed(2)}`, a.fn ? 'bad' : 'good');
  Charts.metricBars('chartMetrics', m);
  if (m.dataset && m.dataset.label_counts) Charts.classBalance('chartBalance', m.dataset);
})();
