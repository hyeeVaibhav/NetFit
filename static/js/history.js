'use strict';
(() => {
  const table = $('#histTable');

  async function load() {
    skeleton(table, 140);
    try {
      const { runs } = await api('/api/history');
      if (!runs.length) {
        table.innerHTML = `<tbody><tr><td class="text-center text-secondary py-5">No predictions saved yet.<br>
          <a class="btn btn-primary btn-sm mt-3" href="/predict?sample=1">Run the sample file</a></td></tr></tbody>`;
        return;
      }
      table.innerHTML = `<thead><tr><th>#</th><th>When</th><th>File</th><th>Model</th><th class="text-end">Threshold</th>
        <th class="text-end">Flows</th><th class="text-end">Flagged</th><th class="text-end">Recall</th><th></th></tr></thead><tbody>` +
        runs.map((r) => `<tr>
          <td><a href="/results/${r.id}">#${r.id}</a></td>
          <td class="text-nowrap">${esc(r.created_at.replace('T', ' '))}</td>
          <td class="text-truncate" style="max-width:200px" title="${esc(r.filename)}">${esc(r.filename)}</td>
          <td>${esc(r.model_name)}</td>
          <td class="text-end mono">${r.threshold.toFixed(2)}</td>
          <td class="text-end mono">${fmtInt(r.n_rows)}</td>
          <td class="text-end mono">${fmtInt(r.n_attack)} <span class="text-secondary">(${fmtPct(r.attack_rate, 1)})</span></td>
          <td class="text-end mono">${r.has_labels ? fmtPct(r.recall, 1) : '<span class="text-secondary">n/a</span>'}</td>
          <td class="text-nowrap text-end">
            <a class="btn btn-sm btn-outline-primary" href="/results/${r.id}">Open</a>
            <a class="btn btn-sm btn-outline-secondary" href="/api/runs/${r.id}/download">CSV</a>
            <button class="btn btn-sm btn-outline-danger" data-del="${r.id}" type="button">Delete</button></td></tr>`).join('') + '</tbody>';
    } catch (e) { emptyState(table, e.message); }
  }

  table.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-del]'); if (!b) return;
    if (!confirm(`Delete run #${b.dataset.del} and its results file?`)) return;
    try { await api(`/api/runs/${b.dataset.del}`, { method: 'DELETE' }); toast('Run deleted', 'ok'); load(); }
    catch (err) { toast(err.message, 'err'); }
  });
  $('#clearBtn').addEventListener('click', async () => {
    if (!confirm('Delete ALL saved predictions? This cannot be undone.')) return;
    try { const r = await api('/api/history', { method: 'DELETE' }); toast(`${r.deleted} run(s) deleted`, 'ok'); load(); }
    catch (err) { toast(err.message, 'err'); }
  });
  load();
})();
