from django.contrib.auth.models import Group, User
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Inspection, Product, Review

PASSWORD = 'correct-horse-42'
PAGES = {'Administrator': '/admin-panel/', 'Engineer': '/engineer/', 'Supervisor': '/supervisor/'}


# A fast hasher keeps these login tests quick; it does not change what is tested.
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AuthTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.groups = {name: Group.objects.create(name=name) for name in PAGES}
        cls.users = {}
        for role in PAGES:
            user = User.objects.create_user(f'{role.lower()}1', password=PASSWORD)
            user.groups.add(cls.groups[role])
            cls.users[role] = user
        cls.no_role = User.objects.create_user('norole', password=PASSWORD)
        cls.two_roles = User.objects.create_user('tworoles', password=PASSWORD)
        cls.two_roles.groups.add(cls.groups['Engineer'], cls.groups['Supervisor'])

    def csrf_client(self):
        """A client that enforces CSRF like a browser, holding a valid CSRF cookie."""
        client = APIClient(enforce_csrf_checks=True)
        response = client.get('/api/csrf/')
        self.assertEqual(response.status_code, 200)
        return client, response.cookies['csrftoken'].value

    def login(self, username, password=PASSWORD, **extra):
        client, token = self.csrf_client()
        response = client.post(
            '/api/login/', {'username': username, 'password': password, **extra},
            format='json', HTTP_X_CSRFTOKEN=token,
        )
        return client, response


class LoginApiTests(AuthTestBase):
    def test_login_success_returns_username_and_role(self):
        for role, page in PAGES.items():
            with self.subTest(role):
                user = self.users[role]
                client, response = self.login(user.username)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'username': user.username, 'role': role, 'redirect': page})
                me = client.get('/api/me/')
                self.assertEqual(me.json(), {'username': user.username, 'role': role})

    def test_wrong_password_is_401_with_message(self):
        client, response = self.login('engineer1', password='wrong')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Incorrect username or password.')
        self.assertEqual(client.get('/api/me/').status_code, 403)

    def test_unknown_user_gets_same_message(self):
        _, response = self.login('nobody-here')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Incorrect username or password.')

    def test_missing_fields_rejected(self):
        _, response = self.login('', password='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('username and password', response.json()['detail'])

    def test_user_without_role_refused(self):
        client, response = self.login('norole')
        self.assertEqual(response.status_code, 403)
        self.assertIn('no role', response.json()['detail'])
        self.assertEqual(client.get('/api/me/').status_code, 403)

    def test_user_with_two_roles_refused(self):
        client, response = self.login('tworoles')
        self.assertEqual(response.status_code, 403)
        self.assertIn('more than one role', response.json()['detail'])
        self.assertEqual(client.get('/api/me/').status_code, 403)

    def test_inactive_user_refused(self):
        user = self.users['Engineer']
        user.is_active = False
        user.save()
        _, response = self.login(user.username)
        self.assertEqual(response.status_code, 401)

    def test_safe_next_is_followed_and_unsafe_next_ignored(self):
        _, response = self.login('engineer1', next='/engineer/?tab=history')
        self.assertEqual(response.json()['redirect'], '/engineer/?tab=history')
        _, response = self.login('engineer1', next='https://evil.example/steal')
        self.assertEqual(response.json()['redirect'], '/engineer/')

    def test_logout(self):
        client, _ = self.login('engineer1')
        self.assertEqual(client.get('/api/me/').status_code, 200)
        token = client.cookies['csrftoken'].value
        response = client.post('/api/logout/', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get('/api/me/').status_code, 403)
        self.assertEqual(client.get('/engineer/').status_code, 302)

    def test_me_when_logged_out(self):
        response = APIClient().get('/api/me/')
        self.assertEqual(response.status_code, 403)

    def test_me_refuses_user_whose_role_was_removed(self):
        client, _ = self.login('engineer1')
        self.users['Engineer'].groups.clear()
        response = client.get('/api/me/')
        self.assertEqual(response.status_code, 403)
        self.assertIn('no role', response.json()['detail'])


class CsrfTests(AuthTestBase):
    def test_login_without_csrf_token_is_refused(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.post('/api/login/', {'username': 'engineer1', 'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(client.get('/api/me/').status_code, 403)

    def test_login_with_wrong_csrf_token_is_refused(self):
        client, _ = self.csrf_client()
        response = client.post(
            '/api/login/', {'username': 'engineer1', 'password': PASSWORD},
            format='json', HTTP_X_CSRFTOKEN='x' * 32,
        )
        self.assertEqual(response.status_code, 403)

    def test_login_with_csrf_token_succeeds(self):
        _, response = self.login('engineer1')
        self.assertEqual(response.status_code, 200)

    def test_logout_needs_csrf_token(self):
        client, _ = self.login('engineer1')
        self.assertEqual(client.post('/api/logout/').status_code, 403)
        self.assertEqual(client.get('/api/me/').status_code, 200)

    def test_csrf_endpoint_sets_cookie(self):
        response = APIClient().get('/api/csrf/')
        self.assertIn('csrftoken', response.cookies)

    def test_login_page_sets_csrf_cookie(self):
        response = self.client.get('/login/')
        self.assertIn('csrftoken', response.cookies)


class PageAccessTests(AuthTestBase):
    def test_each_role_reaches_its_own_page(self):
        templates = {
            'Administrator': 'pages/admin_panel.html',
            'Engineer': 'screens/engineer_screen.html',
            'Supervisor': 'screens/supervisor_screen.html',
        }
        for role, page in PAGES.items():
            with self.subTest(role):
                self.client.force_login(self.users[role])
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'base.html')
                self.assertTemplateUsed(response, templates[role])
                self.assertContains(response, self.users[role].username)
                self.assertContains(response, 'data-action="sign-out"')

    def test_other_roles_get_403_page(self):
        for role, user in self.users.items():
            for other_role, page in PAGES.items():
                if other_role == role:
                    continue
                with self.subTest(user=role, page=page):
                    self.client.force_login(user)
                    response = self.client.get(page)
                    self.assertEqual(response.status_code, 403)
                    self.assertTemplateUsed(response, '403.html')
                    self.assertContains(response, f'This page is for {other_role}s', status_code=403)

    def test_no_role_and_two_role_users_get_403_on_every_page(self):
        for user in (self.no_role, self.two_roles):
            self.client.force_login(user)
            for page in PAGES.values():
                with self.subTest(user=user.username, page=page):
                    self.assertEqual(self.client.get(page).status_code, 403)

    def test_logged_out_users_are_redirected_to_login(self):
        for page in PAGES.values():
            with self.subTest(page):
                response = self.client.get(page)
                self.assertRedirects(response, f'/login/?next={page}', fetch_redirect_response=False)

    def test_root_redirects(self):
        self.assertRedirects(self.client.get('/'), '/login/', fetch_redirect_response=False)
        for role, page in PAGES.items():
            with self.subTest(role):
                self.client.force_login(self.users[role])
                self.assertRedirects(self.client.get('/'), page, fetch_redirect_response=False)

    def test_login_page(self):
        response = self.client.get('/login/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/login.html')
        self.assertContains(response, 'id="login-form"')
        self.client.force_login(self.users['Supervisor'])
        self.assertRedirects(self.client.get('/login/'), '/supervisor/', fetch_redirect_response=False)

    def test_header_links_match_role(self):
        self.client.force_login(self.users['Engineer'])
        response = self.client.get('/engineer/')
        self.assertContains(response, 'href="/engineer/"')
        self.assertNotContains(response, 'href="/admin-panel/"')
        self.assertNotContains(response, 'href="/supervisor/"')

    def test_django_admin_is_separate(self):
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/login/', response['Location'])

    def test_static_files_are_found(self):
        for path in ('css/app.css', 'js/api.js', 'js/login.js', 'js/admin_panel.js',
                     'vendor/bootstrap-5.3.3/css/bootstrap.min.css',
                     'vendor/bootstrap-5.3.3/js/bootstrap.bundle.min.js'):
            with self.subTest(path):
                self.assertIsNotNone(finders.find(path))

    def test_placeholders_name_the_teammate(self):
        for role in ('Engineer', 'Supervisor'):
            with self.subTest(role):
                self.client.force_login(self.users[role])
                response = self.client.get(PAGES[role])
                self.assertContains(response, 'Placeholder · Person 4')
                self.assertNotContains(response, 'coming soon')


class SessionApiTests(AuthTestBase):
    """Real browser-style sessions (login API + CSRF) against existing APIs."""

    def test_engineer_still_refused_on_review_api(self):
        product = Product.objects.create(product_id='T-1', name='Test plate')
        inspection = Inspection.objects.create(
            product=product, original_filename='a.png', status='completed', predicted_class='Normal',
            confidence=0.9, defect_probability=0.1, model_version='v', submitted_by=self.users['Engineer'],
        )
        client, response = self.login('engineer1')
        self.assertEqual(response.status_code, 200)
        token = client.cookies['csrftoken'].value
        response = client.post(
            f'/api/inspections/{inspection.pk}/review/',
            {'reviewed_class': 'Defective', 'comment': 'should not work'},
            format='json', HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Review.objects.filter(inspection=inspection).exists())

    def test_administrator_adds_product_through_session(self):
        client, _ = self.login('administrator1')
        token = client.cookies['csrftoken'].value
        body = {'product_id': 'P-NEW', 'name': 'New plate', 'description': ''}
        self.assertEqual(client.post('/api/products/', body, format='json').status_code, 403)
        response = client.post('/api/products/', body, format='json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Product.objects.filter(product_id='P-NEW').exists())
        listed = [p['product_id'] for p in client.get('/api/products/').json()]
        self.assertIn('P-NEW', listed)

    def test_engineer_cannot_add_product_through_session(self):
        client, _ = self.login('engineer1')
        token = client.cookies['csrftoken'].value
        response = client.post(
            '/api/products/', {'product_id': 'P-X', 'name': 'X'}, format='json', HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.filter(product_id='P-X').exists())
