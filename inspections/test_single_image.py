"""POST /api/inspections/: one image, validated then predicted in the request (Person 2's flow)."""
import io
from pathlib import Path
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth.models import Group, User
from PIL import Image
from rest_framework.test import APIClient

from inspections.model.inference import predict
from inspections.models import Inspection, Review

from .tests import SAMPLE_A, SAMPLE_B, VALIDATION_FILES, BatchTestBase, upload

URL = '/api/inspections/'


def media_files():
    folder = Path(settings.MEDIA_ROOT) / 'inspections'
    return sorted(folder.iterdir()) if folder.exists() else []


class SingleImageTestBase(BatchTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user('admin1')
        cls.admin.groups.add(Group.objects.create(name='Administrator'))

    def post_one(self, file=None, user=None, product='P-PLATE01', **extra):
        self.client.force_authenticate(user or self.engineer)
        data = {}
        if product is not None:
            data['product'] = product
        if file is not None:
            data['file'] = file
        data.update(extra)
        return self.client.post(URL, data, format='multipart')

    def assert_nothing_stored(self, before_files):
        self.assertEqual(Inspection.objects.count(), 0)
        self.assertEqual(media_files(), before_files)


class SingleImageSuccessTests(SingleImageTestBase):
    def test_valid_png_and_jpeg_saved_with_right_fields(self):
        for source in (SAMPLE_A, SAMPLE_B):
            with self.subTest(source.name):
                with mock.patch('inspections.views.process_inspection.delay') as delay:
                    response = self.post_one(upload(source))
                delay.assert_not_called()  # runs in the request, not through Celery
                self.assertEqual(response.status_code, 201, response.content)
                body = response.json()
                expected = predict(source)

                self.assertEqual(body['status'], 'completed')
                self.assertEqual(body['failure_reason'], '')
                self.assertEqual(body['predicted_class'], expected['predicted_class'])
                self.assertAlmostEqual(body['confidence'], expected['confidence'])
                self.assertAlmostEqual(body['defect_probability'], expected['defect_probability'])
                self.assertEqual(body['model_version'], 'BIT-PLATE-CV-1.0')
                self.assertEqual(body['submitted_by'], self.engineer.username)
                self.assertEqual(body['product'], 'P-PLATE01')
                self.assertEqual(body['original_filename'], source.name)
                self.assertIsNone(body['batch'])
                self.assertTrue(body['created_at'])
                self.assertEqual(body['review_status'], 'pending')
                self.assertEqual(body['image_url'], f'http://testserver/api/inspections/{body["id"]}/image/')

                item = Inspection.objects.get(pk=body['id'])
                self.assertTrue(Path(item.image.path).exists())
                self.assertEqual(Path(item.image.path).read_bytes(), source.read_bytes())
                # Stored under a random name, not the uploaded one.
                self.assertNotIn(source.stem, item.image.name)

                image = self.client.get(f'/api/inspections/{body["id"]}/image/')
                self.assertEqual(image.status_code, 200)
                self.assertEqual(b''.join(image.streaming_content), source.read_bytes())

    def test_renamed_file_gets_same_prediction(self):
        expected = predict(SAMPLE_A)
        for name in ('normal_plate.jpg', 'Defective.png', 'x.bin', 'no_extension'):
            with self.subTest(name):
                body = self.post_one(upload(SAMPLE_A, name)).json()
                self.assertEqual(body['original_filename'], name)
                self.assertEqual(body['predicted_class'], expected['predicted_class'])
                self.assertAlmostEqual(body['defect_probability'], expected['defect_probability'])

    def test_survives_fresh_read_and_appears_in_history(self):
        item_id = self.post_one(upload(SAMPLE_B)).json()['id']

        item = Inspection.objects.get(pk=item_id)
        self.assertEqual(item.status, 'completed')
        self.assertEqual(item.submitted_by, self.engineer)
        self.assertEqual(item.product, self.product)
        self.assertIsNone(item.batch)
        self.assertIsNotNone(item.predicted_class)

        self.client.force_authenticate(self.engineer)
        history = self.client.get(URL).json()
        self.assertEqual([i['id'] for i in history], [item_id])
        detail = self.client.get(f'{URL}{item_id}/').json()
        self.assertEqual(detail['predicted_class'], item.predicted_class)

    def test_other_engineer_gets_404(self):
        item_id = self.post_one(upload(SAMPLE_A)).json()['id']
        self.client.force_authenticate(self.engineer2)
        self.assertEqual(self.client.get(f'{URL}{item_id}/').status_code, 404)
        self.assertEqual(self.client.get(f'{URL}{item_id}/image/').status_code, 404)
        self.assertEqual(self.client.get(URL).json(), [])

    def test_supervisor_can_review_it(self):
        body = self.post_one(upload(SAMPLE_A)).json()
        corrected = 'Normal' if body['predicted_class'] == 'Defective' else 'Defective'
        self.client.force_authenticate(self.supervisor)
        response = self.client.post(
            f'{URL}{body["id"]}/review/', {'reviewed_class': corrected, 'comment': 'checked'}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['review_status'], 'corrected')
        # The model's original output is kept.
        self.assertEqual(Inspection.objects.get(pk=body['id']).predicted_class, body['predicted_class'])
        self.assertTrue(Review.objects.filter(inspection_id=body['id']).exists())

    def test_get_history_still_works_for_supervisor(self):
        self.post_one(upload(SAMPLE_A))
        self.client.force_authenticate(self.supervisor)
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)


class SingleImageRejectionTests(SingleImageTestBase):
    def assert_rejected(self, response, before, text=None):
        self.assertEqual(response.status_code, 400, response.content)
        detail = response.json()['detail']
        self.assertTrue(detail)
        if text:
            self.assertIn(text, detail)
        self.assert_nothing_stored(before)

    def test_validation_files_return_400_and_store_nothing(self):
        before = media_files()
        with mock.patch('inspections.tasks.predict') as model:
            for path in VALIDATION_FILES:
                with self.subTest(path.name):
                    self.assert_rejected(self.post_one(upload(path)), before)
        model.assert_not_called()

    def test_validation_reasons_are_readable(self):
        reasons = {p.name: self.post_one(upload(p)).json()['detail'] for p in VALIDATION_FILES}
        self.assertEqual(reasons['corrupt_image.png'], 'File is not a readable JPEG or PNG image.')
        self.assertEqual(reasons['not_an_image.jpg'], 'File is not a readable JPEG or PNG image.')
        self.assertIn('32x32', reasons['too_small.png'])

    def test_half_cut_jpeg_returns_400(self):
        before = media_files()
        data = SAMPLE_B.read_bytes()
        cut = upload(SAMPLE_B, 'half.jpg')
        cut.file = io.BytesIO(data[: len(data) // 2])
        cut.size = len(data) // 2
        with mock.patch('inspections.tasks.predict') as model:
            self.assert_rejected(self.post_one(cut), before)
        model.assert_not_called()

    def test_over_5_mib_returns_400(self):
        # Real, decodable PNG of random pixels, so only the size is wrong.
        pixels = np.random.default_rng(1).integers(0, 256, (1450, 1450, 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(pixels, 'RGB').save(buf, 'PNG', compress_level=0)
        self.assertGreater(len(buf.getvalue()), 5 * 1024 * 1024)
        big = upload(SAMPLE_A, 'big.png')
        big.file, big.size = io.BytesIO(buf.getvalue()), len(buf.getvalue())
        before = media_files()
        with mock.patch('inspections.tasks.predict') as model:
            self.assert_rejected(self.post_one(big), before, '5 MiB')
        model.assert_not_called()

    def test_missing_file(self):
        before = media_files()
        self.assert_rejected(self.post_one(None), before, '"file"')

    def test_two_files_rejected(self):
        before = media_files()
        self.assert_rejected(self.post_one([upload(SAMPLE_A), upload(SAMPLE_B)]), before, 'exactly one')

    def test_files_field_from_batch_is_not_accepted(self):
        before = media_files()
        self.assert_rejected(self.post_one(None, files=[upload(SAMPLE_A)]), before, '"file"')

    def test_unknown_product(self):
        before = media_files()
        self.assert_rejected(self.post_one(upload(SAMPLE_A), product='NOPE'), before, 'Unknown product "NOPE"')

    def test_missing_product(self):
        before = media_files()
        self.assert_rejected(self.post_one(upload(SAMPLE_A), product=None), before, 'Choose a product')


class SingleImagePermissionTests(SingleImageTestBase):
    def test_non_engineers_get_403(self):
        for user in (self.supervisor, self.admin, self.no_role):
            with self.subTest(user.username):
                response = self.post_one(upload(SAMPLE_A), user=user)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['detail'], 'Only Engineers can submit inspections.')
        self.assert_nothing_stored([])

    def test_logged_out_refused(self):
        response = APIClient().post(URL, {'product': 'P-PLATE01', 'file': upload(SAMPLE_A)}, format='multipart')
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Inspection.objects.count(), 0)

    def test_session_post_needs_csrf_token(self):
        self.engineer.set_password('pw-for-test-1')
        self.engineer.save()
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username=self.engineer.username, password='pw-for-test-1'))
        data = {'product': 'P-PLATE01', 'file': upload(SAMPLE_A)}
        self.assertEqual(client.post(URL, data, format='multipart').status_code, 403)
        token = client.get('/api/csrf/').cookies['csrftoken'].value
        data = {'product': 'P-PLATE01', 'file': upload(SAMPLE_A)}
        response = client.post(URL, data, format='multipart', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)


class SingleImageModelErrorTests(SingleImageTestBase):
    def test_model_error_saves_failed_with_no_prediction(self):
        with mock.patch('inspections.tasks.predict', side_effect=RuntimeError(r'boom at C:\secret\path')), \
                self.assertLogs('inspections.tasks', level='ERROR'):
            response = self.post_one(upload(SAMPLE_A))
        self.assertEqual(response.status_code, 500)
        detail = response.json()['detail']
        self.assertIn('Model could not process this image (RuntimeError)', detail)
        self.assertNotIn('secret', detail)
        self.assertNotIn('\\', detail)

        item = Inspection.objects.get()
        self.assertEqual(item.status, 'failed')
        self.assertEqual(item.failure_reason, 'Model could not process this image (RuntimeError).')
        self.assertIsNone(item.predicted_class)
        self.assertIsNone(item.confidence)
        self.assertIsNone(item.defect_probability)
        self.assertEqual(item.model_version, '')
        self.assertIn(str(item.pk), detail)
