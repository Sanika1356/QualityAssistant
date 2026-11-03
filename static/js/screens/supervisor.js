/* Supervisor screen: quality incidents (default), then all inspections, filters, search, and one-time reviews.
 * Table and review-panel layout follow Person 4's supervisor_history screen; all data comes from the API.
 */
(function () {
  'use strict';
  const { api, showAlert, setBusy } = window.App;
  const UI = window.UI;
  const { el } = UI;

  UI.hashTabs(document.querySelector('[data-tabs]'));

  const s = {
    prediction: document.getElementById('sup-prediction'),
    review: document.getElementById('sup-review'),
    search: document.getElementById('sup-search'),
    refresh: document.getElementById('sup-refresh'),
    body: document.getElementById('sup-body'),
    count: document.getElementById('sup-count'),
    summary: document.getElementById('sup-summary'),
    items: [],
    request: 0,
  };

  function matches(item, text) {
    if (!text) return true;
    const needle = text.toLowerCase();
    return item.original_filename.toLowerCase().includes(needle)
      || (item.submitted_by || '').toLowerCase().includes(needle);
  }

  function renderSummary(items) {
    const count = (fn) => items.filter(fn).length;
    const tiles = [
      ['In this list', items.length],
      ['Awaiting review', count((i) => i.review_status === 'pending')],
      ['Reviewed', count((i) => i.review)],
      ['Failed uploads', count((i) => i.status === 'failed')],
    ];
    s.summary.hidden = false;
    s.summary.replaceChildren(...tiles.map(([label, value]) =>
      el('div', {}, el('div', { class: 'label', text: label }), el('div', { class: 'value', text: value }))));
  }

  function render() {
    const text = s.search.value.trim();
    const shown = s.items.filter((item) => matches(item, text));
    const filtered = s.prediction.value || s.review.value || text;
    s.count.textContent = text
      ? `Showing ${shown.length} of ${s.items.length}`
      : `${s.items.length} inspection${s.items.length === 1 ? '' : 's'}`;
    renderSummary(shown);
    s.body.replaceChildren(shown.length
      ? UI.historyTable(shown, {
        showEngineer: true,
        onOpen: (item) => openDetail(item.id),
        openLabel: (item) => (item.review_status === 'pending' ? 'Review' : 'View'),
      })
      : UI.state('empty',
        filtered ? 'Nothing matches these filters' : 'No inspections yet',
        filtered ? 'Clear the search or choose different filters.' : 'Engineers’ inspections will appear here.',
        text ? 'search' : 'inbox'));
  }

  async function load() {
    const request = ++s.request;
    s.body.replaceChildren(UI.state('loading', 'Loading inspections…'));
    try {
      const items = await api(UI.filterQuery(s.prediction.value, s.review.value));
      if (request !== s.request) return;
      s.items = items;
      render();
    } catch (error) {
      if (request !== s.request) return;
      s.summary.hidden = true;
      s.count.textContent = '';
      s.body.replaceChildren(UI.state('error', 'Could not load inspections', error.message));
    }
  }

  /* ---------- Review form ---------- */

  function reviewForm(item) {
    const predicted = item.predicted_class;
    const other = predicted === 'Defective' ? 'Normal' : 'Defective';
    const alertBox = el('div', { hidden: true });
    const comment = el('textarea', {
      class: 'form-control', id: `review-comment-${item.id}`, rows: 3, maxlength: 1000,
      placeholder: 'For example: scratch visible near the top edge',
    });
    const submit = el('button', { type: 'submit', class: 'btn btn-primary', text: 'Save review', disabled: true });
    const choice = (value, title, sub) => {
      const id = `review-${item.id}-${value}`;
      return el('div', { class: 'choice' },
        el('input', {
          type: 'radio', name: 'reviewed_class', id, value, required: true,
          onchange: () => { submit.disabled = false; },
        }),
        el('label', { for: id }, el('span', { class: 'choice-title', text: title }), el('span', { class: 'choice-sub', text: sub })));
    };

    const form = el('form', { class: 'detail-block is-review', novalidate: true, 'aria-labelledby': `review-title-${item.id}` },
      el('h3', { id: `review-title-${item.id}` }, el('span', { text: 'Your review' }), UI.reviewChip(item)),
      alertBox,
      el('fieldset', { class: 'mb-3' },
        el('legend', { class: 'form-label fs-6', text: 'Is the model right?' }),
        el('div', { class: 'choice-group' },
          choice(predicted, `Confirm ${predicted}`, 'The model is right.'),
          choice(other, `Correct to ${other}`, 'The model is wrong.'))),
      el('div', { class: 'mb-3' },
        el('label', { class: 'form-label', for: `review-comment-${item.id}` }, 'Comment ', el('span', { class: 'muted', text: '(optional)' })),
        comment),
      el('div', { class: 'note mb-3', text: 'Each inspection can be reviewed only once, and a saved review cannot be changed. The model’s original output is always kept.' }),
      submit);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const selected = form.querySelector('input[name="reviewed_class"]:checked');
      if (!selected) {
        showAlert(alertBox, 'Choose Confirm or Correct first.');
        return;
      }
      setBusy(submit, true, 'Saving…');
      try {
        await api(`/api/inspections/${item.id}/review/`, {
          method: 'POST', body: { reviewed_class: selected.value, comment: comment.value.trim() },
        });
        // Read it back from the server to show it really was saved.
        await openDetail(item.id, 'Review saved. This view was reloaded from the server.');
        load();
      } catch (error) {
        setBusy(submit, false);
        showAlert(alertBox, error.message);
      }
    });
    return form;
  }

  async function openDetail(id, message) {
    let item;
    try {
      item = await api(`/api/inspections/${id}/`);
    } catch (error) {
      UI.showDialog(`Inspection #${id}`, UI.state('error', 'Could not open this inspection', error.message));
      return;
    }
    const blocks = [];
    if (message) blocks.push(el('div', { class: 'alert alert-success', role: 'status', text: message }));
    blocks.push(UI.originalBlock(item));
    if (item.review_status === 'pending') blocks.push(reviewForm(item));
    else blocks.push(UI.reviewBlock(item));
    UI.showDialog(`Inspection #${item.id} · ${item.original_filename}`, UI.detailLayout(item, blocks));
  }

  s.prediction.addEventListener('change', load);
  s.review.addEventListener('change', load);
  s.refresh.addEventListener('click', load);
  s.search.addEventListener('input', render);
  document.getElementById('sup-filters').addEventListener('submit', (e) => e.preventDefault());

  /* Round 3: Supervisor Dashboard (quality incidents), the default view */
  const incidents = window.Incidents.mount({
    tab: document.getElementById('tab-incidents'),
    isDefault: true,
    list: document.getElementById('incidents-list'),
    detail: document.getElementById('incident-detail'),
    body: document.getElementById('incidents-body'),
    count: document.getElementById('incidents-count'),
    summary: document.getElementById('incidents-summary'),
    filter: document.getElementById('incidents-filter'),
    refresh: document.getElementById('incidents-refresh'),
    canDecide: true,
    showEngineer: true,
  });
  incidents.route();

  load();
})();
