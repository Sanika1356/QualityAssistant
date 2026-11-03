(function () {
  'use strict';
  const { api, showAlert, clearAlert, setBusy, showFieldErrors, clearFieldErrors } = window.App;

  const form = document.getElementById('signup-form');
  const alertBox = document.getElementById('signup-alert');
  const button = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert(alertBox);
    clearFieldErrors(form);

    const username = form.username.value.trim();
    const password = form.password.value;
    const missing = {};
    if (!username) missing.username = ['Enter a username.'];
    if (!password) missing.password = ['Enter a password.'];
    if (password && form.password2.value !== password) missing.password2 = ['The two passwords do not match.'];
    if (Object.keys(missing).length) {
      showFieldErrors(form, missing);
      return;
    }

    setBusy(button, true, 'Creating account…');
    try {
      const created = await api('/api/signup/', { method: 'POST', body: { username, password }, redirectOnSignOut: false });
      const params = new URLSearchParams({ role: 'engineer', username: created.username, created: '1' });
      window.location.assign(`/login/?${params}`);
    } catch (error) {
      setBusy(button, false);
      if (Object.keys(error.fieldErrors).length) showFieldErrors(form, error.fieldErrors);
      else showAlert(alertBox, error.message);
    }
  });
})();
