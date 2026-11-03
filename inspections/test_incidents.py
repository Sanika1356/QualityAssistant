"""
Round 3 incident tests. The real SOP search runs on a temporary copy of the
SOPs; only the AI reply is mocked, so Groq is not needed.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from rest_framework.test import APIClient

from .models import Incident, Review
from .test_sop_assistant import GOOD_REPLY, SopTestBase

URL = '/api/incidents/'


class IncidentTestBase(SopTestBase):
    def setUp(self):
        super().setUp()
        self.engineer = self.user
        self.engineer.groups.add(Group.objects.get_or_create(name='Engineer')[0])
        self.engineer2 = self.make_user('eng2', 'Engineer')
        self.supervisor = self.make_user('sup', 'Supervisor')
        self.admin = self.make_user('adm', 'Administrator')
        patcher = mock.patch('inspections.sop_assistant.llm.generate', return_value=GOOD_REPLY)
        self.ask_llm = patcher.start()
        self.addCleanup(patcher.stop)

    def make_user(self, name, group):
        user = User.objects.create_user(username=name, password='pass12345')
        user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    def as_user(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def create(self, inspection=None, user=None):
        inspection = inspection or self.inspection
        return self.as_user(user or self.engineer).post(
            URL, {'inspection_id': inspection.pk}, format='json'
        )

    def decide(self, incident_id, user=None, decision='Approved for follow-up', comment='Checked.'):
        return self.as_user(user or self.supervisor).post(
            f'{URL}{incident_id}/decision/',
            {'decision': decision, 'review_comment': comment},
            format='json',
        )


class CreateTests(IncidentTestBase):
    def test_defective_creates_cited_incident(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertEqual(data['evidence_status'], 'Sufficient')
        self.assertEqual(data['decision'], 'Pending')
        self.assertFalse(data['manual_review_required'])
        self.assertEqual(data['original_prediction'], 'Defective')
        self.assertEqual(data['model_version_snapshot'], 'BIT-PLATE-CV-1.0')
        self.assertIn('flagged by the classifier', data['summary'])
        self.assertEqual(data['created_by'], 'eng')
        self.assertTrue(data['actions'])
        for action in data['actions']:
            for source in action['sources']:
                self.assertIn(source['document_id'], {'Q-PLATE-01', 'Q-PLATE-02'})
                self.assertGreaterEqual(source['page_number'], 1)
                self.assertTrue(source['passage'])
                self.assertIn(f"#page={source['page_number']}", source['source_url'])

    def test_repeat_request_returns_same_incident(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['incident_id'], second.data['incident_id'])
        self.assertEqual(Incident.objects.count(), 1)
        self.assertEqual(self.ask_llm.call_count, 1)

    def test_repeat_request_keeps_the_review(self):
        incident_id = self.create().data['incident_id']
        self.assertEqual(self.decide(incident_id).status_code, 200)
        again = self.create()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['decision'], 'Approved for follow-up')
        self.assertEqual(again.data['review_comment'], 'Checked.')

    def test_normal_gets_message_and_no_incident(self):
        inspection = self.make_inspection(self.plate, predicted_class='Normal')
        response = self.create(inspection)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.data['detail'])
        self.assertEqual(Incident.objects.count(), 0)

    def test_unfinished_inspections_get_message_and_no_incident(self):
        for state in ('queued', 'processing', 'failed'):
            inspection = self.make_inspection(self.plate, status=state, predicted_class=None)
            response = self.create(inspection)
            self.assertEqual(response.status_code, 400, state)
        self.assertEqual(Incident.objects.count(), 0)

    def test_human_correction_does_not_change_eligibility(self):
        Review.objects.create(
            inspection=self.inspection, reviewed_class='Normal',
            reviewer=self.supervisor, comment='Looks fine.',
        )
        normal = self.make_inspection(self.plate, predicted_class='Normal')
        Review.objects.create(inspection=normal, reviewed_class='Defective', reviewer=self.supervisor)

        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['original_prediction'], 'Defective')
        self.assertIn('Looks fine.', response.data['human_correction'])
        self.assertEqual(self.create(normal).status_code, 400)

    def test_round2_result_is_not_overwritten(self):
        self.create()
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.predicted_class, 'Defective')
        self.assertEqual(self.inspection.confidence, 0.97)


class EvidenceFailureTests(IncidentTestBase):
    def assert_insufficient(self, response):
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['evidence_status'], 'Insufficient')
        self.assertTrue(response.data['evidence_reason'])
        self.assertTrue(response.data['manual_review_required'])
        self.assertEqual(response.data['actions'], [])
        self.assertEqual(response.data['sources'], [])
        self.assertEqual(Incident.objects.count(), 1)

    def test_missing_sop_file(self):
        (self.tmp / 'SOPs' / 'Q_PLATE_02_Review_Rev1_0.pdf').unlink()
        self.assert_insufficient(self.create())
        self.ask_llm.assert_not_called()

    def test_unmapped_product(self):
        self.plate.product_id = 'P-UNKNOWN'
        self.plate.save()
        self.assert_insufficient(self.create())
        self.ask_llm.assert_not_called()

    def test_ai_failure(self):
        self.ask_llm.side_effect = RuntimeError('secret-key-123 rejected')
        response = self.create()
        self.assert_insufficient(response)
        self.assertNotIn('secret-key-123', response.data['evidence_reason'])

    def test_unexpected_crash_still_saves_incident(self):
        with mock.patch(
            'inspections.sop_assistant.generate_incident_content',
            side_effect=RuntimeError('secret-key-123'),
        ):
            response = self.create()
        self.assert_insufficient(response)
        self.assertNotIn('secret-key-123', response.data['evidence_reason'])

    def test_insufficient_cannot_be_approved(self):
        (self.tmp / 'SOPs' / 'Q_PLATE_02_Review_Rev1_0.pdf').unlink()
        incident_id = self.create().data['incident_id']
        self.assertEqual(self.decide(incident_id).status_code, 400)
        ok = self.decide(incident_id, decision='Needs more information')
        self.assertEqual(ok.status_code, 200)


class PermissionTests(IncidentTestBase):
    def test_only_engineers_create(self):
        for user in (self.supervisor, self.admin):
            self.assertEqual(self.create(user=user).status_code, 403)
        self.assertEqual(APIClient().post(URL, {'inspection_id': 1}).status_code, 403)
        self.assertEqual(Incident.objects.count(), 0)

    def test_engineer_cannot_use_another_engineers_inspection(self):
        self.assertEqual(self.create(user=self.engineer2).status_code, 404)

    def test_engineer_sees_only_own_supervisor_sees_all(self):
        incident_id = self.create().data['incident_id']
        other = self.as_user(self.engineer2)
        self.assertEqual(other.get(URL).data, [])
        self.assertEqual(other.get(f'{URL}{incident_id}/').status_code, 404)
        self.assertEqual(len(self.as_user(self.engineer).get(URL).data), 1)
        self.assertEqual(len(self.as_user(self.supervisor).get(URL).data), 1)

    def test_engineer_and_admin_cannot_decide(self):
        incident_id = self.create().data['incident_id']
        self.assertEqual(self.decide(incident_id, user=self.engineer).status_code, 403)
        self.assertEqual(self.decide(incident_id, user=self.admin).status_code, 403)
        self.assertEqual(self.as_user(self.admin).get(URL).status_code, 403)
        self.assertEqual(Incident.objects.get().decision, 'Pending')

    def test_supervisor_decision_is_saved(self):
        incident_id = self.create().data['incident_id']
        self.assertEqual(self.decide(incident_id).status_code, 200)
        data = self.as_user(self.supervisor).get(f'{URL}{incident_id}/').data
        self.assertEqual(data['decision'], 'Approved for follow-up')
        self.assertEqual(data['reviewer'], 'sup')
        self.assertEqual(data['review_comment'], 'Checked.')
        self.assertTrue(data['reviewed_at'])

    def test_comment_is_required(self):
        incident_id = self.create().data['incident_id']
        for comment in ('', '   '):
            self.assertEqual(self.decide(incident_id, comment=comment).status_code, 400)
        self.assertEqual(Incident.objects.get().decision, 'Pending')

    def test_pending_cannot_be_chosen_as_a_decision(self):
        incident_id = self.create().data['incident_id']
        self.assertEqual(self.decide(incident_id, decision='Pending').status_code, 400)


class BriefGapTests(IncidentTestBase):
    """Engineer denial, saved inspection fields, both SOPs cited, no 100% confidence."""

    def test_engineer_review_attempt_is_denied_and_not_saved(self):
        incident_id = self.create().data['incident_id']
        # Exactly what the "Attempt review as Engineer" button sends.
        response = self.as_user(self.engineer).post(
            f'{URL}{incident_id}/decision/',
            {'decision': 'Needs more information',
             'review_comment': 'Engineer review attempt: the server must refuse this.'},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data['detail'], 'Only Supervisors can review incidents.')
        incident = Incident.objects.get()
        self.assertEqual(incident.decision, 'Pending')
        self.assertIsNone(incident.reviewer)
        self.assertEqual(incident.review_comment, '')
        self.assertIsNone(incident.reviewed_at)

    def test_engineer_attempt_button_posts_to_decision_endpoint(self):
        from django.conf import settings
        script = (settings.BASE_DIR / 'static' / 'js' / 'incidents.js').read_text(encoding='utf-8')
        self.assertIn('Attempt review as Engineer', script)
        self.assertIn('/decision/`', script)
        self.assertIn("method: 'POST'", script)

    def test_incident_shows_saved_inspection(self):
        self.inspection.image = 'inspections/sample.png'
        self.inspection.original_filename = 'plate_042.png'
        self.inspection.save()
        data = self.create().data
        self.assertEqual(data['inspection_original_filename'], 'plate_042.png')
        self.assertEqual(data['inspection_submitted_by'], 'eng')
        self.assertTrue(data['inspection_inspected_at'])
        self.assertTrue(data['inspection_image_url'].endswith(f'/api/inspections/{self.inspection.pk}/image/'))

        reloaded = self.as_user(self.supervisor).get(f"{URL}{data['incident_id']}/").data
        self.assertEqual(reloaded['inspection_original_filename'], 'plate_042.png')
        self.assertEqual(reloaded['inspection_image_url'], data['inspection_image_url'])

    def test_incident_without_saved_image_has_no_image_url(self):
        self.assertIsNone(self.create().data['inspection_image_url'])

    def test_sufficient_incident_cites_both_plate_sops(self):
        data = self.create().data
        self.assertEqual(data['evidence_status'], 'Sufficient')
        self.assertEqual({s['document_id'] for s in data['sources']}, {'Q-PLATE-01', 'Q-PLATE-02'})
        self.assertTrue(data['evidence_reason'])

    def test_uncited_required_sop_saves_insufficient(self):
        from .test_sop_assistant import ONLY_PLATE_01_REPLY
        self.ask_llm.return_value = ONLY_PLATE_01_REPLY
        response = self.create()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['evidence_status'], 'Insufficient')
        self.assertTrue(response.data['manual_review_required'])
        self.assertEqual(response.data['actions'], [])
        self.assertEqual(response.data['sources'], [])
        self.assertEqual(Incident.objects.count(), 1)
        self.assertEqual(self.ask_llm.call_count, 2)
        self.assertIn('Q-PLATE-02', response.data['evidence_reason'])

    def test_summary_never_says_100_percent(self):
        self.inspection.confidence = 0.9999999999999996
        self.inspection.save()
        summary = self.create().data['summary']
        self.assertIn('confidence > 99.9%', summary)
        self.assertNotIn('100.0%', summary)
        self.assertNotIn('100%', summary)
