"""
Tests for the SOP assistant. The AI is always mocked, so Groq is not needed.

Each test works on a temporary copy of pack_data so files can be removed or
changed safely, and uses the offline hash embedding backend.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from . import sop_assistant, sop_loader
from .models import Inspection, Product, Review

REAL_PACK = Path(settings.BASE_DIR) / 'pack_data'

GOOD_REPLY = (
    'ACTION: Record a proposed quality hold for the inspected item pending Supervisor review [1]\n'
    'ACTION: Request a Supervisor review of the image and inspection record [2]'
)


class SopTestBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(REAL_PACK / 'SOPs', self.tmp / 'SOPs')
        shutil.copy(REAL_PACK / 'product_sop_mapping.csv', self.tmp / 'product_sop_mapping.csv')
        self.settings_override = override_settings(
            SOP_PACK_DIR=self.tmp,
            SOP_INDEX_PATH=self.tmp / 'index.json',
            SOP_EMBEDDING_BACKEND='hash',
        )
        self.settings_override.enable()

        self.user = User.objects.create_user(username='eng', password='pass12345')
        self.plate = Product.objects.create(product_id='P-PLATE01', name='Demonstration metal plate')
        self.inspection = self.make_inspection(self.plate)

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_inspection(self, product, **fields):
        values = dict(
            product=product, original_filename='x.png', status='completed',
            predicted_class='Defective', confidence=0.97, defect_probability=0.97,
            model_version='BIT-PLATE-CV-1.0', submitted_by=self.user,
        )
        values.update(fields)
        return Inspection.objects.create(**values)

    def rewrite_mapping(self, transform):
        path = self.tmp / 'product_sop_mapping.csv'
        lines = path.read_text(encoding='utf-8').splitlines()
        path.write_text('\n'.join(transform(lines)) + '\n', encoding='utf-8')

    def run_with_reply(self, *replies):
        with mock.patch.object(sop_assistant.llm, 'generate', side_effect=list(replies)) as fake:
            result = sop_assistant.generate_incident_content(self.inspection)
        return result, fake

    def assert_insufficient(self, result):
        self.assertEqual(result['evidence_status'], 'Insufficient')
        self.assertTrue(result['evidence_reason'])
        self.assertEqual(result['actions'], [])
        self.assertNotIn(str(self.tmp), result['evidence_reason'])


class MappingAndRetrievalTests(SopTestBase):
    def test_correct_mapping(self):
        plate = {(r['document_id'], r['revision']) for r in sop_loader.mapped_documents('P-PLATE01')}
        gasket = {(r['document_id'], r['revision']) for r in sop_loader.mapped_documents('P-GASKET02')}
        self.assertEqual(plate, {('Q-PLATE-01', '1.0'), ('Q-PLATE-02', '1.0')})
        self.assertEqual(gasket, {('Q-GASKET-01', '1.0')})

    def test_product_id_matched_exactly(self):
        with self.assertRaises(sop_loader.MissingEvidence):
            sop_loader.mapped_documents('p-plate01')

    def test_gasket_never_in_plate_retrieval(self):
        passages, _ = sop_assistant.retrieve('P-PLATE01')
        self.assertTrue(passages)
        self.assertTrue(all(p.document_id.startswith('Q-PLATE') for p in passages))

        result, fake = self.run_with_reply(GOOD_REPLY)
        prompt = fake.call_args[0][1]
        self.assertNotIn('GASKET', prompt.upper())
        self.assertEqual(result['evidence_status'], 'Sufficient')

    def test_gasket_chunk_leaking_from_loader_is_removed(self):
        real = sop_loader.get_sop_chunks
        leaked = sop_loader.SopChunk('P-PLATE01', 'Q-GASKET-01', '1.0', 'g.pdf', 1,
                                     'Gasket record: quality hold Supervisor review evidence inspection.')
        with mock.patch.object(sop_loader, 'get_sop_chunks', lambda pid: real(pid) + [leaked]):
            passages, _ = sop_assistant.retrieve('P-PLATE01')
            result, fake = self.run_with_reply(GOOD_REPLY)
        self.assertNotIn(leaked, passages)
        self.assertNotIn('GASKET', fake.call_args[0][1].upper())
        self.assertEqual(result['evidence_status'], 'Sufficient')

    def test_both_plate_sops_in_prompt(self):
        result, fake = self.run_with_reply(GOOD_REPLY)
        prompt = fake.call_args[0][1]
        self.assertIn('document="Q-PLATE-01"', prompt)
        self.assertIn('document="Q-PLATE-02"', prompt)

    def test_missing_plate_02_passages_gives_insufficient(self):
        real = sop_loader.get_sop_chunks
        only_01 = lambda pid: [c for c in real(pid) if c.document_id != 'Q-PLATE-02']
        with mock.patch.object(sop_loader, 'get_sop_chunks', only_01):
            result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        self.assertIn('Q-PLATE-02', result['evidence_reason'])
        fake.assert_not_called()

    def test_plate_02_mapping_row_removed_gives_insufficient(self):
        self.rewrite_mapping(lambda lines: [l for l in lines if 'Q-PLATE-02' not in l])
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        self.assertIn('Q-PLATE-02', result['evidence_reason'])
        fake.assert_not_called()

    def test_pages_are_one_based_and_correct(self):
        chunks = sop_loader.get_sop_chunks('P-PLATE01')
        self.assertEqual(min(c.page_number for c in chunks), 1)
        self.assertEqual(max(c.page_number for c in chunks), 2)
        hold = [c for c in chunks if 'proposed quality hold' in c.text]
        self.assertEqual([(c.document_id, c.page_number) for c in hold], [('Q-PLATE-01', 1)])
        boundaries = [c for c in chunks if 'does not identify scratches versus pits' in c.text]
        self.assertEqual([(c.document_id, c.page_number) for c in boundaries], [('Q-PLATE-01', 2)])

    def test_source_details_come_from_real_chunks(self):
        result, fake = self.run_with_reply(GOOD_REPLY)
        passages, _ = sop_assistant.retrieve('P-PLATE01')
        source = result['actions'][0]['sources'][0]
        self.assertEqual(source['passage_number'], 1)
        self.assertEqual(source['document_id'], passages[0].document_id)
        self.assertEqual(source['page_number'], passages[0].page_number)
        self.assertEqual(source['passage'], passages[0].text)
        self.assertEqual(
            source['source_url'],
            f"/sops/{passages[0].document_id}/1.0/#page={passages[0].page_number}",
        )


class ReplyCheckTests(SopTestBase):
    def test_invented_citation_rejected(self):
        bad = 'ACTION: Record a proposed quality hold pending Supervisor review [99]'
        result, fake = self.run_with_reply(bad, bad)
        self.assert_insufficient(result)
        self.assertEqual(fake.call_count, 2)  # retried once

    def test_missing_citation_rejected_then_retry_succeeds(self):
        result, fake = self.run_with_reply('ACTION: Request Supervisor review', GOOD_REPLY)
        self.assertEqual(result['evidence_status'], 'Sufficient')
        self.assertEqual(fake.call_count, 2)

    def test_invalid_action_dropped_and_valid_kept(self):
        mixed = GOOD_REPLY + '\nACTION: Ask the supplier for a replacement [1]'
        result, _ = self.run_with_reply(mixed, mixed)
        self.assertEqual(result['evidence_status'], 'Sufficient')
        self.assertEqual(len(result['actions']), 2)
        self.assertNotIn('supplier', str(result['actions']).lower())

    def test_forbidden_claims_rejected(self):
        claims = [
            'The item has a scratch', 'The defect is a pit', 'Find the root cause',
            'Severity is high', 'Depth is 0.5 mm', 'Repair the plate', 'Grind the surface',
            'Check the tolerance', 'Estimate the cost', 'Contact the supplier', 'Scrap the item',
            'Release the item', 'Authorize rework', 'Dispose of the batch',
            'Shut down the line', 'Change equipment settings', 'Record a confirmed defect',
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                reply = f'ACTION: {claim} [1]'
                result, _ = self.run_with_reply(reply, reply)
                self.assert_insufficient(result)

    def test_other_document_rejected(self):
        for name in ('Q-GASKET-01', 'Q-PLATE-99'):
            with self.subTest(name=name):
                reply = f'ACTION: Follow {name} for review [1]'
                result, _ = self.run_with_reply(reply, reply)
                self.assert_insufficient(result)

    def test_odd_spaces_and_citation_styles(self):
        reply = (
            'ACTION:\u202fRecord a proposed quality hold for the inspected item【1†L3-L5】\n'
            '- ACTION: Request a Supervisor review ［2］\n'
            '1. ACTION: Preserve the original image and model output [1, 3]'
        )
        result, _ = self.run_with_reply(reply)
        self.assertEqual(result['evidence_status'], 'Sufficient')
        self.assertEqual([[s['passage_number'] for s in a['sources']] for a in result['actions']],
                         [[1], [2], [1, 3]])
        self.assertNotIn('\u202f', result['actions'][0]['text'])
        self.assertNotIn('【', str(result))

    def test_refusal_gives_insufficient(self):
        result, _ = self.run_with_reply('NOT_ENOUGH_INFORMATION', 'NOT_ENOUGH_INFORMATION')
        self.assert_insufficient(result)

    def test_empty_reply_gives_insufficient(self):
        result, _ = self.run_with_reply('', '')
        self.assert_insufficient(result)


class FailureTests(SopTestBase):
    def test_ai_failure_gives_insufficient(self):
        error = sop_assistant.llm.LLMUnavailable('The AI service is busy (rate limit reached). Please try again in a minute.')
        result, _ = self.run_with_reply(error)
        self.assert_insufficient(result)
        self.assertIn('rate limit', result['evidence_reason'])

    def test_unexpected_ai_error_gives_insufficient(self):
        result, _ = self.run_with_reply(RuntimeError('secret path C:/x'))
        self.assert_insufficient(result)
        self.assertNotIn('C:/x', result['evidence_reason'])

    def test_missing_mapping_gives_insufficient(self):
        (self.tmp / 'product_sop_mapping.csv').unlink()
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        fake.assert_not_called()

    def test_missing_pdf_gives_insufficient(self):
        (self.tmp / 'SOPs' / 'Q_PLATE_02_Review_Rev1_0.pdf').unlink()
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        self.assertIn('Q-PLATE-02', result['evidence_reason'])
        fake.assert_not_called()

    def test_unreadable_pdf_gives_insufficient(self):
        (self.tmp / 'SOPs' / 'Q_PLATE_01_Containment_Rev1_0.pdf').write_bytes(b'not a pdf')
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        fake.assert_not_called()

    def test_no_relevant_passages_gives_insufficient(self):
        with mock.patch.object(sop_loader, 'get_sop_chunks', lambda pid: []):
            result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        fake.assert_not_called()

    def test_low_scores_give_insufficient(self):
        with override_settings(SOP_MIN_SCORE=0.99):
            result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        fake.assert_not_called()

    def test_unknown_product_gives_insufficient(self):
        self.inspection = self.make_inspection(Product.objects.create(product_id='P-PLATE02', name='Other'))
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        self.assertIn('P-PLATE02', result['evidence_reason'])
        fake.assert_not_called()

    def test_revision_mismatch_gives_insufficient(self):
        self.rewrite_mapping(lambda lines: [l.replace('Q-PLATE-02,1.0', 'Q-PLATE-02,2.0') for l in lines])
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        self.assertIn('revision 2.0', result['evidence_reason'])
        fake.assert_not_called()

    def test_normal_prediction_not_processed(self):
        self.inspection = self.make_inspection(self.plate, predicted_class='Normal')
        result, fake = self.run_with_reply(GOOD_REPLY)
        self.assert_insufficient(result)
        fake.assert_not_called()


class SummaryAndRecordTests(SopTestBase):
    def test_summary_is_factual(self):
        result, _ = self.run_with_reply(GOOD_REPLY)
        summary = result['summary']
        for fact in ('P-PLATE01', f'Inspection {self.inspection.pk}', 'eng', 'Defective',
                     '97.0%', 'BIT-PLATE-CV-1.0', 'flagged by the classifier',
                     'Batch or lot reference: Not provided'):
            self.assertIn(fact, summary)
        self.assertNotIn('confirmed', summary.lower())
        self.assertIsNone(result['human_correction'])

    def test_confidence_never_printed_as_100_percent(self):
        cases = [
            (1.0, '> 99.9%'), (0.9999999999999996, '> 99.9%'), (0.9995, '> 99.9%'),
            (0.9994, '99.9%'), (0.97, '97.0%'), (0.0005, '0.1%'), (0.0004, '< 0.1%'),
            (0.0, '< 0.1%'), (None, 'Not recorded'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(sop_assistant.format_percent(value), expected)

        self.inspection = self.make_inspection(self.plate, confidence=1.0)
        summary = sop_assistant.build_summary(self.inspection)
        self.assertIn('confidence > 99.9%', summary)
        self.assertNotIn('100.0%', summary)
        self.assertNotIn('100%', summary)

    def test_human_correction_kept_separate_and_nothing_overwritten(self):
        supervisor = User.objects.create_user(username='sup', password='pass12345')
        Review.objects.create(inspection=self.inspection, reviewed_class='Normal',
                              reviewer=supervisor, comment='Looks clean')
        self.inspection.refresh_from_db()
        result, _ = self.run_with_reply(GOOD_REPLY)
        self.assertIn('sup', result['human_correction'])
        self.assertIn('Normal', result['human_correction'])
        self.assertIn('Defective', result['summary'])

        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.predicted_class, 'Defective')
        self.assertEqual(self.inspection.confidence, 0.97)
        self.assertEqual(self.inspection.review.reviewed_class, 'Normal')

    def test_index_command_indexes_only_mapped_pdfs(self):
        from django.core.management import call_command
        (self.tmp / 'SOPs' / 'unmapped.pdf').write_bytes(
            (self.tmp / 'SOPs' / 'Q_PLATE_01_Containment_Rev1_0.pdf').read_bytes())
        call_command('index_sops', stdout=mock.MagicMock())
        index = (self.tmp / 'index.json').read_text(encoding='utf-8')
        self.assertIn('Q-PLATE-01', index)
        self.assertIn('Q-GASKET-01', index)
        self.assertNotIn('unmapped', index)


class SopPdfRouteTests(SopTestBase):
    def test_login_required(self):
        response = self.client.get('/sops/Q-PLATE-01/1.0/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_mapped_pdf_served(self):
        self.client.force_login(self.user)
        response = self.client.get('/sops/Q-PLATE-01/1.0/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))

    def test_unmapped_document_or_revision_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/sops/Q-PLATE-01/2.0/').status_code, 404)
        self.assertEqual(self.client.get('/sops/..%2Fsettings/1.0/').status_code, 404)
