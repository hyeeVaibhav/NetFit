/* charts.js - every chart draws genuine numbers from metrics.json / curves.json (or from a saved prediction run). */
'use strict';

const Charts = (() => {
  const builders = {}, inst = {};
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  // small plugin: print the value above (or beside) each bar
  Chart.register({
    id: 'valueLabels',
    afterDatasetsDraw(chart, _args, opts) {
      if (!opts || !opts.fmt) return;
      const { ctx } = chart; ctx.save();
      ctx.fillStyle = cssv('--chart-text'); ctx.font = '600 11px sans-serif';
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i); if (meta.hidden) return;
        meta.data.forEach((bar, j) => {
          const v = ds.data[j]; if (v === null || v === undefined) return;
          if (chart.options.indexAxis === 'y') { ctx.textAlign = 'left'; ctx.fillText(opts.fmt(v), bar.x + 5, bar.y + 4); }
          else { ctx.textAlign = 'center'; ctx.fillText(opts.fmt(v), bar.x, bar.y - 5); }
        });
      });
      ctx.restore();
    },
  });

  function applyTheme() {
    Chart.defaults.color = cssv('--chart-text');
    Chart.defaults.borderColor = cssv('--chart-grid');
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.animation.duration = 450;
  }
  function render(id) {
    const el = document.getElementById(id);
    if (!el || !builders[id]) return;
    applyTheme();
    if (inst[id]) inst[id].destroy();
    inst[id] = new Chart(el, builders[id]());
  }
  function draw(id, build) { builders[id] = build; render(id); }
  function destroy(id) { if (inst[id]) { inst[id].destroy(); delete inst[id]; } delete builders[id]; }
  document.addEventListener('themechange', () => Object.keys(builders).forEach(render));

  const keysOf = (m) => MODEL_ORDER.filter((k) => m && m.models && m.models[k]);
  const pctAxis = { min: 0, max: 1.08, ticks: { callback: (v) => (v <= 1 ? (v * 100).toFixed(0) + '%' : '') } };
  const pctTip = { callbacks: { label: (c) => `${c.dataset.label}: ${fmtPct(c.parsed.y ?? c.parsed.x, 2)}` } };

  // -------------------------------------------------------------- comparison charts
  function metricBars(id, m) {
    draw(id, () => ({
      type: 'bar',
      data: {
        labels: ['Accuracy', 'Precision', 'Recall', 'F1 score'],
        datasets: keysOf(m).map((k) => ({
          label: modelName(m, k), backgroundColor: MODEL_COLORS[k], borderRadius: 4,
          data: ['accuracy', 'precision', 'recall', 'f1'].map((x) => m.models[k].metrics[x]),
        })),
      },
      options: { scales: { y: pctAxis }, plugins: { tooltip: pctTip, valueLabels: { fmt: (v) => (v * 100).toFixed(0) } } },
    }));
  }

  function recallBars(id, m) {
    draw(id, () => ({
      type: 'bar',
      data: {
        labels: keysOf(m).map((k) => modelName(m, k)),
        datasets: [{ label: 'Recall (attacks detected)', data: keysOf(m).map((k) => m.models[k].metrics.recall),
          backgroundColor: keysOf(m).map((k) => MODEL_COLORS[k]), borderRadius: 6 }],
      },
      options: {
        scales: { y: pctAxis }, plugins: { legend: { display: false }, valueLabels: { fmt: (v) => (v * 100).toFixed(1) + '%' },
          tooltip: { callbacks: { label: (c) => { const e = m.models[keysOf(m)[c.dataIndex]].metrics;
            return [`Recall: ${fmtPct(e.recall)}`, `Caught ${fmtInt(e.tp)} of ${fmtInt(e.tp + e.fn)} attacks`]; } } } },
      },
    }));
  }

  function missedFalse(id, m) {
    draw(id, () => ({
      type: 'bar',
      data: {
        labels: keysOf(m).map((k) => modelName(m, k)),
        datasets: [
          { label: 'Attacks missed (false negatives)', data: keysOf(m).map((k) => m.models[k].metrics.fn), backgroundColor: '#dc2626', borderRadius: 4 },
          { label: 'False alarms (false positives)', data: keysOf(m).map((k) => m.models[k].metrics.fp), backgroundColor: '#f59e0b', borderRadius: 4 },
        ],
      },
      options: { scales: { y: { beginAtZero: true } }, plugins: { valueLabels: { fmt: (v) => fmtInt(v) } } },
    }));
  }

  function classBalance(id, ds) {
    draw(id, () => ({
      type: 'doughnut',
      data: { labels: ['Benign', 'Attack'], datasets: [{ data: [ds.label_counts.benign, ds.label_counts.attack],
        backgroundColor: ['#3b82f6', '#ef4444'], borderWidth: 0 }] },
      options: { cutout: '62%', plugins: { tooltip: { callbacks: { label: (c) => {
        const t = ds.label_counts.benign + ds.label_counts.attack;
        return `${c.label}: ${fmtInt(c.parsed)} (${fmtPct(c.parsed / t)})`; } } } } },
    }));
  }

  // -------------------------------------------------------------- curves
  function lineCurves(id, curves, kind, zoom) {
    const src = curves[kind]; const keys = MODEL_ORDER.filter((k) => src[k]);
    draw(id, () => {
      const isRoc = kind === 'roc';
      const sets = keys.map((k) => ({
        label: `${src[k].name} (${isRoc ? 'AUC ' + src[k].auc.toFixed(4) : 'AP ' + src[k].ap.toFixed(4)})`,
        data: src[k][isRoc ? 'fpr' : 'recall'].map((x, i) => ({ x, y: src[k][isRoc ? 'tpr' : 'precision'][i] })),
        borderColor: MODEL_COLORS[k], backgroundColor: MODEL_COLORS[k], showLine: true, pointRadius: 0, borderWidth: 2.2, tension: 0,
      }));
      if (isRoc) sets.push({ label: 'Random guessing', data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: '#94a3b8',
        borderDash: [6, 5], showLine: true, pointRadius: 0, borderWidth: 1.2 });
      return {
        type: 'scatter', data: { datasets: sets },
        options: {
          scales: {
            x: { min: zoom ? (isRoc ? 0 : 0.8) : 0, max: zoom && isRoc ? 0.1 : 1.0, title: { display: true, text: isRoc ? 'False positive rate (false alarms)' : 'Recall' } },
            y: { min: zoom ? (isRoc ? 0.8 : 0.3) : 0, max: 1.01, title: { display: true, text: isRoc ? 'True positive rate (recall)' : 'Precision' } },
          },
          plugins: { tooltip: { enabled: false } },
        },
      };
    });
  }
  const roc = (id, c, zoom = false) => lineCurves(id, c, 'roc', zoom);
  const pr = (id, c, zoom = false) => lineCurves(id, c, 'pr', zoom);

  function training(id, hist, key, title) {
    draw(id, () => {
      const n = (hist[key] || []).length;
      return {
        type: 'line',
        data: { labels: Array.from({ length: n }, (_, i) => i + 1), datasets: [
          { label: 'Training ' + title, data: hist[key], borderColor: '#3b82f6', backgroundColor: '#3b82f6', pointRadius: 2, tension: .25 },
          { label: 'Validation ' + title, data: hist['val_' + key], borderColor: '#f59e0b', backgroundColor: '#f59e0b', pointRadius: 2, tension: .25 },
        ] },
        options: { scales: { x: { title: { display: true, text: 'Epoch' } } } },
      };
    });
  }

  function sweep(id, rows) {
    draw(id, () => ({
      type: 'line',
      data: { labels: rows.map((r) => r.threshold.toFixed(2)), datasets: [
        { label: 'Recall', data: rows.map((r) => r.recall), borderColor: '#ef4444', backgroundColor: '#ef4444', tension: .2 },
        { label: 'Precision', data: rows.map((r) => r.precision), borderColor: '#3b82f6', backgroundColor: '#3b82f6', tension: .2 },
        { label: 'False alarm rate', data: rows.map((r) => r.fpr), borderColor: '#f59e0b', backgroundColor: '#f59e0b', tension: .2 },
        { label: 'F1', data: rows.map((r) => r.f1), borderColor: '#8b5cf6', backgroundColor: '#8b5cf6', borderDash: [5, 4], tension: .2 },
      ] },
      options: { scales: { y: { min: 0, max: 1.02, ticks: { callback: (v) => (v * 100).toFixed(0) + '%' } },
        x: { title: { display: true, text: 'Decision threshold' } } }, plugins: { tooltip: pctTip } },
    }));
  }

  /** slider that shows what a given threshold would do, using the saved threshold sweep */
  function explorer(rootId, rows, start = 0.5) {
    const root = document.getElementById(rootId);
    if (!root || !rows || !rows.length) return;
    let idx = rows.reduce((b, r, i) => (Math.abs(r.threshold - start) < Math.abs(rows[b].threshold - start) ? i : b), 0);
    root.innerHTML = `<div class="explorer">
      <label class="form-label mb-1">Decision threshold: <b id="${rootId}-v"></b>
        <span class="text-secondary small">(attack if the model's probability is at least this)</span></label>
      <input type="range" class="form-range" min="0" max="${rows.length - 1}" step="1" value="${idx}" id="${rootId}-r">
      <div class="row g-2 mt-1" id="${rootId}-s"></div></div>`;
    const upd = () => {
      const r = rows[idx];
      $('#' + rootId + '-v').textContent = r.threshold.toFixed(2);
      const tile = (v, l) => `<div class="col-4 col-md-2"><div class="stat"><b>${v}</b><span>${l}</span></div></div>`;
      $('#' + rootId + '-s').innerHTML = tile(fmtInt(r.tp), 'attacks caught') + tile(fmtInt(r.fn), 'attacks MISSED') +
        tile(fmtInt(r.fp), 'false alarms') + tile(fmtPct(r.recall, 1), 'recall') + tile(fmtPct(r.precision, 1), 'precision') +
        tile(fmtPct(r.fpr, 2), 'false alarm rate');
    };
    $('#' + rootId + '-r').addEventListener('input', (e) => { idx = +e.target.value; upd(); });
    upd();
  }

  // -------------------------------------------------------------- other charts
  function attackType(id, m) {
    const atr = m.attack_type_recall || {}; const ref = atr.ann || atr.random_forest; if (!ref) return false;
    const types = Object.keys(ref);
    draw(id, () => ({
      type: 'bar',
      data: { labels: types, datasets: MODEL_ORDER.filter((k) => atr[k]).map((k) => ({
        label: modelName(m, k), backgroundColor: MODEL_COLORS[k], borderRadius: 3, hidden: k.startsWith('logistic'),
        data: types.map((t) => (atr[k][t] ? atr[k][t].recall : null)) })) },
      options: { scales: { y: pctAxis }, plugins: { tooltip: { callbacks: { label: (c) => {
        const e = atr[MODEL_ORDER.filter((k) => atr[k])[c.datasetIndex]][types[c.dataIndex]];
        return `${c.dataset.label}: ${fmtPct(e.recall)} (${e.detected}/${e.count})`; } } } } },
    }));
    return true;
  }

  function featureImportance(id, m) {
    const fi = m.feature_importance; if (!fi || !fi.features) return false;
    const ord = fi.features.map((_, i) => i).sort((a, b) => fi.ann_normalised[b] - fi.ann_normalised[a]);
    draw(id, () => ({
      type: 'bar',
      data: { labels: ord.map((i) => fi.features[i]), datasets: [
        { label: 'ANN (permutation importance)', data: ord.map((i) => fi.ann_normalised[i]), backgroundColor: MODEL_COLORS.ann, borderRadius: 3 },
        { label: 'Random Forest (impurity importance)', data: ord.map((i) => fi.random_forest[i]), backgroundColor: MODEL_COLORS.random_forest, borderRadius: 3 },
      ] },
      options: { indexAxis: 'y', scales: { x: { ticks: { callback: (v) => (v * 100).toFixed(0) + '%' } } } },
    }));
    return true;
  }

  function probHist(id, h) {
    const labels = h.bins.slice(0, -1).map((b, i) => `${b.toFixed(2)}-${h.bins[i + 1].toFixed(2)}`);
    draw(id, () => ({
      type: 'bar',
      data: { labels, datasets: [
        { label: 'Predicted normal', data: h.normal, backgroundColor: '#3b82f6' },
        { label: 'Predicted attack', data: h.attack, backgroundColor: '#ef4444' } ] },
      options: { scales: { x: { stacked: true, title: { display: true, text: 'P(attack)' }, ticks: { maxRotation: 60, autoSkip: true } },
        y: { stacked: true, title: { display: true, text: 'flows' } } } },
    }));
  }

  function donut(id, labels, values, colors) {
    draw(id, () => ({ type: 'doughnut', data: { labels, datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }] },
      options: { cutout: '62%', plugins: { legend: { position: 'bottom' } } } }));
  }

  function simpleBars(id, labels, values, color, label, horizontal = false) {
    draw(id, () => ({ type: 'bar', data: { labels, datasets: [{ label, data: values, backgroundColor: color, borderRadius: 4 }] },
      options: { indexAxis: horizontal ? 'y' : 'x', plugins: { legend: { display: false }, valueLabels: { fmt: (v) => fmtInt(v) } } } }));
  }

  // -------------------------------------------------------------- network diagram (SVG)
  function architecture(containerId, arch, dark = false) {
    const el = document.getElementById(containerId);
    if (!el || !arch || !arch.layers) return;
    const feats = arch.input_features || [];
    const sizes = [feats.length || arch.layers[0].inputs, ...arch.layers.map((l) => l.neurons)];
    const names = ['Input', ...arch.layers.map((l, i) => (i === arch.layers.length - 1 ? 'Output' : `Hidden ${i + 1}`))];
    const subs = [`${sizes[0]} features`, ...arch.layers.map((l) => `${l.neurons} neuron${l.neurons > 1 ? 's' : ''} · ${l.activation}`)];
    const W = 980, H = 440, left = 260, right = 110, top = 70, bottom = 380;   // wide left margin: longest feature name
    const xs = sizes.map((_, i) => left + (i * (W - left - right)) / (sizes.length - 1));
    const cols = ['#3b82f6', '#f59e0b', '#f59e0b', '#ef4444'];
    const layers = sizes.map((n, i) => {
      const shown = Math.min(n, i === 0 ? n : 8);
      const ys = shown === 1 ? [(top + bottom) / 2] : Array.from({ length: shown }, (_, j) => top + (j * (bottom - top)) / (shown - 1));
      return { n, shown, ys, x: xs[i] };
    });
    let s = `<svg class="arch-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Neural network architecture">`;
    for (let i = 0; i < layers.length - 1; i++)
      for (const ya of layers[i].ys) for (const yb of layers[i + 1].ys)
        s += `<line x1="${layers[i].x}" y1="${ya}" x2="${layers[i + 1].x}" y2="${yb}" stroke="#94a3b8" stroke-opacity=".28" stroke-width=".7"/>`;
    layers.forEach((L, i) => {
      const col = i === 0 ? cols[0] : (i === layers.length - 1 ? cols[3] : cols[1]);
      L.ys.forEach((y, j) => {
        s += `<circle cx="${L.x}" cy="${y}" r="${i === 0 ? 11 : 12}" fill="${col}" stroke="#0f172a" stroke-opacity=".5"/>`;
        if (i === 0 && feats[j]) s += `<text x="${L.x - 18}" y="${y + 4}" text-anchor="end">${esc(feats[j])}</text>`;
      });
      if (L.n > L.shown) s += `<text x="${L.x}" y="${bottom + 28}" text-anchor="middle">⋮ +${L.n - L.shown} more</text>`;
      s += `<text x="${L.x}" y="26" text-anchor="middle" style="font-weight:700;font-size:13px">${names[i]}</text>`;
      s += `<text x="${L.x}" y="44" text-anchor="middle">${esc(subs[i])}</text>`;
    });
    const last = layers[layers.length - 1];
    s += `<text x="${last.x + 24}" y="${last.ys[0] + 4}">P(attack)</text></svg>`;
    el.innerHTML = s;
  }

  return { draw, destroy, metricBars, recallBars, missedFalse, classBalance, roc, pr, training, sweep, explorer,
    attackType, featureImportance, probHist, donut, simpleBars, architecture, keysOf };
})();
