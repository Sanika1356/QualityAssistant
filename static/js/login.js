(function () {
  'use strict';
  const { api, showAlert, clearAlert, setBusy } = window.App;

  const form = document.getElementById('login-form');
  const alertBox = document.getElementById('login-alert');
  const button = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearAlert(alertBox);

    const username = form.username.value.trim();
    const password = form.password.value;
    if (!username || !password) {
      showAlert(alertBox, 'Enter your username and password.');
      (username ? form.password : form.username).focus();
      return;
    }

    setBusy(button, true, 'Signing in…');
    try {
      const next = new URLSearchParams(window.location.search).get('next') || '';
      // The role is only a label; the server checks it against the account's real group.
      const role = form.dataset.role || '';
      const result = await api('/api/login/', {
        method: 'POST',
        body: { username, password, next, role },
        redirectOnSignOut: false,
      });
      window.location.assign(result.redirect);
    } catch (error) {
      setBusy(button, false);
      showAlert(alertBox, error.message);
      form.password.value = '';
      form.password.focus();
    }
  });
})();
