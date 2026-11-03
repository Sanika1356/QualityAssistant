/* Metrics panel: shows exactly what `python manage.py evaluate_samples` saved. Nothing is hard-coded. */
(function () {
  'use strict';
  const { api } = window.App;
  const { el, state, when } = window.UI;

  function matrix(data) {
    const [[tn, fp], [fn, tp]] = data.confusion_matrix.values;
    const [a, b] = data.confusion_matrix.order; // Normal, Defective
    const cell = (n, tag, extra) => el('div', {
      class: `cell ${extra || ''}${n > 0 ? ' has-value' : ''}`,
      role: 'cell', 'aria-label': `${tag}: ${n}`,
    }, el('span', { class: 'n', text: n }), el('span', { class: 'tag', text: tag }));

    return el('div', {},
      el('div', { class: 'eyebrow mb-2', text: 'Confusion matrix' }),
      el('div', { class: 'small muted mb-3', text: 'Rows are the true label, columns are what the model predicted.' }),
      el('div', { class: 'matrix', role: 'table', 'aria-label': 'Confusion matrix, rows actual, columns predicted' },
        el('div', { class: 'axis', role: 'columnheader', text: 'Actual ↓ / Predicted →' }),
        el('div', { class: 'axis', role: 'columnheader', text: a }),
        el('div', { class: 'axis', role: 'columnheader', text: b }),
        el('div', { class: 'axis axis-row', role: 'rowheader', text: a }),
        cell(tn, 'TN', 'is-correct'),
        cell(fp, 'FP'),
        el('div', { class: 'axis axis-row', role: 'rowheader', text: b }),
        cell(fn, 'FN · missed', 'is-missed'),
        cell(tp, 'TP', 'is-correct')));
  }

  function render(body, meta, data) {
    const recall = data.defect_recall;
    meta.textContent = `Run ${when(data.generated_at)}`;
    body.replaceChildren(el('div', { class: 'panel-body' },
      el('div', { class: 'row g-4 align-items-start' },
        el('div', { class: 'col-lg-6' }, matrix(data)),
        el('div', { class: 'col-lg-6' },
          el('div', { class: 'eyebrow', text: 'Defect recall' }),
          el('div', { class: 'd-flex align-items-baseline gap-2 mb-1' },
            el('span', { class: 'headline-stat', text: recall === null ? '—' : `${(recall * 100).toFixed(1)}%` }),
            el('span', { class: 'muted num', text: `${data.tp} of ${data.tp + data.fn} defective plates caught` })),
          el('p', { class: 'small muted', text: 'Recall = TP ÷ (TP + FN). It matters most here, because a missed defect can reach a customer.' }),
          el('dl', { class: 'stat-list mb-3' },
            [['TP · defect caught', data.tp], ['FN · defect missed', data.fn],
              ['FP · normal flagged', data.fp], ['TN · normal passed', data.tn],
              ['Images scored', data.sample_count], ['Model version', data.model_version]]
              .map(([label, value]) => el('div', {}, el('dt', { text: label }), el('dd', { text: value })))),
          el('div', { class: 'small mb-3' }, 'Produced by ', el('span', { class: 'cmd', text: data.command }),
            data.failures && data.failures.length ? ` · ${data.failures.length} image(s) failed to process` : ' · every image processed'))),
      el('div', { class: 'limitation mt-4', role: 'note' },
        el('strong', { text: 'Limitation. ' }),
        `These ${data.sample_count} images are synthetic, with fixed framing. A good score here cannot show how the model will do on real factory images.`)));
  }

  async function load(panel) {
    const body = panel.querySelector('[data-metrics-body]');
    const meta = panel.querySelector('[data-metrics-meta]');
    try {
      render(body, meta, await api('/api/metrics/'));
    } catch (error) {
      const missing = error.status === 404;
      body.replaceChildren(state(missing ? 'empty' : 'error',
        missing ? 'No evaluation has been run yet' : 'Could not load model metrics', error.message));
    }
  }

  document.querySelectorAll('[data-metrics-panel]').forEach(load);
})();
