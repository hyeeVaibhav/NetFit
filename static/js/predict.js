'use strict';
(() => {
  let file = null, useSample = false;
  const dz = $('#dropzone'), input = $('#fileInput'), info = $('#fileInfo'), errBox = $('#errorBox');
  const thr = $('#thr'), thrVal = $('#thrVal'), overlay = $('#overlay');

  const showError = (title, details = []) => {
    errBox.classList.remove('d-none');
    errBox.innerHTML = `<strong>${esc(title)}</strong>` +
      (details.length ? `<ul class="mb-0 mt-2 small">${details.map((d) => `<li>${esc(d)}</li>`).join('')}</ul>` : '');
    errBox.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  const clearError = () => { errBox.classList.add('d-none'); errBox.innerHTML = ''; };

  function setFile(f) {
    clearError(); useSample = false;
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.csv')) { file = null; info.classList.add('d-none'); return showError('Only .csv files are accepted.'); }
    file = f;
    info.classList.remove('d-none');
    info.innerHTML = `<b>${esc(f.name)}</b> · ${(f.size / 1024).toFixed(1)} KB — ready`;
  }

  dz.addEventListener('click', () => input.click());
  dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => setFile(input.files[0]));
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', (e) => setFile(e.dataTransfer.files[0]));

  function chooseSample() {
    clearError(); file = null; useSample = true;
    info.classList.remove('d-none');
    info.innerHTML = '<b>sample_flows.csv</b> (bundled with the model export, flows from the held-out test set) — ready';
  }
  const sampleBtn = $('#sampleBtn');
  if (sampleBtn) sampleBtn.addEventListener('click', chooseSample);
  if (new URLSearchParams(location.search).get('sample') === '1' && sampleBtn) chooseSample();

  $$('.model-choice').forEach((lab) => lab.addEventListener('click', () => {
    if (lab.classList.contains('disabled')) return;
    $$('.model-choice').forEach((l) => l.classList.remove('selected'));
    lab.classList.add('selected'); $('input', lab).checked = true;
  }));

  thr.addEventListener('input', () => { thrVal.textContent = Number(thr.value).toFixed(2); });
  $$('[data-thr]').forEach((b) => b.addEventListener('click', () => {
    thr.value = b.dataset.thr; thrVal.textContent = Number(thr.value).toFixed(2);
  }));

  $('#runBtn').addEventListener('click', async () => {
    clearError();
    if (!file && !useSample) return showError('Choose a CSV file first, or use the bundled sample file.');
    const model = ($('input[name=model]:checked') || {}).value;
    if (!model) return showError('No model is available. Check the setup message at the top of the page.');
    const fd = new FormData();
    fd.append('model', model); fd.append('threshold', thr.value);
    if (useSample) fd.append('sample', '1'); else fd.append('file', file);

    overlay.classList.add('show'); $('#overlayText').textContent = 'Uploading and validating…';
    const t = setTimeout(() => { $('#overlayText').textContent = 'Running the model…'; }, 700);
    try {
      const res = await api('/api/predict', { method: 'POST', body: fd });
      location.href = res.redirect;
    } catch (e) {
      clearTimeout(t); overlay.classList.remove('show');
      showError(e.message, e.details || []);
    }
  });
})();
