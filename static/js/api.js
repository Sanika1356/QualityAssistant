/* Shared browser helpers. Loaded on every page by templates/base.html.
 *
 *   const data = await api('/api/products/');                       // GET
 *   await api('/api/products/', { method: 'POST', body: { ... } });  // JSON body
 *   await api('/api/batches/',  { method: 'POST', body: formData }); // file upload
 *
 * api() sends the session cookie and the X-CSRFToken header, and throws an ApiError
 * whose .message is ready to show to the user (.status, .data, .fieldErrors for forms).
 */
(function () {
  'use strict';

  const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
  const SIGNED_OUT_DETAIL = 'Authentication credentials were not provided.';

  class ApiError extends Error {
    constructor(message, status, data, fieldErrors) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.data = data;
      this.fieldErrors = fieldErrors || {};
    }
  }

  function getCookie(name) {
    const match = document.cookie.split(';').map((c) => c.trim()).find((c) => c.startsWith(name + '='));
    return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
  }

  async function csrfToken() {
    let token = getCookie('csrftoken');
    if (!token) {
      await fetch('/api/csrf/', { credentials: 'same-origin' });
      token = getCookie('csrftoken');
    }
    return token;
  }

  function humanField(name) {
    const text = name.replace(/_/g, ' ');
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function fieldErrorsFrom(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)) return {};
    const errors = {};
    for (const [field, value] of Object.entries(data)) {
      if (field === 'detail' || field === 'non_field_errors') continue;
      errors[field] = [].concat(value).map(String);
    }
    return errors;
  }

  function messageFrom(status, data, text) {
    if (data && typeof data === 'object') {
      if (typeof data.detail === 'string') return data.detail;
      if (Array.isArray(data)) return data.join(' ');
      if (Array.isArray(data.non_field_errors)) return data.non_field_errors.join(' ');
      const parts = Object.entries(fieldErrorsFrom(data)).map(([f, msgs]) => `${humanField(f)}: ${msgs.join(' ')}`);
      if (parts.length) return parts.join(' ');
    }
    if (status === 403 && text && /CSRF/i.test(text)) {
      return 'Your security token has expired. Reload the page and try again.';
    }
    const defaults = {
      400: 'Please check what you entered and try again.',
      401: 'Please sign in to continue.',
      403: 'You do not have permission to do that.',
      404: 'That item could not be found.',
      413: 'The upload is too large.',
    };
    if (defaults[status]) return defaults[status];
    if (status >= 500) return 'The server had a problem. Please try again in a moment.';
    return `The request failed (HTTP ${status}).`;
  }

  function isSignedOut(status, data) {
    return status === 401 || (status === 403 && data && data.detail === SIGNED_OUT_DETAIL);
  }

  async function api(path, options = {}) {
    const { body, headers = {}, redirectOnSignOut = true, signal } = options;
    const method = (options.method || 'GET').toUpperCase();
    const init = { method, credentials: 'same-origin', headers: { Accept: 'application/json', ...headers }, signal };

    if (body instanceof FormData) {
      init.body = body; // the browser sets the multipart boundary itself
    } else if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers['Content-Type'] = 'application/json';
    }
    if (!SAFE_METHODS.has(method)) {
      init.headers['X-CSRFToken'] = await csrfToken();
    }

    let response;
    try {
      response = await fetch(path, init);
    } catch (networkError) {
      if (networkError.name === 'AbortError') throw networkError; // cancelled on purpose (e.g. leaving the page)
      throw new ApiError('Could not reach the server. Check your connection and try again.', 0, null);
    }

    const isJson = (response.headers.get('Content-Type') || '').includes('application/json');
    let data = null;
    let text = '';
    if (response.status !== 204) {
      if (isJson) data = await response.json().catch(() => null);
      else text = await response.text().catch(() => '');
    }

    if (response.ok) return isJson ? data : text;

    if (redirectOnSignOut && isSignedOut(response.status, data)) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login/?next=${next}`);
    }
    throw new ApiError(messageFrom(response.status, data, text), response.status, data, fieldErrorsFrom(data));
  }

  /* ---------- Small UI helpers ---------- */

  function showAlert(target, message, kind = 'danger') {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    el.className = `alert alert-${kind}`;
    el.setAttribute('role', kind === 'danger' ? 'alert' : 'status');
    el.textContent = message;
    el.hidden = false;
  }

  function clearAlert(target) {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) return;
    el.hidden = true;
    el.textContent = '';
  }

  function setBusy(button, busy, busyLabel) {
    if (!button) return;
    if (busy) {
      button.dataset.label = button.textContent;
      button.textContent = busyLabel || 'Working…';
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    } else {
      button.textContent = button.dataset.label || button.textContent;
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  /* Marks inputs named like the API fields as invalid and fills their .invalid-feedback. */
  function showFieldErrors(form, fieldErrors) {
    clearFieldErrors(form);
    let first = null;
    for (const [name, messages] of Object.entries(fieldErrors || {})) {
      const input = form.elements.namedItem(name);
      if (!input || !input.classList) continue;
      input.classList.add('is-invalid');
      input.setAttribute('aria-invalid', 'true');
      const feedback = form.querySelector(`[data-error-for="${name}"]`);
      if (feedback) feedback.textContent = messages.join(' ');
      first = first || input;
    }
    if (first) first.focus();
  }

  function clearFieldErrors(form) {
    form.querySelectorAll('.is-invalid').forEach((el) => {
      el.classList.remove('is-invalid');
      el.removeAttribute('aria-invalid');
    });
    form.querySelectorAll('[data-error-for]').forEach((el) => { el.textContent = ''; });
  }

  /* ---------- Sign out (button in the header) ---------- */
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action="sign-out"]');
    if (!button) return;
    event.preventDefault();
    setBusy(button, true, 'Signing out…');
    try {
      await api('/api/logout/', { method: 'POST', redirectOnSignOut: false });
      window.location.assign('/login/');
    } catch (error) {
      setBusy(button, false);
      showAlert('#page-alert', `Could not sign out: ${error.message}`);
    }
  });

  window.api = api;
  window.App = { api, ApiError, showAlert, clearAlert, setBusy, showFieldErrors, clearFieldErrors };
})();
