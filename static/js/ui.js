/* Shared building blocks for the inspection screens.
 * Everything is built with createElement/textContent: API text is never parsed as HTML.
 * Layout ideas for the history, batch and review screens come from Person 4's original screens.
 */
(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  /* el('div', {class: 'x', text: 'hi'}, child1, child2) */
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  /* Small line icons drawn from fixed path data (no user input). */
  const ICONS = {
    image: ['M4 5h16v14H4z', 'M4 16l5-5 4 4 3-3 4 4', 'M15.5 9.5a1.5 1.5 0 1 0 0-.01'],
    upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 16v4h16v-4'],
    inbox: ['M4 13l2-8h12l2 8', 'M4 13v6h16v-6', 'M4 13h5l1 2h4l1-2h5'],
    alert: ['M12 3l10 18H2z', 'M12 10v5', 'M12 18v.01'],
    search: ['M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z', 'M20 20l-4.8-4.8'],
  };

  function icon(name, className) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', className || 'state-icon');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    for (const d of ICONS[name] || []) {
      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('d', d);
      svg.append(path);
    }
    return svg;
  }

  /* ---------- Formatting ---------- */

  function percent(value) {
    if (value === null || value === undefined) return '—';
    const pct = Number(value) * 100;
    // Never print "100%": the model is uncalibrated and never truly certain.
    if (pct >= 99.95) return '> 99.9%';
    if (pct < 0.05) return '< 0.1%';
    return `${pct.toFixed(1)}%`;
  }

  function probability(value) {
    if (value === null || value === undefined) return '—';
    const v = Number(value);
    if (v >= 0.9995) return '> 0.999';
    if (v < 0.0005) return '< 0.001';
    return v.toFixed(3);
  }

  const dateFormat = new Intl.DateTimeFormat(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });

  function when(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date);
  }

  function capitalise(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : '';
  }

  /* ---------- Badges and chips ---------- */

  function resultBadge(predictedClass) {
    if (predictedClass === 'Normal') return el('span', { class: 'result result-normal', text: 'Normal' });
    if (predictedClass === 'Defective') return el('span', { class: 'result result-defective', text: 'Defective' });
    return el('span', { class: 'muted', text: '—' });
  }

  function statusChip(status) {
    const known = ['queued', 'processing', 'completed', 'failed'];
    const kind = known.includes(status) ? status : 'muted';
    return el('span', { class: `chip chip-${kind}`, text: capitalise(status || 'unknown') });
  }

  const REVIEW_LABELS = {
    pending: 'Awaiting review',
    confirmed: 'Confirmed',
    corrected: 'Corrected',
    not_reviewable: 'Not reviewable',
  };

  function reviewChip(item) {
    const status = item.review_status;
    const kind = status === 'not_reviewable' ? 'muted' : status;
    const chip = el('span', { class: `chip chip-${kind}`, text: REVIEW_LABELS[status] || capitalise(status) });
    if (status === 'corrected' && item.review) {
      return el('span', { class: 'd-inline-flex flex-wrap align-items-center gap-1' },
        chip, el('span', { class: 'sub', text: `to ${item.review.reviewed_class}` }));
    }
    return chip;
  }

  function thumb(item, size) {
    if (!item.image_url) {
      return el('span', { class: 'thumb thumb-empty', title: 'No saved image', text: 'None' });
    }
    return el('img', {
      class: 'thumb', src: item.image_url, alt: `Thumbnail of ${item.original_filename}`,
      loading: 'lazy', width: size || 44, height: size || 44,
    });
  }

  /* ---------- States ---------- */

  function state(kind, title, message, iconName) {
    const role = kind === 'error' ? 'alert' : 'status';
    return el('div', { class: `state${kind === 'error' ? ' state-error' : ''}`, role },
      kind === 'loading'
        ? el('div', { class: 'spinner-border spinner-border-sm text-secondary', 'aria-hidden': 'true' })
        : icon(iconName || (kind === 'error' ? 'alert' : 'inbox')),
      el('div', { class: 'state-title', text: title }),
      message ? el('div', { class: 'small', text: message }) : null);
  }

  /* ---------- Result hero ---------- */

  function verdictCard(item, options = {}) {
    const failed = item.status === 'failed' || !item.predicted_class;
    const kind = failed ? 'is-failed' : item.predicted_class === 'Defective' ? 'is-defective' : 'is-normal';
    const glyph = failed ? '×' : item.predicted_class === 'Defective' ? '!' : '✓';
    const word = failed ? 'Not inspected' : item.predicted_class;
    const note = failed
      ? item.failure_reason || 'This image could not be inspected.'
      : item.predicted_class === 'Defective'
        ? 'The model found signs of a scratch or pit on this plate.'
        : 'The model found no defect on this plate.';

    const media = el('div', { class: 'verdict-media' },
      item.image_url
        ? el('img', { src: item.image_url, alt: `Inspected plate: ${item.original_filename}` })
        : el('div', { class: 'text-center', style: 'color:#9fb0c1' }, icon('image'), el('div', { class: 'small', text: 'No saved image' })));

    const body = el('div', { class: 'verdict-body' },
      el('div', {},
        el('div', { class: 'eyebrow', text: options.eyebrow || 'Model verdict' }),
        el('div', { class: 'verdict-word', role: 'status' },
          el('span', { class: 'verdict-icon', 'aria-hidden': 'true', text: glyph }),
          el('span', { text: word })),
        el('p', { class: 'verdict-note', text: note })));

    if (!failed) {
      const confidence = Number(item.confidence) || 0;
      body.append(el('div', {},
        el('div', { class: 'meter-head' },
          el('span', { class: 'eyebrow', id: `conf-label-${item.id}`, text: 'Confidence' }),
          el('span', { class: 'meter-value', text: percent(item.confidence) })),
        el('div', {
          class: 'meter', role: 'meter', 'aria-labelledby': `conf-label-${item.id}`,
          'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(confidence * 100),
        }, el('div', { class: 'meter-fill', style: `width:${Math.max(2, Math.min(100, confidence * 100))}%` })),
        el('div', {
          class: 'meter-caption',
          text: `Defect probability ${probability(item.defect_probability)}. Plates at 0.5 or above are marked Defective. Scores are uncalibrated.`,
        })));
    }

    const facts = [
      ['Model version', item.model_version || '—'],
      ['Inspected', when(item.created_at)],
      ['File', item.original_filename],
      ['Inspection', `#${item.id}`],
    ];
    if (item.product) facts.push(['Product', item.product]);
    if (item.submitted_by) facts.push(['Engineer', item.submitted_by]);
    body.append(el('dl', { class: 'facts' },
      facts.map(([label, value]) => el('div', {}, el('dt', { text: label }), el('dd', { text: value })))));

    return el('article', { class: `verdict-card ${kind} reveal`, 'aria-label': `Result for ${item.original_filename}` },
      media, body);
  }

  /* ---------- Original output vs review (detail dialog) ---------- */

  function originalBlock(item) {
    const rows = item.status === 'completed'
      ? [
        ['Result', resultBadge(item.predicted_class)],
        ['Confidence', percent(item.confidence)],
        ['Defect probability', probability(item.defect_probability)],
        ['Model version', item.model_version],
      ]
      : [['Status', statusChip(item.status)], ['Reason', item.failure_reason || '—']];
    rows.push(['Inspected', when(item.created_at)], ['Engineer', item.submitted_by || '—'], ['File', item.original_filename]);
    const ran = item.status === 'completed';
    return el('section', { class: 'detail-block is-original', 'aria-labelledby': `orig-${item.id}` },
      el('h3', { id: `orig-${item.id}` }, el('span', { text: ran ? 'Original model output' : 'Upload result' }),
        ran ? el('span', { class: 'chip chip-muted', text: 'Never edited' }) : null),
      el('dl', { class: 'facts', style: 'border-top:0;padding-top:0' },
        rows.map(([label, value]) => el('div', {}, el('dt', { text: label }), el('dd', {}, value)))));
  }

  function reviewBlock(item) {
    const block = el('section', { class: 'detail-block is-review', 'aria-labelledby': `rev-${item.id}` },
      el('h3', { id: `rev-${item.id}` }, el('span', { text: 'Supervisor review' }), reviewChip(item)));
    if (item.review) {
      const r = item.review;
      block.append(el('dl', { class: 'facts', style: 'border-top:0;padding-top:0' },
        el('div', {}, el('dt', { text: 'Reviewed result' }), el('dd', {}, resultBadge(r.reviewed_class))),
        el('div', {}, el('dt', { text: 'Reviewer' }), el('dd', { text: r.reviewer })),
        el('div', {}, el('dt', { text: 'Reviewed' }), el('dd', { text: when(r.reviewed_at) })),
        el('div', { style: 'grid-column:1/-1' }, el('dt', { text: 'Comment' }),
          el('dd', { style: 'font-weight:400', text: r.comment || 'No comment.' }))));
    } else if (item.review_status === 'not_reviewable') {
      block.append(el('p', { class: 'muted mb-0', text: 'This upload failed, so there is no model output to review.' }));
    } else {
      block.append(el('p', { class: 'muted mb-0', text: 'Not reviewed yet.' }));
    }
    return block;
  }

  /* ---------- Inspection table (history) ---------- */

  function historyTable(items, options = {}) {
    const head = ['Image', 'Result', 'Confidence', 'Status', 'Review'];
    if (options.showEngineer) head.splice(1, 0, 'Engineer');
    if (options.onOpen) head.push('');
    const rows = items.map((item) => {
      const cells = [
        el('td', {}, el('div', { class: 'cell-file' }, thumb(item),
          el('div', {}, el('div', { class: 'file-name', text: item.original_filename }),
            el('div', { class: 'sub', text: `#${item.id} · ${when(item.created_at)}` })))),
        el('td', {}, resultBadge(item.predicted_class)),
        el('td', { class: 'num', text: item.status === 'completed' ? percent(item.confidence) : '—' }),
        el('td', {}, statusChip(item.status),
          item.status === 'failed' && item.failure_reason ? el('div', { class: 'reason mt-1', text: item.failure_reason }) : null),
        el('td', {}, reviewChip(item)),
      ];
      if (options.showEngineer) cells.splice(1, 0, el('td', { text: item.submitted_by }));
      if (options.onOpen) {
        const label = options.openLabel ? options.openLabel(item) : 'View';
        cells.push(el('td', { class: 'text-end' }, el('button', {
          type: 'button', class: 'btn btn-sm btn-outline-primary',
          'aria-label': `${label} inspection ${item.id}, ${item.original_filename}`,
          text: label, onclick: () => options.onOpen(item),
        })));
      }
      return el('tr', { dataset: { id: item.id } }, cells);
    });
    return el('div', { class: 'table-responsive' },
      el('table', { class: 'table table-vi' },
        el('thead', {}, el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))),
        el('tbody', {}, rows)));
  }

  function filterQuery(prediction, reviewStatus) {
    const params = new URLSearchParams();
    if (prediction) params.set('prediction', prediction);
    if (reviewStatus) params.set('review_status', reviewStatus);
    const query = params.toString();
    return `/api/inspections/${query ? `?${query}` : ''}`;
  }

  /* Image on the left, information blocks on the right. */
  function detailLayout(item, blocks) {
    return el('div', { class: 'detail-grid reveal' },
      el('div', { class: 'detail-image' },
        item.image_url
          ? el('img', { src: item.image_url, alt: `Inspected plate: ${item.original_filename}` })
          : el('div', { class: 'text-center', style: 'color:#9fb0c1' }, icon('image'),
            el('div', { class: 'small', text: 'No saved image: the upload failed before it was stored.' }))),
      el('div', {}, blocks));
  }

  function showDialog(title, content) {
    const dialog = document.getElementById('inspection-dialog');
    dialog.querySelector('.modal-title').textContent = title;
    dialog.querySelector('.modal-body').replaceChildren(content);
    window.bootstrap.Modal.getOrCreateInstance(dialog).show();
    return dialog;
  }

  /* Tabs that follow the URL hash, so /engineer/#batch opens the batch tab. */
  function hashTabs(container) {
    const links = [...container.querySelectorAll('[data-bs-toggle="pill"]')];
    const show = (hash) => {
      const link = links.find((l) => l.getAttribute('href') === hash);
      if (link && window.bootstrap) window.bootstrap.Tab.getOrCreateInstance(link).show();
    };
    links.forEach((link) => link.addEventListener('shown.bs.tab', () => {
      history.replaceState(null, '', link.getAttribute('href'));
    }));
    if (window.location.hash) show(window.location.hash);
    // Back/forward buttons and #links on the same page change only the hash.
    window.addEventListener('hashchange', () => show(window.location.hash));
  }

  window.UI = {
    el, icon, percent, probability, when, capitalise, resultBadge, statusChip, reviewChip, thumb,
    state, verdictCard, originalBlock, reviewBlock, historyTable, filterQuery, hashTabs, detailLayout, showDialog,
  };
})();
