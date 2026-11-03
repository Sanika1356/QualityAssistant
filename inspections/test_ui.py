"""Metrics report + API, and safety checks on the final screens."""
import io
import json
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

ROLES = ('Administrator', 'Engineer', 'Supervisor')


class MetricsCommandTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def run_command(self):
        out = self.tmp / 'report.txt'
        call_command('evaluate_samples', output=str(out), stdout=io.StringIO())
        return out, json.loads(out.with_suffix('.json').read_text(encoding='utf-8'))

    def test_json_written_next_to_text_report(self):
        out, data = self.run_command()
        self.assertTrue(out.exists())
        self.assertTrue(out.with_suffix('.json').exists())
        self.assertEqual(data['command'], 'python manage.py evaluate_samples')
        self.assertEqual(data['model_version'], 'BIT-PLATE-CV-1.0')
        self.assertEqual(data['decision_threshold'], 0.5)
        self.assertEqual(data['images_found'], 60)
        self.assertIn('synthetic', data['limitation'])

    def test_json_numbers_are_consistent(self):
        _, data = self.run_command()
        m = data['confusion_matrix']
        self.assertEqual((m['rows'], m['columns'], m['order']), ('actual', 'predicted', ['Normal', 'Defective']))
        [[tn, fp], [fn, tp]] = m['values']
        self.assertEqual((tn, fp, fn, tp), (data['tn'], data['fp'], data['fn'], data['tp']))
        self.assertEqual(tn + fp + fn + tp, data['sample_count'])
        self.assertEqual(data['sample_count'] + len(data['failures']), data['images_found'])
        self.assertAlmostEqual(data['defect_recall'], tp / (tp + fn))

    def test_json_matches_text_report(self):
        out, data = self.run_command()
        text = out.read_text(encoding='utf-8')
        for key in ('tp', 'fn', 'fp', 'tn'):
            found = re.search(rf'^{key.upper()} \(.*?\)\s+= (\d+)$', text, re.M)
            self.assertEqual(int(found.group(1)), data[key], key)

    def test_committed_report_files_agree(self):
        """The metrics_report.json shipped in the repo came from the same run as metrics_report.txt."""
        base = Path(settings.BASE_DIR)
        data = json.loads((base / 'metrics_report.json').read_text(encoding='utf-8'))
        text = (base / 'metrics_report.txt').read_text(encoding='utf-8')
        for key in ('tp', 'fn', 'fp', 'tn'):
            found = re.search(rf'^{key.upper()} \(.*?\)\s+= (\d+)$', text, re.M)
            self.assertEqual(int(found.group(1)), data[key], key)


class MetricsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in ROLES:
            user = User.objects.create_user(role.lower())
            user.groups.add(Group.objects.create(name=role))
            cls.users[role] = user
        cls.no_role = User.objects.create_user('plain')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.report = self.tmp / 'metrics_report.json'
        self.data = {'tp': 3, 'fn': 1, 'fp': 0, 'tn': 4, 'sample_count': 8, 'command': 'python manage.py evaluate_samples'}
        self.report.write_text(json.dumps(self.data), encoding='utf-8')
        self.client = APIClient()

    def get(self, user):
        self.client.force_authenticate(user)
        with override_settings(METRICS_REPORT_JSON=self.report):
            return self.client.get('/api/metrics/')

    def test_each_role_gets_the_saved_report(self):
        for role, user in self.users.items():
            with self.subTest(role):
                response = self.get(user)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), self.data)

    def test_no_role_and_anonymous_refused(self):
        self.assertEqual(self.get(self.no_role).status_code, 403)
        self.assertIn(self.get(None).status_code, (401, 403))

    def test_missing_report_says_which_command_to_run(self):
        self.report.unlink()
        response = self.get(self.users['Supervisor'])
        self.assertEqual(response.status_code, 404)
        self.assertIn('python manage.py evaluate_samples', response.json()['detail'])

    def test_unreadable_report(self):
        self.report.write_text('{not json', encoding='utf-8')
        response = self.get(self.users['Supervisor'])
        self.assertEqual(response.status_code, 500)
        self.assertIn('evaluate_samples', response.json()['detail'])

    def test_read_only(self):
        self.client.force_authenticate(self.users['Administrator'])
        with override_settings(METRICS_REPORT_JSON=self.report):
            self.assertEqual(self.client.post('/api/metrics/', {}).status_code, 405)


class ScreenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in ROLES:
            user = User.objects.create_user(f'{role.lower()}-ui')
            user.groups.add(Group.objects.create(name=role))
            cls.users[role] = user

    def test_pages_load_shared_scripts(self):
        pages = {'Administrator': '/admin-panel/', 'Engineer': '/engineer/', 'Supervisor': '/supervisor/'}
        for role, page in pages.items():
            with self.subTest(role):
                self.client.force_login(self.users[role])
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'js/api.js')
                self.assertContains(response, 'js/ui.js')

    def test_admin_page_shows_metrics_panel(self):
        self.client.force_login(self.users['Administrator'])
        response = self.client.get('/admin-panel/')
        self.assertContains(response, 'data-metrics-panel')
        self.assertContains(response, 'js/metrics.js')

    def test_new_static_files_are_found(self):
        for path in ('js/ui.js', 'js/metrics.js', 'js/screens/engineer.js', 'js/screens/supervisor.js'):
            with self.subTest(path):
                self.assertIsNotNone(finders.find(path))

    def test_scripts_never_inject_html(self):
        unsafe = re.compile(r'\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write\(|eval\(')
        scripts = [p for p in (Path(settings.BASE_DIR) / 'static' / 'js').rglob('*.js')]
        self.assertGreaterEqual(len(scripts), 7)
        for path in scripts:
            with self.subTest(path.name):
                self.assertIsNone(unsafe.search(path.read_text(encoding='utf-8')))

    def test_no_hard_coded_metric_values_in_screens(self):
        # The metrics panel must be filled from the API; the template and script carry no counts.
        template = (Path(settings.BASE_DIR) / 'templates' / 'partials' / 'metrics_panel.html').read_text(encoding='utf-8')
        script = (Path(settings.BASE_DIR) / 'static' / 'js' / 'metrics.js').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'\b(30|60)\b', template))
        self.assertIsNone(re.search(r'\b(30|60)\b', script))
        self.assertIn("api('/api/metrics/')", script)
