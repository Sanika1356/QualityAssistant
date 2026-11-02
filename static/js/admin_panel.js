(function () {
  'use strict';
  const { api, showAlert, clearAlert, setBusy, showFieldErrors, clearFieldErrors } = window.App;

  const els = {
    body: document.getElementById('products-body'),
    tableWrap: document.getElementById('products-table-wrap'),
    loading: document.getElementById('products-loading'),
    empty: document.getElementById('products-empty'),
    count: document.getElementById('product-count'),
    listAlert: document.getElementById('products-alert'),
    form: document.getElementById('product-form'),
    formAlert: document.getElementById('add-alert'),
  };

  function cell(text, className) {
    const td = document.createElement('td');
    if (className) {
      const span = document.createElement('span');
      span.className = className;
      span.textContent = text;
      td.appendChild(span);
    } else {
      td.textContent = text; // textContent, never innerHTML: product text is user input
    }
    return td;
  }

  function render(products, highlightId) {
    els.body.replaceChildren();
    for (const product of products) {
      const row = document.createElement('tr');
      row.append(
        cell(product.product_id, 'code-id'),
        cell(product.name),
        product.description ? cell(product.description) : cell('—', 'muted'),
      );
      if (product.product_id === highlightId) row.classList.add('table-active');
      els.body.appendChild(row);
    }
    els.loading.hidden = true;
    els.empty.hidden = products.length > 0;
    els.tableWrap.hidden = products.length === 0;
    els.count.textContent = products.length === 1 ? '1 product' : `${products.length} products`;
  }

  async function load(highlightId) {
    clearAlert(els.listAlert);
    try {
      const data = await api('/api/products/');
      render(Array.isArray(data) ? data : data.results || [], highlightId);
    } catch (error) {
      els.loading.hidden = true;
      showAlert(els.listAlert, `Could not load products: ${error.message}`);
    }
  }

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
    setBusy(button, true, 'Adding…');
    try {
      const created = await api('/api/products/', { method: 'POST', body });
      els.form.reset();
      showAlert(els.formAlert, `Added ${created.product_id}.`, 'success');
      await load(created.product_id);
      els.form.product_id.focus();
    } catch (error) {
      if (Object.keys(error.fieldErrors).length) showFieldErrors(els.form, error.fieldErrors);
      showAlert(els.formAlert, error.message);
    } finally {
      setBusy(button, false);
    }
  });

  load();
})();
