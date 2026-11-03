"""Self sign-up (always Engineer) and the role label on the sign-in page."""
from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Inspection, Product, Review

STRONG = 'plate-check-2026!'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class SignupTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.groups = {n: Group.objects.create(name=n) for n in ('Administrator', 'Engineer', 'Supervisor')}
        cls.engineer = User.objects.create_user('eng-existing', password=STRONG)
        cls.engineer.groups.add(cls.groups['Engineer'])
        cls.supervisor = User.objects.create_user('sup-existing', password=STRONG)
        cls.supervisor.groups.add(cls.groups['Supervisor'])

    def csrf_client(self):
        client = APIClient(enforce_csrf_checks=True)
        token = client.get('/api/csrf/').cookies['csrftoken'].value
        return client, token

    def signup(self, data):
        client, token = self.csrf_client()
        return client.post('/api/signup/', data, format='json', HTTP_X_CSRFTOKEN=token)

    def login(self, username, password=STRONG, role=None):
        client, token = self.csrf_client()
        body = {'username': username, 'password': password}
        if role is not None:
            body['role'] = role
        response = client.post('/api/login/', body, format='json', HTTP_X_CSRFTOKEN=token)
        return client, response


class SignupApiTests(SignupTestBase):
    def test_creates_engineer_only(self):
        response = self.signup({'username': 'newbie', 'password': STRONG})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {'username': 'newbie', 'role': 'Engineer'})
        user = User.objects.get(username='newbie')
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Engineer'])
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(STRONG))

    def test_ignores_role_and_admin_rights(self):
        response = self.signup({
            'username': 'sneaky', 'password': STRONG, 'role': 'Administrator', 'group': 'Supervisor',
            'groups': ['Administrator', 'Supervisor'], 'is_staff': True, 'is_superuser': True,
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['role'], 'Engineer')
        user = User.objects.get(username='sneaky')
        self.assertEqual(list(user.groups.values_list('name', flat=True)), ['Engineer'])
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_refuses_duplicate_any_case(self):
        for name in ('eng-existing', 'ENG-Existing'):
            with self.subTest(name):
                response = self.signup({'username': name, 'password': STRONG})
                self.assertEqual(response.status_code, 400)
                self.assertIn('already exists', response.json()['username'][0])
        self.assertEqual(User.objects.filter(username__iexact='eng-existing').count(), 1)

    def test_refuses_weak_passwords(self):
        for weak in ('short1', '12345678901', 'password', 'weakuser1'):
            with self.subTest(weak):
                response = self.signup({'username': 'weakuser1', 'password': weak})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json()['password'])
        self.assertFalse(User.objects.filter(username='weakuser1').exists())

    def test_refuses_missing_and_invalid_username(self):
        self.assertEqual(self.signup({'username': '', 'password': STRONG}).status_code, 400)
        response = self.signup({'username': 'bad name!', 'password': STRONG})
        self.assertEqual(response.status_code, 400)
        self.assertIn('username', response.json())

    def test_csrf_enforced(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post('/api/signup/', {'username': 'nocsrf', 'password': STRONG}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='nocsrf').exists())

    def test_signup_does_not_sign_in(self):
        client, token = self.csrf_client()
        client.post('/api/signup/', {'username': 'fresh', 'password': STRONG}, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(client.get('/api/me/').status_code, 403)


class NewUserAccessTests(SignupTestBase):
    def test_new_user_is_an_engineer_everywhere(self):
        self.signup({'username': 'newbie2', 'password': STRONG})
        client, response = self.login('newbie2', role='engineer')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['role'], 'Engineer')
        self.assertEqual(client.get('/engineer/').status_code, 200)
        self.assertEqual(client.get('/supervisor/').status_code, 403)
        self.assertEqual(client.get('/admin-panel/').status_code, 403)

        product = Product.objects.create(product_id='T-1', name='Test')
        item = Inspection.objects.create(
            product=product, original_filename='a.png', status='completed', predicted_class='Normal',
            confidence=0.9, defect_probability=0.1, model_version='v', submitted_by=self.engineer,
        )
        token = client.cookies['csrftoken'].value
        response = client.post(f'/api/inspections/{item.pk}/review/', {'reviewed_class': 'Defective'},
                               format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Review.objects.exists())


class RoleLabelTests(SignupTestBase):
    def test_wrong_role_refused_and_signed_out(self):
        client, response = self.login('eng-existing', role='administrator')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], "This account isn't an Administrator account. Use the correct sign-in.")
        self.assertEqual(client.get('/api/me/').status_code, 403)
        self.assertEqual(client.get('/engineer/').status_code, 302)

        _, response = self.login('eng-existing', role='supervisor')
        self.assertEqual(response.json()['detail'], "This account isn't a Supervisor account. Use the correct sign-in.")

    def test_wrong_role_signs_out_an_existing_session(self):
        client, response = self.login('eng-existing', role='engineer')
        self.assertEqual(client.get('/api/me/').status_code, 200)
        token = client.cookies['csrftoken'].value
        response = client.post('/api/login/', {'username': 'eng-existing', 'password': STRONG, 'role': 'supervisor'},
                               format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get('/api/me/').status_code, 403)

    def test_correct_role_signs_in(self):
        for user, role, page in (('eng-existing', 'engineer', '/engineer/'), ('sup-existing', 'Supervisor', '/supervisor/')):
            with self.subTest(role):
                client, response = self.login(user, role=role)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['redirect'], page)

    def test_unknown_or_missing_role_is_ignored(self):
        for role in (None, '', 'superadmin', '<script>', 'Administrator ; drop'):
            with self.subTest(role=role):
                _, response = self.login('eng-existing', role=role)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['role'], 'Engineer')

    def test_wrong_password_with_role_still_401(self):
        _, response = self.login('eng-existing', password='nope', role='engineer')
        self.assertEqual(response.status_code, 401)


class PublicPageTests(SignupTestBase):
    def test_login_page_heading_follows_role(self):
        for key, heading in (('engineer', 'Engineer sign in'), ('administrator', 'Administrator sign in'),
                             ('supervisor', 'Supervisor sign in')):
            with self.subTest(key):
                response = self.client.get(f'/login/?role={key}')
                self.assertContains(response, heading)
        self.assertContains(self.client.get('/login/'), '>Sign in</h1>')
        response = self.client.get('/login/?role=<script>alert(1)</script>')
        self.assertContains(response, '>Sign in</h1>')
        self.assertNotContains(response, '<script>alert(1)')

    def test_signup_link_only_for_engineer_and_plain(self):
        for url in ('/login/', '/login/?role=engineer'):
            with self.subTest(url):
                self.assertContains(self.client.get(url), 'Create an account')
        for url in ('/login/?role=administrator', '/login/?role=supervisor'):
            with self.subTest(url):
                response = self.client.get(url)
                self.assertNotContains(response, 'Create an account')
                self.assertContains(response, 'Accounts for this role are created by an administrator.')

    def test_created_message_and_username_prefill_never_password(self):
        response = self.client.get('/login/?role=engineer&username=newbie&created=1')
        self.assertContains(response, 'Account created. Sign in with your new password.')
        self.assertContains(response, 'value="newbie"')
        self.assertNotContains(response, 'type="password" value')
        response = self.client.get('/login/?username="><script>x</script>')
        self.assertNotContains(response, '<script>x</script>')

    def test_signup_page(self):
        response = self.client.get('/signup/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="signup-form"')
        self.assertContains(response, 'id="password2"')
        self.assertIn('csrftoken', response.cookies)
        self.client.force_login(self.engineer)
        self.assertRedirects(self.client.get('/signup/'), '/engineer/', fetch_redirect_response=False)
