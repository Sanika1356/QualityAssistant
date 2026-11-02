import io
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from config.celery import app as celery_app
from inspections.model.inference import predict
from inspections.models import Batch, Inspection, Product
from inspections.tasks import process_inspection
from inspections.validators import validate_image

PACK = Path(settings.BASE_DIR) / 'pack_data'
SAMPLE_A = PACK / 'Samples' / 'images' / 'inspection_001.png'
SAMPLE_B = PACK / 'Samples' / 'images' / 'inspection_002.jpg'
VALIDATION_FILES = sorted((PACK / 'Validation').iterdir())

MEDIA_TMP = tempfile.mkdtemp(prefix='inspections-test-media-')


def upload(path, name=None):
    return SimpleUploadedFile(name or Path(path).name, Path(path).read_bytes())


def png_bytes(width, height, fmt='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', (width, height), 'gray').save(buf, fmt)
    return buf.getvalue()


class EagerCeleryMixin:
    """Run Celery tasks in-process: no Redis and no worker needed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._celery_conf = {
            'task_always_eager': celery_app.conf.task_always_eager,
            'task_eager_propagates': celery_app.conf.task_eager_propagates,
            'broker_url': celery_app.conf.broker_url,
        }
        celery_app.conf.task_always_eager = True
        celery_app.conf.task_eager_propagates = True
        # An unreachable broker proves the tests never talk to Redis.
        celery_app.conf.broker_url = 'memory://'

    @classmethod
    def tearDownClass(cls):
        for key, value in cls._celery_conf.items():
            setattr(celery_app.conf, key, value)
        super().tearDownClass()


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class BatchTestBase(EagerCeleryMixin, TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        call_command('load_products', stdout=io.StringIO())
        cls.product = Product.objects.get(product_id='P-PLATE01')
        engineers = Group.objects.create(name='Engineer')
        supervisors = Group.objects.create(name='Supervisor')
        cls.engineer = User.objects.create_user('eng1')
        cls.engineer.groups.add(engineers)
        cls.engineer2 = User.objects.create_user('eng2')
        cls.engineer2.groups.add(engineers)
        cls.supervisor = User.objects.create_user('sup1')
        cls.supervisor.groups.add(supervisors)
        cls.no_role = User.objects.create_user('plain')

    def setUp(self):
        self.client = APIClient()

    def post_batch(self, files, user=None, product='P-PLATE01'):
        self.client.force_authenticate(user or self.engineer)
        data = {'product': product}
        if files:
            data['files'] = files
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post('/api/batches/', data, format='multipart')


class ValidatorTests(TestCase):
    def test_all_validation_files_fail_with_reason(self):
        self.assertEqual(len(VALIDATION_FILES), 3)
        for path in VALIDATION_FILES:
            with self.subTest(path.name):
                reason = validate_image(path)
                self.assertTrue(reason, f'{path.name} should be rejected')

    def test_all_samples_pass(self):
        for path in sorted((PACK / 'Samples' / 'images').iterdir()):
            with self.subTest(path.name):
                self.assertIsNone(validate_image(path))

    def test_size_boundaries_inclusive(self):
        self.assertIsNone(validate_image(io.BytesIO(png_bytes(64, 64))))
        self.assertIsNone(validate_image(io.BytesIO(png_bytes(4096, 64))))
        self.assertIn('63x64', validate_image(io.BytesIO(png_bytes(63, 64))))
        self.assertIn('64x4097', validate_image(io.BytesIO(png_bytes(64, 4097))))

    def test_content_not_extension(self):
        # A real PNG named .gif passes; GIF content named .png fails.
        self.assertIsNone(validate_image(SimpleUploadedFile('x.gif', SAMPLE_A.read_bytes())))
        gif = SimpleUploadedFile('x.png', png_bytes(100, 100, 'GIF'))
        self.assertIn('GIF', validate_image(gif))

    def test_truncated_image_fails(self):
        data = SAMPLE_A.read_bytes()
        self.assertTrue(validate_image(io.BytesIO(data[: len(data) // 2])))

    def test_over_5_mib_fails(self):
        big = io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\0' * (5 * 1024 * 1024))
        self.assertIn('5 MiB', validate_image(big))


class BatchCountTests(BatchTestBase):
    def assert_nothing_created(self):
        self.assertEqual(Batch.objects.count(), 0)
        self.assertEqual(Inspection.objects.count(), 0)

    def test_zero_files_rejected(self):
        response = self.post_batch([])
        self.assertEqual(response.status_code, 400)
        self.assert_nothing_created()

    def test_eleven_files_rejected(self):
        response = self.post_batch([upload(SAMPLE_A, f'img{i}.png') for i in range(11)])
        self.assertEqual(response.status_code, 400)
        self.assert_nothing_created()

    def test_ten_files_accepted(self):
        response = self.post_batch([upload(SAMPLE_A, f'img{i}.png') for i in range(10)])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Inspection.objects.filter(status='completed').count(), 10)

    def test_unknown_product_rejected(self):
        response = self.post_batch([upload(SAMPLE_A)], product='NOPE')
        self.assertEqual(response.status_code, 400)
        self.assert_nothing_created()


class MixedBatchTests(BatchTestBase):
    def test_mixed_batch(self):
        files = [upload(SAMPLE_A)] + [upload(p) for p in VALIDATION_FILES]
        with mock.patch('inspections.tasks.predict', wraps=predict) as spy:
            response = self.post_batch(files)
        self.assertEqual(response.status_code, 201)

        # The model was called exactly once: only for the valid sample.
        self.assertEqual(spy.call_count, 1)

        items = {i.original_filename: i for i in Inspection.objects.all()}
        self.assertEqual(len(items), 4)

        valid = items[SAMPLE_A.name]
        self.assertEqual(valid.status, 'completed')
        expected = predict(SAMPLE_A)
        self.assertEqual(valid.predicted_class, expected['predicted_class'])
        self.assertAlmostEqual(valid.confidence, expected['confidence'])
        self.assertAlmostEqual(valid.defect_probability, expected['defect_probability'])
        self.assertEqual(valid.model_version, 'BIT-PLATE-CV-1.0')

        for path in VALIDATION_FILES:
            with self.subTest(path.name):
                item = items[path.name]
                self.assertEqual(item.status, 'failed')
                self.assertTrue(item.failure_reason)
                self.assertIsNone(item.predicted_class)
                self.assertIsNone(item.confidence)
                self.assertIsNone(item.defect_probability)
                self.assertEqual(item.model_version, '')
                self.assertFalse(item.image)

    def test_post_response_lists_initial_statuses(self):
        # Without eager execution the response shows what the user sees immediately.
        celery_app.conf.task_always_eager = False
        try:
            with mock.patch('inspections.views.process_inspection.delay') as delay:
                files = [upload(SAMPLE_A), upload(VALIDATION_FILES[0])]
                response = self.post_batch(files)
        finally:
            celery_app.conf.task_always_eager = True
        body = response.json()
        self.assertEqual(response.status_code, 201)
        self.assertEqual([i['status'] for i in body['items']], ['queued', 'failed'])
        self.assertEqual(delay.call_count, 1)

    def test_one_model_error_does_not_stop_others(self):
        def flaky(path):
            if Path(path).read_bytes() == SAMPLE_B.read_bytes():
                raise RuntimeError('boom')
            return predict(path)

        with mock.patch('inspections.tasks.predict', side_effect=flaky), \
                self.assertLogs('inspections.tasks', level='ERROR'):
            self.post_batch([upload(SAMPLE_A), upload(SAMPLE_B), upload(SAMPLE_A, 'again.png')])
        statuses = dict(Inspection.objects.values_list('original_filename', 'status'))
        self.assertEqual(statuses[SAMPLE_B.name], 'failed')
        self.assertEqual(statuses[SAMPLE_A.name], 'completed')
        self.assertEqual(statuses['again.png'], 'completed')
        failed = Inspection.objects.get(original_filename=SAMPLE_B.name)
        self.assertIn('RuntimeError', failed.failure_reason)
        self.assertIsNone(failed.predicted_class)

    def test_broker_down_marks_item_failed(self):
        celery_app.conf.task_always_eager = False
        try:
            with mock.patch(
                'inspections.views.process_inspection.delay', side_effect=ConnectionError('down')
            ), self.assertLogs('inspections.views', level='ERROR'):
                response = self.post_batch([upload(SAMPLE_A)])
        finally:
            celery_app.conf.task_always_eager = True
        self.assertEqual(response.status_code, 201)
        item = Inspection.objects.get()
        self.assertEqual(item.status, 'failed')
        self.assertIn('queue', item.failure_reason)


class RenameTests(BatchTestBase):
    def test_filename_does_not_affect_prediction(self):
        names = ['defective_scratch.png', 'normal_ok.jpg', 'Defective.jpeg', 'x.bin', 'no_extension']
        for source in (SAMPLE_A, SAMPLE_B):
            expected = predict(source)
            Inspection.objects.all().delete()
            Batch.objects.all().delete()
            self.post_batch([upload(source, name) for name in names])
            for item in Inspection.objects.all():
                with self.subTest(source=source.name, name=item.original_filename):
                    self.assertEqual(item.status, 'completed')
                    self.assertEqual(item.predicted_class, expected['predicted_class'])
                    self.assertAlmostEqual(item.defect_probability, expected['defect_probability'])


class PermissionTests(BatchTestBase):
    def test_non_engineers_cannot_submit(self):
        for user in (self.no_role, self.supervisor):
            with self.subTest(user=user.username):
                response = self.post_batch([upload(SAMPLE_A)], user=user)
                self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(None)
        response = self.client.post(
            '/api/batches/', {'product': 'P-PLATE01', 'files': [upload(SAMPLE_A)]}, format='multipart'
        )
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Batch.objects.count(), 0)

    def test_engineer_cannot_see_another_engineers_batch(self):
        batch_id = self.post_batch([upload(SAMPLE_A)]).json()['id']
        url = f'/api/batches/{batch_id}/'

        self.client.force_authenticate(self.engineer2)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_authenticate(self.engineer)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_authenticate(self.supervisor)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.force_authenticate(self.no_role)
        self.assertEqual(self.client.get(url).status_code, 403)


class TaskIdempotencyTests(BatchTestBase):
    def test_rerun_does_not_overwrite_completed_result(self):
        self.post_batch([upload(SAMPLE_A)])
        item = Inspection.objects.get()
        self.assertEqual(item.status, 'completed')
        before = (item.predicted_class, item.confidence, item.defect_probability, item.model_version)

        fake = {'predicted_class': 'Normal', 'confidence': 0.01, 'defect_probability': 0.99,
                'model_version': 'FAKE'}
        with mock.patch('inspections.tasks.predict', return_value=fake) as spy:
            self.assertEqual(process_inspection(item.pk), 'skipped')
            process_inspection.delay(item.pk)
        spy.assert_not_called()

        item.refresh_from_db()
        self.assertEqual(item.status, 'completed')
        self.assertEqual(
            (item.predicted_class, item.confidence, item.defect_probability, item.model_version), before
        )

    def test_rerun_never_sends_invalid_item_to_model(self):
        self.post_batch([upload(VALIDATION_FILES[0])])
        item = Inspection.objects.get()
        with mock.patch('inspections.tasks.predict') as spy:
            self.assertEqual(process_inspection(item.pk), 'skipped')
        spy.assert_not_called()
        item.refresh_from_db()
        self.assertEqual(item.status, 'failed')


class PersistenceTests(BatchTestBase):
    def test_records_persist(self):
        response = self.post_batch([upload(SAMPLE_A), upload(VALIDATION_FILES[1])])
        batch_id = response.json()['id']

        # Read back from the database with fresh queries, not from the response.
        batch = Batch.objects.get(pk=batch_id)
        self.assertEqual(batch.product, self.product)
        self.assertEqual(batch.submitted_by, self.engineer)
        self.assertIsNotNone(batch.created_at)
        items = list(batch.items.order_by('id'))
        self.assertEqual([i.status for i in items], ['completed', 'failed'])
        for item in items:
            self.assertEqual(item.product, self.product)
            self.assertEqual(item.submitted_by, self.engineer)
        self.assertTrue(Path(items[0].image.path).exists())

        self.client.force_authenticate(self.engineer)
        body = self.client.get(f'/api/batches/{batch_id}/').json()
        self.assertEqual(
            set(body['items'][0]),
            {'id', 'original_filename', 'status', 'failure_reason', 'predicted_class',
             'confidence', 'defect_probability', 'model_version'},
        )
        self.assertEqual(body['items'][0]['predicted_class'], items[0].predicted_class)


class CommandTests(TestCase):
    def test_load_products_is_idempotent(self):
        call_command('load_products', stdout=io.StringIO())
        call_command('load_products', stdout=io.StringIO())
        self.assertEqual(Product.objects.filter(product_id='P-PLATE01').count(), 1)

    def test_evaluate_samples_writes_report(self):
        out = Path(tempfile.mkdtemp()) / 'report.txt'
        call_command('evaluate_samples', output=str(out), stdout=io.StringIO())
        text = out.read_text(encoding='utf-8')
        self.assertIn('Images found: 60', text)
        self.assertIn('Defect recall', text)
        self.assertNotIn('Validation/', text)
        shutil.rmtree(out.parent, ignore_errors=True)
