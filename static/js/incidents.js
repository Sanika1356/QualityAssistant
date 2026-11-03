/* Round 3: shared incident screens for Engineers and Supervisors.
 * Everything is built with createElement/textContent: AI and API text is never parsed as HTML.
 */
(function () {
  'use strict';
  const { api, showAlert, setBusy } = window.App;
  const UI = window.UI;
  const { el } = UI;
  const URL = '/api/incidents/';

  const ENGINEER_DENIAL_COMMENT = 'Engineer review attempt: the server must refuse this.';

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

  /* Evidence status and its reason are always shown, whatever the status. */
  function evidenceBanner(incident) {
    const sufficient = incident.evidence_status === 'Sufficient';
    return el('div', {
      class: `incident-evidence ${sufficient ? 'is-sufficient' : 'is-insufficient'}`, role: 'status',
    },
    el('div', { class: 'incident-evidence-head' },
      evidenceChip(incident.evidence_status),
      incident.manual_review_required
        ? el('strong', { class: 'incident-manual', text: 'Manual review required' }) : null),
    el('p', { class: 'mb-0', text: incident.evidence_reason || 'No reason was recorded.' }));
  }

  /* The saved Round 2 inspection this incident was created from. */
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
    return block(
      [el('span', { text: 'Saved inspection' }), el('span', { class: 'chip chip-muted', text: `#${incident.inspection_id}` })],
      'incident-inspection',
      el('div', { class: 'incident-inspection-grid' },
        image,
        facts([
          ['File name', incident.inspection_original_filename || '—'],
          ['Inspected', UI.when(incident.inspection_inspected_at)],
          ['Submitted by', incident.inspection_submitted_by || '—'],
          ['Product', `${incident.product_id_snapshot} (${incident.product_name_snapshot})`],
        ])));
  }

  function originalResult(incident) {
    return block(
      [el('span', { text: 'Original classifier result' }), el('span', { class: 'chip chip-muted', text: 'Never edited' })],
      'is-original',
      facts([
        ['Result', UI.resultBadge(incident.original_prediction)],
        ['Confidence', UI.percent(incident.original_confidence)],
        ['Defect probability', UI.probability(incident.original_defect_probability)],
        ['Model version', incident.model_version_snapshot || '—'],
      ]));
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

  /* Each cited document once, with its revision and a link to the whole PDF. */
  function documentsUsed(incident) {
    const seen = new Map();
    for (const source of incident.sources || []) {
      const key = `${source.document_id}|${source.revision}`;
      if (!seen.has(key)) seen.set(key, source);
    }
    const documents = [...seen.values()];
    return block('Documents used', '',
      documents.length
        ? el('ul', { class: 'incident-documents' }, documents.map((source) =>
          el('li', {},
            el('span', {}, el('strong', { text: source.document_id }), ` Revision ${source.revision}`),
            el('a', {
              href: source.source_url.split('#')[0], target: '_blank', rel: 'noopener', text: 'Open PDF',
              'aria-label': `Open ${source.document_id} revision ${source.revision} in a new tab`,
            }))))
        : el('p', { class: 'muted mb-0', text: 'No SOP document supports a suggested action for this incident.' }));
  }

  function contentBlocks(incident) {
    const blocks = [evidenceBanner(incident), inspectionBlock(incident), originalResult(incident)];
    if (incident.human_correction) {
      blocks.push(block('Human correction (recorded separately)', 'is-review',
        el('p', { class: 'mb-0', text: incident.human_correction })));
    }
    blocks.push(block([el('span', { text: 'Incident' }), evidenceChip(incident.evidence_status)], '',
      facts([
        ['Incident ID', incident.incident_id],
        ['Created by', incident.created_by],
        ['Created', UI.when(incident.created_at)],
      ]),
      el('p', { class: 'incident-summary', text: incident.summary })));
    blocks.push(block('Suggested next actions', '',
      incident.actions.length
        ? el('ol', { class: 'incident-actions' }, incident.actions.map((action) =>
          el('li', {},
            el('p', { class: 'incident-action-text', text: action.text }),
            el('ul', { class: 'incident-sources' }, action.sources.map(sourceCard)))))
        : el('p', { class: 'muted mb-0', text: 'No suggested actions. A person must review this incident manually.' })));
    blocks.push(documentsUsed(incident));
    return blocks;
  }

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
        after = ` Checked again: the decision is still ${fresh.decision}.`;
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

  function decisionBlock(incident, options) {
    const pending = incident.decision === 'Pending';
    return block([el('span', { text: 'Supervisor decision' }), decisionChip(incident.decision)], 'is-review',
      pending
        ? el('p', { class: 'muted mb-0', text: 'Waiting for a Supervisor. Only a Supervisor can record a decision.' })
        : facts([
          ['Reviewer', incident.reviewer || '—'],
          ['Decided', UI.when(incident.reviewed_at)],
          ['Comment', incident.review_comment || '—'],
        ]),
      pending && options.engineerView ? engineerAttempt(incident) : null,
      el('p', { class: 'note mt-3 mb-0', text: 'Approval is for follow-up only. It does not release or scrap the item.' }));
  }

  function decisionForm(incident, onSaved) {
    const alertBox = el('div', { hidden: true });
    const canApprove = incident.evidence_status === 'Sufficient';
    const comment = el('textarea', {
      class: 'form-control', id: 'incident-comment', rows: 3, maxlength: 1000, required: true,
    });
    const select = el('select', { class: 'form-select', id: 'incident-decision', required: true },
      el('option', { value: '', text: 'Choose a decision' }),
      canApprove ? el('option', { value: 'Approved for follow-up', text: 'Approved for follow-up' }) : null,
      el('option', { value: 'Needs more information', text: 'Needs more information' }));
    const submit = el('button', { type: 'submit', class: 'btn btn-primary', text: 'Save decision' });
    const form = el('form', { class: 'detail-block is-review', novalidate: true },
      el('h3', {}, el('span', { text: 'Your decision' }), decisionChip(incident.decision)),
      alertBox,
      canApprove ? null : el('p', { class: 'note', text: 'Evidence is insufficient, so this incident cannot be approved.' }),
      el('div', { class: 'mb-3' }, el('label', { class: 'form-label', for: 'incident-decision', text: 'Decision' }), select),
      el('div', { class: 'mb-3' }, el('label', { class: 'form-label', for: 'incident-comment', text: 'Comment (required)' }), comment),
      el('p', { class: 'note', text: 'Approval is for follow-up only. It does not release or scrap the item.' }),
      submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!select.value) { showAlert(alertBox, 'Choose a decision first.'); return; }
      if (!comment.value.trim()) { showAlert(alertBox, 'Write a comment before saving.'); return; }
      setBusy(submit, true, 'Saving…');
      try {
        await api(`${URL}${incident.incident_id}/decision/`, {
          method: 'POST', body: { decision: select.value, review_comment: comment.value.trim() },
        });
        await open(incident.incident_id, { canDecide: true, message: 'Decision saved. This view was reloaded from the server.' });
        if (onSaved) onSaved();
      } catch (error) {
        setBusy(submit, false);
        showAlert(alertBox, error.message);
      }
    });
    return form;
  }

  /* canDecide marks the Supervisor screen. Only Engineers otherwise can open incidents. */
  async function open(id, options = {}) {
    let incident;
    try {
      incident = await api(`${URL}${id}/`);
    } catch (error) {
      UI.showDialog('Incident', UI.state('error', 'Could not open this incident', error.message));
      return;
    }
    const blocks = [];
    if (options.message) blocks.push(el('div', { class: 'alert alert-success', role: 'status', text: options.message }));
    blocks.push(...contentBlocks(incident));
    blocks.push(options.canDecide && incident.decision === 'Pending'
      ? decisionForm(incident, options.onSaved)
      : decisionBlock(incident, { engineerView: !options.canDecide }));
    UI.showDialog(`Incident for inspection #${incident.inspection_id}`, el('div', { class: 'incident-view reveal' }, blocks));
  }

  /* The Incidents tab. */
  function listScreen({ body, count, filter, refresh, canDecide, showEngineer }) {
    let request = 0;
    async function load() {
      const current = ++request;
      body.replaceChildren(UI.state('loading', 'Loading incidents…'));
      try {
        let items = await api(URL);
        if (current !== request) return;
        const total = items.length;
        if (filter && filter.value) items = items.filter((i) => i.decision === filter.value);
        count.textContent = `${total} incident${total === 1 ? '' : 's'}`;
        if (!items.length) {
          body.replaceChildren(UI.state('empty', total ? 'Nothing matches this filter' : 'No incidents yet',
            total ? 'Choose a different decision.'
              : canDecide ? 'Incidents created by Engineers will appear here.'
                : 'Open a Defective inspection and choose Create incident.'));
          return;
        }
        const head = ['Inspection', 'Product', 'Evidence', 'Decision', 'Created', ''];
        if (showEngineer) head.splice(1, 0, 'Engineer');
        body.replaceChildren(el('div', { class: 'table-responsive' },
          el('table', { class: 'table table-vi table-actions' },
            el('thead', {}, el('tr', {}, head.map((h) => el('th', { scope: 'col', text: h })))),
            el('tbody', {}, items.map((i) => {
              const cells = [
                el('td', { text: `#${i.inspection_id}` }),
                el('td', { text: i.product_id_snapshot }),
                el('td', {}, evidenceChip(i.evidence_status)),
                el('td', {}, decisionChip(i.decision)),
                el('td', { text: UI.when(i.created_at) }),
                el('td', { class: 'text-end' }, el('button', {
                  type: 'button', class: 'btn btn-sm btn-outline-primary',
                  text: canDecide && i.decision === 'Pending' ? 'Review' : 'View',
                  'aria-label': `Open incident for inspection ${i.inspection_id}`,
                  onclick: () => open(i.incident_id, { canDecide, onSaved: load }),
                })),
              ];
              if (showEngineer) cells.splice(1, 0, el('td', { text: i.created_by }));
              return el('tr', {}, cells);
            })))));
      } catch (error) {
        if (current !== request) return;
        count.textContent = '';
        body.replaceChildren(UI.state('error', 'Could not load incidents', error.message));
      }
    }
    if (filter) filter.addEventListener('change', load);
    refresh.addEventListener('click', load);
    return load;
  }

  /* The Create incident button. The server decides who is eligible and explains refusals. */
  function createPanel(item, onChanged) {
    const alertBox = el('div', { hidden: true });
    const button = el('button', { type: 'button', class: 'btn btn-primary', text: 'Create incident' });
    button.addEventListener('click', async () => {
      alertBox.hidden = true;
      setBusy(button, true, 'Creating… this can take a minute');
      try {
        const before = await api(URL);
        const existed = before.some((i) => i.inspection_id === item.id);
        const incident = await api(URL, { method: 'POST', body: { inspection_id: item.id } });
        await open(incident.incident_id, {
          message: existed
            ? 'An incident already exists for this inspection. Here is the same one; nothing was changed.'
            : 'Incident created.',
        });
        if (onChanged) onChanged();
      } catch (error) {
        showAlert(alertBox, error.message);
      } finally {
        setBusy(button, false);
      }
    });
    return el('section', { class: 'detail-block' },
      el('h3', {}, el('span', { text: 'Quality incident' })),
      alertBox,
      el('p', { class: 'muted', text: 'Only completed inspections the classifier flagged as Defective can create an incident.' }),
      button);
  }

  window.Incidents = { open, listScreen, createPanel };
})();
