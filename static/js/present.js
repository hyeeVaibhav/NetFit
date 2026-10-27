'use strict';
/* Presentation mode: a slide deck built from the saved evaluation. Every number is computed from metrics.json / curves.json. */
(async () => {
  const [m, c] = await Promise.all([Data.metrics(), Data.curves()]);
  let insights = [];
  try { insights = (await api('/api/insights')).insights; } catch (e) { /* optional */ }
  const ins = (id) => insights.find((i) => i.id === id);
  const stage = $('#slide');
  const slides = [];
  const canvasIds = [];
  const chart = (id, extra = '') => { canvasIds.push(id); return `<div class="chart-wrap ${extra}"><canvas id="${id}"></canvas></div>`; };
  const take = (text) => (text ? `<div class="takeaway">${esc(text)}</div>` : '');
  const hasM = m && m.models && Object.keys(m.models).length;

  // ------------------------------------------------------------ 1 title
  const ds = (m && m.dataset) || {};
  slides.push({
    html: `<div class="text-center my-auto">
      <div class="sub text-uppercase mb-3" style="letter-spacing:3px">College project</div>
      <h1>Network Intrusion Detection<br>with an Artificial Neural Network</h1>
      <p class="lead mt-4">Can a neural network tell a normal network flow from an attack, and how does it compare with classical machine learning?</p>
      ${ds.name ? `<p class="sub mt-3">${esc(ds.name)} · ${fmtInt(ds.rows_used)} flows · ${(ds.features || []).length} input features</p>` : ''}
    </div>` });

  // ------------------------------------------------------------ 2 problem
  if (ds.test_label_counts || ds.label_counts) {
    const cnt = ds.test_label_counts || ds.label_counts, tot = cnt.benign + cnt.attack;
    slides.push({
      html: `<h2>The problem: attacks hide in a sea of normal traffic</h2>
        <div class="row g-4 align-items-center mt-1">
          <div class="col-md-6"><div class="pbox text-center"><div class="big-number" style="color:#f87171">${fmtPct(cnt.attack / tot, 1)}</div>
            <div class="sub">of the flows are attacks</div></div></div>
          <div class="col-md-6"><div class="pbox text-center"><div class="big-number" style="color:#60a5fa">${fmtPct(cnt.benign / tot, 1)}</div>
            <div class="sub">accuracy of a "detector" that always says Normal</div></div></div>
        </div>${take('So accuracy alone cannot judge an intrusion detector. We must measure how many attacks are caught, and at what cost in false alarms.')}` });
  }

  // ------------------------------------------------------------ 3 pipeline
  const nTr = ds.rows_used && ds.test_rows ? ds.rows_used - ds.test_rows : null;
  const box = (t, s) => `<div class="pbox text-center flex-fill"><div class="fw-bold">${t}</div><div class="sub">${s}</div></div>`;
  slides.push({
    html: `<h2>The workflow</h2>
      <div class="d-flex flex-wrap gap-3 align-items-stretch mt-3">
        ${box('1. Data', `${esc(ds.name || 'network flows')}`)}
        ${box('2. Features', `${(ds.features || []).length || 10} numbers per flow, standardised`)}
        ${box('3. Split', nTr ? `${fmtInt(nTr)} train · ${fmtInt(ds.test_rows)} test (never seen in training)` : 'train / test')}
        ${box('4. Models', 'Logistic Regression ×2, Random Forest, ANN')}
        ${box('5. Evaluate', 'recall, precision, F1, confusion matrix, ROC / PR')}
        ${box('6. This app', 'upload flows, get predictions')}
      </div>${take('Every model is judged on the same held-out test flows.')}` });

  if (hasM) {
    // ---------------------------------------------------------- 4 accuracy trap
    slides.push({ html: `<h2>Accuracy, precision, recall, F1</h2>${chart('p4')}${take(ins('trap') && ins('trap').text)}`,
      after: () => Charts.metricBars('p4', m) });
  }

  // ------------------------------------------------------------ 5 architecture
  if (m && m.architecture && m.architecture.layers) {
    const a = m.architecture;
    slides.push({
      html: `<h2>The neural network</h2>
        <div class="sub mb-2">${(a.input_features || []).length} inputs → ${a.layers.map((l) => `${l.neurons} (${l.activation})`).join(' → ')} · ${fmtInt(a.total_parameters)} trainable parameters</div>
        <div id="p5" class="pbox" style="overflow:auto"></div>
        ${take('Hidden layers learn combinations of features; the sigmoid output is the probability that the flow is an attack.')}`,
      after: () => Charts.architecture('p5', a) });
  }

  if (hasM) {
    // ---------------------------------------------------------- 6 recall
    slides.push({ html: `<h2>How many attacks does each model catch?</h2>${chart('p6')}${take(ins('recall_leader') && ins('recall_leader').text)}`,
      after: () => Charts.recallBars('p6', m) });
    // ---------------------------------------------------------- 7 missed vs false alarms
    slides.push({ html: `<h2>The price: missed attacks and false alarms</h2>${chart('p7')}${take(ins('other_leaders') && ins('other_leaders').text)}`,
      after: () => Charts.missedFalse('p7', m) });
  }

  // ------------------------------------------------------------ 8 ROC / PR
  if (c && c.roc && c.pr) {
    slides.push({
      html: `<h2>Ranking quality: ROC and Precision-Recall</h2>
        <div class="row g-3"><div class="col-6">${chart('p8a')}</div><div class="col-6">${chart('p8b')}</div></div>
        ${take('Curves higher and further left (ROC) or right (PR) are better. Shown zoomed to the region that matters for a detector.')}`,
      after: () => { Charts.roc('p8a', c, true); Charts.pr('p8b', c, true); } });
  }

  // ------------------------------------------------------------ 9 confusion matrices
  if (hasM) {
    const keys = Charts.keysOf(m);
    slides.push({
      html: `<h2>Confusion matrices</h2><div class="row g-3 mt-1">${keys.map((k) => `<div class="col-md-6 col-xl-3"><div class="pbox">
        <div class="fw-bold mb-2" style="color:${MODEL_COLORS[k]}">${esc(m.models[k].name)}</div>${confusionHtml(m.models[k].confusion_matrix)}</div></div>`).join('')}</div>
        ${take('Bottom-left of each matrix = attacks that slipped through.')}` });
  }

  // ------------------------------------------------------------ 10 sensitivity
  const sw = c && c.threshold_sweep && c.threshold_sweep.ann;
  if (sw) {
    slides.push({
      html: `<h2>The ANN's sensitivity is a dial</h2><div id="p10x" class="pbox mb-3"></div>${chart('p10')}${take(ins('threshold') && ins('threshold').text)}`,
      after: () => { Charts.explorer('p10x', sw, 0.5); Charts.sweep('p10', sw); } });
  }

  // ------------------------------------------------------------ 11 training
  const h = c && c.training_history;
  if (h && h.loss) {
    slides.push({ html: `<h2>Learning curves</h2>${chart('p11')}${take('Training and validation loss falling together shows the network is learning, not memorising.')}`,
      after: () => Charts.training('p11', h, 'loss', 'loss') });
  }

  // ------------------------------------------------------------ 12 per attack type / 13 features
  if (m && m.attack_type_recall && (m.attack_type_recall.ann || m.attack_type_recall.random_forest)) {
    slides.push({ html: `<h2>Detection by attack type</h2>${chart('p12')}${take('Recall for each attack family, ANN against Random Forest (click the legend to compare).')}`,
      after: () => Charts.attackType('p12', m) });
  }
  if (m && m.feature_importance && m.feature_importance.features) {
    slides.push({ html: `<h2>Which features matter?</h2>${chart('p13')}${take('Two different ways to measure importance, for two different models.')}`,
      after: () => Charts.featureImportance('p13', m) });
  }

  // ------------------------------------------------------------ 14 honest trade-offs
  if (insights.length) {
    const pick = ['ann_rank', 'other_leaders', 'honest'].map(ins).filter(Boolean);
    slides.push({
      html: `<h2>The honest comparison</h2><div class="d-flex flex-column gap-3 mt-2">${pick.map((i) =>
        `<div class="insight ${i.tone}"><h6 style="font-size:1.1rem">${esc(i.title)}</h6><p style="font-size:1.05rem">${esc(i.text)}</p></div>`).join('')}</div>` });
  }

  // ------------------------------------------------------------ 15 live demo
  slides.push({
    html: `<div class="text-center my-auto"><h2>Live demo</h2>
      <p class="lead mb-4">Upload network flows, choose a model and a threshold, and get a verdict for every flow.</p>
      <div class="d-flex gap-3 justify-content-center flex-wrap">
        <a class="deck-btn text-decoration-none fs-5 px-4 py-2" href="/predict?sample=1">Run the sample file</a>
        <a class="deck-btn text-decoration-none fs-5 px-4 py-2" href="/battle">Model Battle</a>
        <a class="deck-btn text-decoration-none fs-5 px-4 py-2" href="/history">History</a></div></div>` });

  // ------------------------------------------------------------ 16 limitations
  slides.push({
    html: `<h2>Limitations and future work</h2>
      <div class="row g-3 mt-1"><div class="col-md-6"><div class="pbox"><div class="fw-bold mb-2">Limits today</div>
        <ul class="mb-0"><li>Binary output: attack or normal, not the attack type</li><li>One dataset, ten flow features</li>
        <li>Unseen attack types may be missed</li><li>Scores uploaded flow records; no live packet capture or blocking</li></ul></div></div>
      <div class="col-md-6"><div class="pbox"><div class="fw-bold mb-2">Next steps</div>
        <ul class="mb-0"><li>Multi-class ANN that names the attack</li><li>Richer input features and tuning on validation data</li>
        <li>Evaluate on other networks and datasets</li><li>Live flow collection and alerting</li></ul></div></div></div>` });

  // ------------------------------------------------------------ 17 conclusion
  const concl = ['recall_leader', 'trap', 'honest'].map(ins).filter(Boolean);
  slides.push({
    html: `<h2>Conclusion</h2><div class="d-flex flex-column gap-3 mt-2">${concl.map((i) =>
      `<div class="insight ${i.tone}"><p style="font-size:1.1rem;color:#e2e8f0">${esc(i.text)}</p></div>`).join('')}</div>
      <div class="takeaway mt-4">A neural network gives high attack detection and a tunable probability; no single model wins every metric.</div>` });

  // ------------------------------------------------------------ engine
  let cur = 0;
  const dots = $('#dots');
  dots.innerHTML = slides.map((_, i) => `<button class="dotnav" data-i="${i}" aria-label="Slide ${i + 1}"></button>`).join('');
  function show(i) {
    cur = Math.max(0, Math.min(slides.length - 1, i));
    canvasIds.splice(0).forEach((id) => Charts.destroy(id));
    stage.innerHTML = slides[cur].html;
    stage.style.animation = 'none'; void stage.offsetWidth; stage.style.animation = '';
    if (slides[cur].after) { try { slides[cur].after(); } catch (e) { console.error(e); } }
    $('#counter').textContent = `${cur + 1} / ${slides.length}`;
    $$('.dotnav').forEach((d, k) => d.classList.toggle('on', k === cur));
    history.replaceState(null, '', '#' + (cur + 1));
  }
  $('#prev').addEventListener('click', () => show(cur - 1));
  $('#next').addEventListener('click', () => show(cur + 1));
  dots.addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) show(+b.dataset.i); });
  document.addEventListener('keydown', (e) => {
    if (['ArrowRight', 'PageDown', ' '].includes(e.key)) { e.preventDefault(); show(cur + 1); }
    else if (['ArrowLeft', 'PageUp'].includes(e.key)) { e.preventDefault(); show(cur - 1); }
    else if (e.key === 'Home') show(0);
    else if (e.key === 'End') show(slides.length - 1);
    else if (e.key.toLowerCase() === 'f') toggleFs();
  });
  function toggleFs() {
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
    else document.exitFullscreen();
  }
  $('#fsBtn').addEventListener('click', toggleFs);
  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
})();
