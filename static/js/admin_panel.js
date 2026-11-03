(function () {
  'use strict';
  const { api, showAlert, clearAlert, setBusy, showFieldErrors, clearFieldErrors } = window.App;

  const els = {
    body: document.getElementById('products-body'),
    tableWrap: document.getElementById('products-table-wrap'),
    state: document.getElementById('products-state'),
    count: document.getElementById('product-count'),
    search: document.getElementById('product-search'),
    listAlert: document.getElementById('products-alert'),
    form: document.getElementById('product-form'),
    formAlert: document.getElementById('add-alert'),
  };
  let products = [];
  let highlightId = null;

  function cell(text, className) {
    const td = document.createElement('td');
    if (className) {
      const span = document.createElement('span');
      span.className = className;
      span.textContent = text;
      td.appendChild(span);
    } else {
      td.textContent = text; // textContent, never HTML: product text is user input
    }
    return td;
  }

  function render() {
    const needle = els.search.value.trim().toLowerCase();
    const shown = products.filter((p) => !needle
      || p.product_id.toLowerCase().includes(needle) || p.name.toLowerCase().includes(needle));

    els.count.textContent = needle
      ? `${shown.length} of ${products.length}`
      : `${products.length} product${products.length === 1 ? '' : 's'}`;

    els.body.replaceChildren(...shown.map((product) => {
      const row = document.createElement('tr');
      row.append(
        cell(product.product_id, 'code-id'),
        cell(product.name),
        product.description ? cell(product.description) : cell('—', 'muted'),
      );
      if (product.product_id === highlightId) row.classList.add('table-active');
      return row;
    }));

    const empty = shown.length === 0;
    els.tableWrap.hidden = empty;
    els.state.hidden = !empty;
    if (empty) {
      els.state.textContent = products.length
        ? `No products match “${els.search.value.trim()}”. Try another ID or name.`
        : 'No products yet. Register the first one above.';
    }
  }

  async function load() {
    clearAlert(els.listAlert);
    try {
      const data = await api('/api/products/');
      products = Array.isArray(data) ? data : data.results || [];
      render();
    } catch (error) {
      els.state.hidden = true;
      showAlert(els.listAlert, `Could not load products: ${error.message}`);
    }
  }

  els.search.addEventListener('input', render);

  els.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert(els.formAlert);
    clearFieldErrors(els.form);

    const body = {
      product_id: els.form.product_id.value.trim(),
      name: els.form.name.value.trim(),
      description: els.form.description.value.trim(),
    };
    const missing = {};
    if (!body.product_id) missing.product_id = ['Enter a product ID.'];
    if (!body.name) missing.name = ['Enter a name.'];
    if (Object.keys(missing).length) {
      showFieldErrors(els.form, missing);
      return;
    }

    const button = els.form.querySelector('button[type="submit"]');
    setBusy(button, true, 'Registering…');
    try {
      const created = await api('/api/products/', { method: 'POST', body });
      els.form.reset();
      highlightId = created.product_id;
      showAlert(els.formAlert, `Registered ${created.product_id}.`, 'success');
      await load();
      els.form.product_id.focus();
    } catch (error) {
      if (Object.keys(error.fieldErrors).length) showFieldErrors(els.form, error.fieldErrors);
      else showAlert(els.formAlert, error.message);
    } finally {
      setBusy(button, false);
    }
  });

  load();
})();
