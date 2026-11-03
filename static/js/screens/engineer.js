/* Engineer screen: single inspection, batch, and my history.
 * Batch flow (file list, 10-file limit, 2-second polling) builds on Person 4's batch_inspection.js.
 */
(function () {
  'use strict';
  const { api, showAlert, clearAlert, setBusy } = window.App;
  const UI = window.UI;
  const { el } = UI;

  const MAX_FILES = 10;
  const POLL_MS = 2000;
  const LAST_SINGLE_KEY = 'vi:last-single-inspection';

  UI.hashTabs(document.querySelector('[data-tabs]'));

  /* ================= Products (shared by both forms) ================= */

  async function loadProducts() {
    const selects = document.querySelectorAll('[data-products]');
    try {
      const data = await api('/api/products/');
      const products = Array.isArray(data) ? data : data.results || [];
      selects.forEach((select) => {
        select.replaceChildren(
          products.length
            ? null
            : el('option', { value: '', text: 'No products yet. Ask an Administrator to add one.' }),
          ...products.map((p) => el('option', { value: p.product_id, text: `${p.product_id} · ${p.name}` })));
        select.disabled = products.length === 0;
      });
    } catch (error) {
      selects.forEach((select) => {
        select.replaceChildren(el('option', { value: '', text: 'Could not load products' }));
        select.disabled = true;
      });
      showAlert('#page-alert', `Could not load products: ${error.message}`);
    }
    updateSingleButton();
    updateBatchUi();
  }

  function sessionGet(key) {
    try { return window.sessionStorage.getItem(key); } catch (e) { return null; }
  }
  function sessionSet(key, value) {
    try { window.sessionStorage.setItem(key, value); } catch (e) { /* storage blocked: not needed to work */ }
  }

  function wireDropzone(zone, input, onFiles) {
    ['dragenter', 'dragover'].forEach((type) => zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.add('is-dragover');
    }));
    ['dragleave', 'drop'].forEach((type) => zone.addEventListener(type, () => zone.classList.remove('is-dragover')));
    zone.addEventListener('drop', (event) => {
      event.preventDefault();
      onFiles([...event.dataTransfer.files]);
    });
    input.addEventListener('change', () => {
      onFiles([...input.files]);
      input.value = '';
    });
  }

  /* ================= Single inspection ================= */

  const single = {
    form: document.getElementById('single-form'),
    product: document.getElementById('single-product'),
    drop: document.getElementById('single-drop'),
    input: document.getElementById('single-file'),
    preview: document.getElementById('single-preview'),
    fileName: document.getElementById('single-file-name'),
    submit: document.getElementById('single-submit'),
    alert: document.getElementById('single-alert'),
    result: document.getElementById('single-result'),
    file: null,
    previewUrl: null,
  };

  function updateSingleButton() {
    single.submit.disabled = !single.file || !single.product.value;
  }

  function chooseSingle(files) {
    clearAlert(single.alert);
    if (!files.length) return;
    if (files.length > 1) {
      showAlert(single.alert, 'Choose one image here. Use the Batch tab for several images.', 'warning');
    }
    single.file = files[0];
    if (single.previewUrl) URL.revokeObjectURL(single.previewUrl);
    single.previewUrl = URL.createObjectURL(single.file);
    single.preview.src = single.previewUrl;
    single.preview.alt = `Preview of ${single.file.name}`;
    single.preview.hidden = false;
    single.drop.classList.add('has-preview');
    single.drop.querySelector('[data-drop-empty]').hidden = true;
    single.fileName.textContent = `Selected: ${single.file.name}`;
    updateSingleButton();
  }

  // A file that is not an image can't be previewed; the server still gives the real reason.
  single.preview.addEventListener('error', () => {
    if (!single.file) return;
    single.preview.hidden = true;
    single.drop.querySelector('[data-drop-empty]').hidden = false;
    single.drop.classList.remove('has-preview');
  });

  function showSingleResult(item, eyebrow) {
    const card = UI.verdictCard(item, { eyebrow });
    const footer = el('p', { class: 'small muted mt-3 mb-0' },
      `Saved as inspection #${item.id}. `,
      el('a', { href: '#history', text: 'See it in My history', onclick: (e) => { e.preventDefault(); showTab('#history'); } }),
      '.');
    single.result.replaceChildren(card, footer);
  }

  wireDropzone(single.drop, single.input, chooseSingle);
  single.product.addEventListener('change', updateSingleButton);

  single.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert(single.alert);
    if (!single.file || !single.product.value) return;
    const body = new FormData();
    body.append('product', single.product.value);
    body.append('file', single.file);
    setBusy(single.submit, true, 'Inspecting…');
    single.result.setAttribute('aria-busy', 'true');
    try {
      const item = await api('/api/inspections/', { method: 'POST', body });
      sessionSet(LAST_SINGLE_KEY, String(item.id));
      showSingleResult(item, 'Model verdict');
      historyStale = true;
    } catch (error) {
      showAlert(single.alert, error.message);
    } finally {
      single.result.removeAttribute('aria-busy');
      setBusy(single.submit, false);
      updateSingleButton();
    }
  });

  // After a page reload, show the last result again, read back from the server.
  async function restoreLastSingle() {
    const id = sessionGet(LAST_SINGLE_KEY);
    if (!id || !/^\d+$/.test(id)) return;
    try {
      const item = await api(`/api/inspections/${id}/`);
      showSingleResult(item, 'Last inspection · loaded from the server');
    } catch (error) {
      /* It may belong to another account on this browser; just start empty. */
    }
  }

  /* ================= Batch ================= */

  const batch = {
    form: document.getElementById('batch-form'),
    product: document.getElementById('batch-product'),
    drop: document.getElementById('batch-drop'),
    input: document.getElementById('batch-files'),
    list: document.getElementById('batch-file-list'),
    count: document.getElementById('batch-count'),
    submit: document.getElementById('batch-submit'),
    alert: document.getElementById('batch-alert'),
    progress: document.getElementById('batch-progress'),
    results: document.getElementById('batch-results'),
    meta: document.getElementById('batch-meta'),
    files: [],
    running: false,
    timer: null,
    controller: null,
    rows: new Map(),
  };

  function updateBatchUi() {
    const n = batch.files.length;
    batch.count.textContent = `${n} of ${MAX_FILES} files`;
    batch.count.classList.toggle('is-full', n >= MAX_FILES);
    batch.submit.disabled = n === 0 || batch.running || !batch.product.value;
    batch.submit.textContent = batch.running ? 'Batch running…' : n ? `Start batch of ${n}` : 'Start batch';
    batch.list.replaceChildren(...batch.files.map((file, index) => el('li', {},
      el('span', { class: 'sub num', text: `${index + 1}.` }),
      el('span', { class: 'file-name', text: file.name }),
      el('span', { class: 'sub num', text: `${(file.size / 1024).toFixed(0)} KB` }),
      el('button', {
        type: 'button', class: 'btn btn-sm btn-outline-secondary', text: 'Remove',
        'aria-label': `Remove ${file.name}`, disabled: batch.running,
        onclick: () => { batch.files.splice(index, 1); clearAlert(batch.alert); updateBatchUi(); },
      }))));
  }

  function addBatchFiles(files) {
    clearAlert(batch.alert);
    const room = MAX_FILES - batch.files.length;
    batch.files.push(...files.slice(0, Math.max(0, room)));
    const skipped = files.length - Math.max(0, room);
    if (skipped > 0) {
      showAlert(batch.alert,
        `A batch can hold at most ${MAX_FILES} files. ${skipped} file${skipped === 1 ? ' was' : 's were'} not added.`,
        'warning');
    }
    updateBatchUi();
  }

  wireDropzone(batch.drop, batch.input, addBatchFiles);
  batch.product.addEventListener('change', updateBatchUi);

  function stopPolling() {
    if (batch.timer) clearTimeout(batch.timer);
    if (batch.controller) batch.controller.abort();
    batch.timer = null;
    batch.controller = null;
  }
  window.addEventListener('pagehide', stopPolling);

  function renderProgress(data) {
    const c = data.status_counts;
    const total = data.items.length;
    const finished = c.completed + c.failed;
    const done = c.queued === 0 && c.processing === 0;
    const segment = (kind, n) => el('span', { class: `seg-${kind}`, style: `width:${total ? (n / total) * 100 : 0}%` });
    batch.progress.hidden = false;
    batch.progress.replaceChildren(
      el('div', { class: 'd-flex justify-content-between align-items-baseline mb-2' },
        el('strong', { text: done ? 'Batch finished' : 'Processing…' }),
        el('span', { class: 'num muted', text: `${finished} of ${total} finished` })),
      el('div', {
        class: 'progress-stack', role: 'progressbar', 'aria-label': 'Batch progress',
        'aria-valuemin': 0, 'aria-valuemax': total, 'aria-valuenow': finished,
      }, segment('completed', c.completed), segment('failed', c.failed), segment('processing', c.processing)),
      el('div', { class: 'legend' },
        ['queued', 'processing', 'completed', 'failed'].map((s) =>
          el('span', { class: 'd-inline-flex align-items-center gap-2' }, UI.statusChip(s), el('b', { text: c[s] })))));
    batch.meta.textContent = `Batch #${data.id} · ${UI.when(data.created_at)}`;
  }

  function batchRow(item) {
    const row = el('tr', { dataset: { id: item.id } },
      el('td', {}, el('div', { class: 'cell-file' }, UI.thumb(item),
        el('div', {}, el('div', { class: 'file-name', text: item.original_filename }),
          el('div', { 'data-col': 'detail' })))),
      el('td', { 'data-col': 'status' }),
      el('td', { 'data-col': 'result' }),
      el('td', { class: 'num', 'data-col': 'confidence' }));
    updateBatchRow(row, item);
    return row;
  }

  function updateBatchRow(row, item) {
    // Only text cells change; the thumbnail stays, so images are not downloaded again on every poll.
    if (row.dataset.status === item.status) return;
    row.dataset.status = item.status;
    row.querySelector('[data-col="status"]').replaceChildren(UI.statusChip(item.status));
    row.querySelector('[data-col="result"]').replaceChildren(
      item.status === 'completed' ? UI.resultBadge(item.predicted_class) : el('span', { class: 'muted', text: '—' }));
    row.querySelector('[data-col="confidence"]').textContent =
      item.status === 'completed' ? UI.percent(item.confidence) : '—';
    const waiting = { queued: 'Waiting for the worker', processing: 'Being inspected now' };
    row.querySelector('[data-col="detail"]').replaceChildren(
      item.status === 'failed'
        ? el('div', { class: 'reason', text: item.failure_reason || 'Failed.' })
        : el('div', { class: 'sub', text: item.status === 'completed' ? item.model_version : waiting[item.status] || '' }));
  }

  function renderBatch(data) {
    renderProgress(data);
    let tbody = batch.results.querySelector('tbody');
    if (!tbody) {
      batch.rows.clear();
      tbody = el('tbody');
      batch.results.replaceChildren(el('div', { class: 'table-responsive' },
        el('table', { class: 'table table-vi' },
          el('thead', {}, el('tr', {}, ['File', 'Status', 'Result', 'Confidence']
            .map((h) => el('th', { scope: 'col', text: h })))),
          tbody)));
    }
    for (const item of data.items) {
      const existing = batch.rows.get(item.id);
      if (existing) updateBatchRow(existing, item);
      else {
        const row = batchRow(item);
        batch.rows.set(item.id, row);
        tbody.append(row);
      }
    }
  }

  function finishBatch(data, message, kind) {
    stopPolling();
    batch.running = false;
    historyStale = true;
    updateBatchUi();
    if (message) showAlert(batch.alert, message, kind || 'success');
    else {
      const c = data.status_counts;
      showAlert(batch.alert,
        `Batch #${data.id} finished: ${c.completed} completed, ${c.failed} failed.`, c.failed ? 'warning' : 'success');
    }
  }

  async function poll(batchId, failures = 0) {
    batch.controller = new AbortController();
    try {
      const data = await api(`/api/batches/${batchId}/`, { signal: batch.controller.signal });
      renderBatch(data);
      if (data.status_counts.queued === 0 && data.status_counts.processing === 0) {
        finishBatch(data);
        return;
      }
      batch.timer = setTimeout(() => poll(batchId), POLL_MS);
    } catch (error) {
      if (error.name === 'AbortError' || !batch.running) return;
      if (error.status === 403 || error.status === 404 || failures >= 4) {
        finishBatch(null, `Stopped checking batch #${batchId}: ${error.message}`, 'danger');
        return;
      }
      batch.timer = setTimeout(() => poll(batchId, failures + 1), POLL_MS * (failures + 2));
    }
  }

  batch.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert(batch.alert);
    if (!batch.files.length || batch.running) return;
    if (batch.files.length > MAX_FILES) {
      showAlert(batch.alert, `A batch can hold at most ${MAX_FILES} files.`);
      return;
    }
    const body = new FormData();
    body.append('product', batch.product.value);
    batch.files.forEach((file) => body.append('files', file));

    stopPolling();
    batch.running = true;
    batch.results.replaceChildren(UI.state('loading', 'Uploading files…'));
    batch.progress.hidden = true;
    updateBatchUi();
    try {
      const data = await api('/api/batches/', { method: 'POST', body });
      batch.files = [];
      batch.results.replaceChildren();
      renderBatch(data);
      updateBatchUi();
      if (data.status_counts.queued === 0 && data.status_counts.processing === 0) finishBatch(data);
      else batch.timer = setTimeout(() => poll(data.id), POLL_MS);
    } catch (error) {
      batch.running = false;
      batch.results.replaceChildren(UI.state('error', 'The batch was not created', error.message));
      showAlert(batch.alert, error.message);
      updateBatchUi();
    }
  });

  /* ================= History ================= */

  const hist = {
    prediction: document.getElementById('history-prediction'),
    review: document.getElementById('history-review'),
    body: document.getElementById('history-body'),
    count: document.getElementById('history-count'),
    refresh: document.getElementById('history-refresh'),
  };
  let historyStale = true;
  let historyRequest = 0;

  async function loadHistory() {
    const request = ++historyRequest;
    historyStale = false;
    hist.body.replaceChildren(UI.state('loading', 'Loading your inspections…'));
    try {
      const items = await api(UI.filterQuery(hist.prediction.value, hist.review.value));
      if (request !== historyRequest) return; // a newer filter change won
      const filtered = hist.prediction.value || hist.review.value;
      hist.count.textContent = `${items.length} inspection${items.length === 1 ? '' : 's'}${filtered ? ' match' : ''}`;
      hist.body.replaceChildren(items.length
        ? UI.historyTable(items, { onOpen: openDetail })
        : UI.state('empty',
          filtered ? 'No inspections match these filters' : 'No inspections yet',
          filtered ? 'Try a different result or review state.' : 'Inspect a plate or run a batch, and it will appear here.'));
    } catch (error) {
      if (request !== historyRequest) return;
      hist.count.textContent = '';
      hist.body.replaceChildren(UI.state('error', 'Could not load your history', error.message));
    }
  }

  function openDetail(item) {
    UI.showDialog(`Inspection #${item.id} · ${item.original_filename}`,
      UI.detailLayout(item, [UI.originalBlock(item), UI.reviewBlock(item)]));
  }

  hist.prediction.addEventListener('change', loadHistory);
  hist.review.addEventListener('change', loadHistory);
  hist.refresh.addEventListener('click', loadHistory);

  function showTab(hash) {
    const link = document.querySelector(`[data-tabs] [href="${hash}"]`);
    if (link && window.bootstrap) window.bootstrap.Tab.getOrCreateInstance(link).show();
  }
  document.getElementById('tab-history').addEventListener('shown.bs.tab', () => {
    if (historyStale) loadHistory();
  });
  if (window.location.hash === '#history') loadHistory();

  loadProducts();
  restoreLastSingle();
})();
