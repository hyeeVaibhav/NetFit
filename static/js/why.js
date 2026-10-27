'use strict';
(async () => {
  const [m, c] = await Promise.all([Data.metrics(), Data.curves()]);

  /** run a drawing step; if its data is missing or it throws, show a clear message in that card instead of a blank box */
  const step = (id, ok, fn, msg) => {
    const el = document.getElementById(id); if (!el) return;
    const holder = el.closest('.chart-box') || el;
    if (!ok) return emptyState(holder, msg);
    try { fn(); } catch (e) { console.error(id, e); emptyState(holder, 'This chart could not be drawn: ' + e.message); }
  };
  const noM = 'metrics.json is not available.', noC = 'curves.json is not available.';

  step('cMetrics', m && m.models, () => Charts.metricBars('cMetrics', m), noM);
  step('cRecall', m && m.models, () => Charts.recallBars('cRecall', m), noM);
  step('cMissed', m && m.models, () => Charts.missedFalse('cMissed', m), noM);
  step('cRoc', c && c.roc, () => Charts.roc('cRoc', c, false), noC);
  step('cPr', c && c.pr, () => Charts.pr('cPr', c, false), noC);
  $('#zoomRoc').addEventListener('change', (e) => c && Charts.roc('cRoc', c, e.target.checked));
  $('#zoomPr').addEventListener('change', (e) => c && Charts.pr('cPr', c, e.target.checked));

  // confusion matrices
  const grid = $('#cmGrid');
  if (m && m.models) {
    const keys = [...Charts.keysOf(m), ...(m.models.ann_tuned ? ['ann_tuned'] : [])];
    grid.innerHTML = keys.map((k) => {
      const e = m.models[k];
      return `<div class="col-md-6 col-xl-4"><div class="fw-semibold mb-1">${esc(e.name)}</div>${confusionHtml(e.confusion_matrix)}
        <div class="small text-secondary mt-2">recall ${fmtPct(e.metrics.recall, 1)} · precision ${fmtPct(e.metrics.precision, 1)} · missed ${fmtInt(e.metrics.fn)}</div></div>`;
    }).join('');
  } else emptyState(grid, noM);

  // sensitivity explorer
  const sw = c && c.threshold_sweep && c.threshold_sweep.ann;
  if (sw) { Charts.explorer('explorer', sw, 0.5); Charts.sweep('cSweep', sw); }
  else { emptyState($('#explorer'), noC); emptyState($('#cSweep').parentElement, noC); }

  // architecture and forward pass
  if (m && m.architecture) {
    const a = m.architecture;
    Charts.architecture('archSvg', a);
    $('#archSub').textContent = `${(a.input_features || []).length} inputs → ` + a.layers.map((l) => `${l.neurons} (${l.activation})`).join(' → ') +
      ` · ${fmtInt(a.total_parameters)} trainable parameters`;
  } else emptyState($('#archSvg'), noM);

  const fd = m && m.ann_internals && m.ann_internals.forward_demo;
  if (fd) {
    const on = (arr) => arr.filter((v) => v > 0).length;
    $('#forwardDemo').innerHTML = `
      <div class="table-responsive-x"><table class="table table-sm table-x mb-2"><tbody>
        ${Object.entries(fd.flow_raw).map(([k, v]) => `<tr><td class="text-secondary">${esc(k)}</td><td class="mono text-end">${fmtInt(v)}</td></tr>`).join('')}
      </tbody></table></div>
      <ol class="small mb-0 ps-3">
        <li>The 10 values are standardised (the same scaler as in training).</li>
        <li>Hidden layer 1: <b>${on(fd.a1)}</b> of ${fd.a1.length} neurons switch on (ReLU output above 0).</li>
        <li>Hidden layer 2: <b>${on(fd.a2)}</b> of ${fd.a2.length} neurons switch on.</li>
        <li>Output neuron: z = <b>${fd.z3.toFixed(3)}</b>, and sigmoid(z) gives <b>P(attack) = ${fd.p_attack.toFixed(4)}</b>.</li>
        <li>Keras gave <b>${fd.keras_p_attack.toFixed(4)}</b> for the same flow, so the hand calculation matches the library.</li>
      </ol>`;
  } else emptyState($('#forwardDemo'), 'No forward-pass example was exported.');

  // training curves
  const h = c && c.training_history;
  const noH = c ? 'No training log was exported (the ANN was loaded from disk, not trained in that session).' : noC;
  step('cLoss', h && h.loss, () => Charts.training('cLoss', h, 'loss', 'loss'), noH);
  step('cTrainRecall', h && h.recall, () => Charts.training('cTrainRecall', h, 'recall', 'recall'), noH);

  step('cType', m && m.attack_type_recall, () => { if (!Charts.attackType('cType', m)) throw new Error('no per-attack-type data'); }, noM);
  step('cFeat', m && m.feature_importance, () => { if (!Charts.featureImportance('cFeat', m)) throw new Error('no importance data'); }, noM);
})();
