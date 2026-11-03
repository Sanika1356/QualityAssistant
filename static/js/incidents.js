/* Round 3: shared Quality Incident screens for Engineers and Supervisors.
 * An incident opens as a page section at #incidents/<incident_id>, so it survives a reload.
 * Everything is built with createElement/textContent: AI and API text is never parsed as HTML.
 */
(function () {
  'use strict';
  const { api, showAlert, setBusy } = window.App;
  const UI = window.UI;
  const { el } = UI;
  const URL = '/api/incidents/';
  const LIST_HASH = '#incidents';
  const DETAIL_HASH = /^#incidents\/([0-9a-f-]{36})$/i;
  const ENGINEER_DENIAL_COMMENT = 'Engineer review attempt: the server must refuse this.';
  const NOT_RELEASE = 'Approval is for follow-up only. It is not product release and does not scrap or rework the item.';

  const incidentCode = (incident) => incident.incident_code || `INC-${incident.incident_number}`;
  const inspectionCode = (id) => `INS-${id}`;

  function decisionChip(decision) {
    const kind = decision === 'Pending' ? 'pending'
      : decision === 'Approved for follow-up' ? 'confirmed' : 'corrected';
    return el('span', { class: `chip chip-${kind}`, text: decision });
  }

  function evidenceChip(status) {
    return el('span', {
      class: `chip ${status === 'Sufficient' ? 'chip-confirmed' : 'chip-failed'}`,
      text: `Evidence: ${status}`,
    });
  }

  function facts(rows) {
    return el('dl', { class: 'facts incident-facts' },
      rows.map(([label, value]) => el('div', {}, el('dt', { text: label }), el('dd', {}, value))));
  }

  function block(title, extraClass, ...children) {
    return el('section', { class: `detail-block ${extraClass || ''}`.trim() },
      el('h3', {}, ...(Array.isArray(title) ? title : [el('span', { text: title })])),
      ...children);
  }

  /* ---------- Incident sections, in the order the screen shows them ---------- */

  function headerBlock(incident) {
    return el('header', { class: 'incident-header' },
      el('div', { class: 'incident-title-row' },
        el('h2', { class: 'incident-title', text: `Quality Incident ${incidentCode(incident)}` }),
        el('span', { class: 'incident-review-status' }, el('span', { class: 'muted small', text: 'Review status ' }),
          decisionChip(incident.decision))),
      el('p', { class: 'incident-id-line' }, `Incident ID: ${incident.incident_id}`),
      el('p', { class: 'incident-meta' },
        `Created by ${incident.created_by} · ${UI.when(incident.created_at)}`));
  }

  function inspectionBlock(incident) {
    const image = incident.inspection_image_url
      ? el('a', {
        href: incident.inspection_image_url, target: '_blank', rel: 'noopener', class: 'incident-image-link',
        'aria-label': 'Open the inspection image in a new tab',
      }, el('img', {
        class: 'incident-image', src: incident.inspection_image_url,
        alt: `Inspected plate: ${incident.inspection_original_filename}`,
      }))
      : el('span', { class: 'thumb thumb-empty incident-image', text: 'No image' });
    const section = block(
      [el('span', { text: 'Product and original inspection result' }), el('span', { class: 'chip chip-muted', text: 'Never edited' })],
      'is-original',
      el('div', { class: 'incident-inspection-grid' },
        image,
        facts([
          ['Product', `${incident.product_id_snapshot} (${incident.product_name_snapshot})`],
          ['Inspection', inspectionCode(incident.inspection_id)],
          ['Original prediction', UI.resultBadge(incident.original_prediction)],
          ['Confidence', UI.percent(incident.original_confidence)],
          ['Defect probability', UI.probability(incident.original_defect_probability)],
          ['Model version', incident.model_version_snapshot || '—'],
          ['File name', incident.inspection_original_filename || '—'],
          ['Inspected', UI.when(incident.inspection_inspected_at)],
          ['Submitted by', incident.inspection_submitted_by || '—'],
        ])));
    if (incident.human_correction) {
      section.append(el('div', { class: 'incident-correction' },
        el('strong', { text: 'Human correction (recorded separately). ' }), incident.human_correction));
    }
    return section;
  }

  function summaryBlock(incident) {
    return block('Incident summary', '', el('p', { class: 'incident-summary', text: incident.summary || '—' }));
  }

  function sourceCard(source) {
    return el('li', { class: 'incident-source' },
      el('div', { class: 'incident-source-head' },
        el('strong', { text: `${source.document_id}, Revision ${source.revision}, page ${source.page_number}` }),
        el('a', {
          href: source.source_url, target: '_blank', rel: 'noopener',
          text: `Open page ${source.page_number}`,
          'aria-label': `Open ${source.document_id} at page ${source.page_number} in a new tab`,
        })),
      el('blockquote', { class: 'incident-passage', text: source.passage }));
  }

  function actionsBlock(incident) {
    return block('AI suggested actions', '',
      incident.actions.length
        ? el('ol', { class: 'incident-actions' }, incident.actions.map((action) =>
          el('li', {},
            el('p', { class: 'incident-action-text', text: action.text }),
            el('ul', { class: 'incident-sources' }, action.sources.map(sourceCard)))))
        : el('p', { class: 'incident-empty', text: 'No supported actions available.' }));
  }

  /* Each cited SOP once, with its revision, the cited pages and a link to the PDF. */
  function documentsBlock(incident) {
    const documents = new Map();
    for (const source of incident.sources || []) {
      const key = `${source.document_id}|${source.revision}`;
      if (!documents.has(key)) documents.set(key, { ...source, pages: new Set() });
      documents.get(key).pages.add(source.page_number);
    }
    const items = [...documents.values()];
    return block('Supporting documents', '',
      items.length
        ? el('ul', { class: 'incident-documents' }, items.map((doc) => {
          const pages = [...doc.pages].sort((a, b) => a - b);
          return el('li', {},
            el('span', {}, el('strong', { text: doc.document_id }),
              ` · Revision ${doc.revision} · ${pages.length === 1 ? 'page' : 'pages'} ${pages.join(', ')}`),
            el('a', {
              href: `${doc.source_url.split('#')[0]}#page=${pages[0]}`, target: '_blank', rel: 'noopener', text: 'Open PDF',
              'aria-label': `Open ${doc.document_id} revision ${doc.revision} in a new tab`,
            }));
        }))
        : el('p', { class: 'incident-empty', text: 'No supporting documents, because no action is supported.' }));
  }

  function evidenceBlock(incident) {
    const sufficient = incident.evidence_status === 'Sufficient';
    return el('section', {
      class: `incident-evidence ${sufficient ? 'is-sufficient' : 'is-insufficient'}`, role: 'status',
      'aria-label': 'Evidence status',
    },
    el('h3', { class: 'incident-evidence-head' },
      sufficient ? evidenceChip('Sufficient') : el('span', { class: 'chip chip-failed', text: 'Insufficient evidence' }),
      incident.manual_review_required ? el('strong', { class: 'incident-manual', text: 'Manual review required' }) : null),
    el('p', { class: 'mb-0', text: incident.evidence_reason || 'No reason was recorded.' }));
  }

  /* ---------- Supervisor review ---------- */

  /* Lets an Engineer show that the server refuses their review. It really sends the request. */
  function engineerAttempt(incident) {
    const result = el('div', { hidden: true });
    const button = el('button', {
      type: 'button', class: 'btn btn-outline-secondary btn-sm', text: 'Attempt review as Engineer',
    });
    button.addEventListener('click', async () => {
      setBusy(button, true, 'Sending…');
      let message = '';
      let saved = false;
      try {
        await api(`${URL}${incident.incident_id}/decision/`, {
          method: 'POST',
          body: { decision: 'Needs more information', review_comment: ENGINEER_DENIAL_COMMENT },
        });
        saved = true;
      } catch (error) {
        message = error.message;
      }
      // Ask the server again, so the screen shows nothing was saved.
      let after = '';
      try {
        const fresh = await api(`${URL}${incident.incident_id}/`);
        after = ` Checked again: the review status is still ${fresh.decision}.`;
      } catch (error) {
        // The denial message is the important part; skip the re-check.
      }
      setBusy(button, false);
      result.hidden = false;
      result.className = `alert ${saved ? 'alert-warning' : 'alert-danger'} mt-3 mb-0`;
      result.setAttribute('role', 'alert');
      result.replaceChildren(
        el('strong', { text: saved ? 'Unexpected: the server accepted the review.' : 'Denied by the server: ' }),
        message, after);
    });
    return el('div', { class: 'incident-attempt' },
      el('p', {
        class: 'note mb-2',
        text: 'Engineers cannot review incidents. This button sends a real review request so you can see the server refuse it.',
      }),
      button, result);
  }

  function reviewSummary(incident, engineerView) {
    const pending = incident.decision === 'Pending';
    return block([el('span', { text: 'Supervisor review' }), decisionChip(incident.decision)], 'is-review',
      pending
        ? el('p', { class: 'muted mb-0', text: 'Waiting for a Supervisor. Only a Supervisor can record a decision.' })
        : facts([
          ['Decision', incident.decision],
          ['Reviewer', incident.reviewer || '—'],
          ['Reviewed', UI.when(incident.reviewed_at)],
          ['Comment', incident.review_comment || '—'],
        ]),
      pending && engineerView ? engineerAttempt(incident) : null,
      el('p', { class: 'note mt-3 mb-0', text: NOT_RELEASE }));
  }

  function reviewForm(incident, onSaved) {
    const alertBox = el('div', { hidden: true });
    const canApprove = incident.evidence_status === 'Sufficient';
    const comment = el('textarea', {
      class: 'form-control', id: 'incident-comment', rows: 3, maxlength: 1000, required: true,
    });
    const select = el('select', { class: 'form-select', id: 'incident-decision', required: true },
      el('option', { value: '', text: 'Choose a decision' }),
      canApprove ? el('option', { value: 'Approved for follow-up', text: 'Approved for follow-up' }) : null,
      el('option', { value: 'Needs more information', text: 'Needs more information' }));
    const submit = el('button', { type: 'submit', class: 'btn btn-primary', text: 'Submit review' });
    const form = el('form', { class: 'detail-block is-review', novalidate: true },
      el('h3', {}, el('span', { text: 'Supervisor Review' }), decisionChip(incident.decision)),
      alertBox,
      canApprove ? null : el('p', { class: 'note', text: 'Evidence is insufficient, so this incident cannot be approved.' }),
      el('div', { class: 'mb-3' }, el('label', { class: 'form-label', for: 'incident-decision', text: 'Decision' }), select),
      el('div', { class: 'mb-3' }, el('label', { class: 'form-label', for: 'incident-comment', text: 'Comment (required)' }), comment),
      el('p', { class: 'note', text: NOT_RELEASE }),
      submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!select.value) { showAlert(alertBox, 'Choose a decision first.'); return; }
      if (!comment.value.trim()) { showAlert(alertBox, 'Write a comment before submitting.'); return; }
      setBusy(submit, true, 'Submitting…');
      try {
        await api(`${URL}${incident.incident_id}/decision/`, {
          method: 'POST', body: { decision: select.value, review_comment: comment.value.trim() },
        });
        onSaved('Review submitted. This incident was reloaded from the server.');
      } catch (error) {
        setBusy(submit, false);
        showAlert(alertBox, error.message);
      }
    });
    return form;
  }

  function incidentPage(incident, { canDecide, message, onSaved }) {
    return el('div', { class: 'incident-view reveal' },
      message ? el('div', { class: 'alert alert-success', role: 'status', text: message }) : null,
      headerBlock(incident),
      inspectionBlock(incident),
      summaryBlock(incident),
      actionsBlock(incident),
      documentsBlock(incident),
      evidenceBlock(incident),
      canDecide && incident.decision === 'Pending'
        ? reviewForm(incident, onSaved)
        : reviewSummary(incident, !canDecide));
  }

  /* ---------- Navigation ---------- */

  let pendingMessage = null;

  /* Show an incident page. The hash change opens the Incidents tab and renders it. */
  function openIncident(id, message) {
    pendingMessage = message || null;
    const target = `${LIST_HASH}/${id}`;
    if (window.location.hash === target) window.dispatchEvent(new HashChangeEvent('hashchange'));
    else window.location.hash = target;
  }

  /* ---------- The Incidents tab: list view and incident page ----------
   * canDecide: the Supervisor screen. Only Engineers otherwise can open incidents. */
  function mount({ tab, isDefault, list, detail, body, count, summary, filter, refresh, canDecide, showEngineer, onChange }) {
    let request = 0;

    async function loadList() {
      const current = ++request;
      body.replaceChildren(UI.state('loading', 'Loading incidents…'));
      try {
        let items = await api(URL);
        if (current !== request) return;
        const total = items.length;
        if (summary) {
          summary.hidden = false;
          summary.replaceChildren(...[
            ['All incidents', total],
            ['Pending review', items.filter((i) => i.decision === 'Pending').length],
            ['Insufficient evidence', items.filter((i) => i.evidence_status === 'Insufficient').length],
          ].map(([label, value]) => el('div', {}, el('div', { class: 'label', text: label }), el('div', { class: 'value', text: value }))));
        }
        if (filter && filter.value) items = items.filter((i) => i.decision === filter.value);
        count.textContent = `${total} incident${total === 1 ? '' : 's'}`;
        if (!items.length) {
          body.replaceChildren(UI.state('empty', total ? 'Nothing matches this filter' : 'No incidents yet',
            total ? 'Choose a different review status.'
              : canDecide ? 'Incidents created by Engineers will appear here.'
                : 'Open a Defective inspection in My Inspections and choose Create Quality Incident.'));
          return;
        }
        const head = ['Incident', 'Product', 'Inspection', 'Evidence', 'Review status', 'Created', ''];
        if (showEngineer) head.splice(3, 0, 'Engineer');
        body.replaceChildren(el('div', { class: 'table-responsive' },
          el('table', { class: 'table table-vi table-actions' },
            el('thead', {}, el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))),
            el('tbody', {}, items.map((i) => {
              const cells = [
                el('td', {}, el('strong', { text: incidentCode(i) })),
                el('td', { text: i.product_id_snapshot }),
                el('td', { text: inspectionCode(i.inspection_id) }),
                el('td', {}, evidenceChip(i.evidence_status)),
                el('td', {}, decisionChip(i.decision)),
                el('td', { text: UI.when(i.created_at) }),
                el('td', { class: 'text-end' }, el('a', {
                  href: `${LIST_HASH}/${i.incident_id}`, class: 'btn btn-sm btn-outline-primary',
                  text: canDecide && i.decision === 'Pending' ? 'Review' : 'Open',
                  'aria-label': `Open ${incidentCode(i)} for inspection ${inspectionCode(i.inspection_id)}`,
                })),
              ];
              if (showEngineer) cells.splice(3, 0, el('td', { text: i.created_by }));
              return el('tr', {}, cells);
            })))));
      } catch (error) {
        if (current !== request) return;
        count.textContent = '';
        if (summary) summary.hidden = true;
        body.replaceChildren(UI.state('error', 'Could not load incidents', error.message));
      }
    }

    async function showDetail(id, message) {
      list.hidden = true;
      detail.hidden = false;
      const back = el('a', { href: LIST_HASH, class: 'btn btn-outline-primary btn-sm incident-back', text: '← All incidents' });
      detail.replaceChildren(back, UI.state('loading', 'Loading the incident…'));
      let incident;
      try {
        incident = await api(`${URL}${id}/`);
      } catch (error) {
        detail.replaceChildren(back, UI.state('error', 'Could not open this incident', error.message));
        return;
      }
      detail.replaceChildren(back, incidentPage(incident, {
        canDecide,
        message,
        onSaved: (savedMessage) => {
          showDetail(id, savedMessage);
          if (onChange) onChange();
        },
      }));
      detail.scrollIntoView({ block: 'start' });
    }

    function route() {
      const hash = window.location.hash;
      const match = hash.match(DETAIL_HASH);
      if (match) {
        const message = pendingMessage;
        pendingMessage = null;
        showDetail(match[1], message);
      } else if (hash === LIST_HASH || (hash === '' && isDefault)) {
        detail.hidden = true;
        detail.replaceChildren();
        list.hidden = false;
        loadList();
      }
    }

    if (filter) filter.addEventListener('change', loadList);
    refresh.addEventListener('click', loadList);
    window.addEventListener('hashchange', route);
    // Clicking the tab itself does not fire hashchange.
    tab.addEventListener('shown.bs.tab', () => { if (!DETAIL_HASH.test(window.location.hash)) route(); });
    return { route, loadList };
  }

  /* The Create Quality Incident button. The server decides who is eligible and explains refusals. */
  function createPanel(item, onChanged) {
    const alertBox = el('div', { hidden: true });
    const status = el('p', { class: 'incident-progress', hidden: true, role: 'status' });
    const button = el('button', { type: 'button', class: 'btn btn-primary btn-lg', text: 'Create Quality Incident' });
    button.addEventListener('click', async () => {
      alertBox.hidden = true;
      status.hidden = false;
      status.textContent = 'Finding the SOPs and preparing the incident…';
      setBusy(button, true, 'Finding the SOPs and preparing the incident…');
      try {
        const before = await api(URL);
        const existed = before.some((i) => i.inspection_id === item.id);
        const incident = await api(URL, { method: 'POST', body: { inspection_id: item.id } });
        if (onChanged) onChanged();
        openIncident(incident.incident_id, existed
          ? `An incident already exists for this inspection, so this is the same incident (${incidentCode(incident)}). Nothing was changed.`
          : `Incident ${incidentCode(incident)} created.`);
      } catch (error) {
        showAlert(alertBox, error.message);
      } finally {
        status.hidden = true;
        setBusy(button, false);
      }
    });
    return el('section', { class: 'detail-block incident-create' },
      el('h3', {}, el('span', { text: 'Quality incident' })),
      alertBox,
      el('p', { class: 'muted', text: 'Only completed inspections the classifier flagged as Defective can create an incident. If one already exists, you get the same incident back.' }),
      button, status);
  }

  window.Incidents = { mount, createPanel, openIncident, incidentCode, inspectionCode };
})();
