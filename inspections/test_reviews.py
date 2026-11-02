from django.test import TestCase
from django.contrib.auth.models import User, Group
from rest_framework.test import APIClient
from rest_framework import status

from .models import Product, Inspection, Review


class InspectionPermissionTests(TestCase):

    def setUp(self):

        # Create roles
        self.engineer_group, _ = Group.objects.get_or_create(
            name="Engineer"
        )
        self.supervisor_group, _ = Group.objects.get_or_create(
            name="Supervisor"
        )

        # Create users
        self.engineer = User.objects.create_user(
            username="test_engineer",
            password="test123"
        )
        self.engineer.groups.add(self.engineer_group)

        self.other_engineer = User.objects.create_user(
            username="other_engineer",
            password="test123"
        )
        self.other_engineer.groups.add(self.engineer_group)

        self.supervisor = User.objects.create_user(
            username="test_supervisor",
            password="test123"
        )
        self.supervisor.groups.add(self.supervisor_group)

        # Create product
        self.product = Product.objects.create(
            product_id="TEST-PLATE",
            name="Test Plate",
            description="Testing product"
        )

        # Engineer's inspection
        self.inspection = Inspection.objects.create(
            product=self.product,
            image="test-image.jpg",
            original_filename="test-image.jpg",
            status="completed",
            predicted_class="Normal",
            confidence=0.92,
            defect_probability=0.08,
            model_version="test-v1",
            submitted_by=self.engineer
        )

        # Another engineer's inspection
        self.other_inspection = Inspection.objects.create(
            product=self.product,
            image="other-image.jpg",
            original_filename="other-image.jpg",
            status="completed",
            predicted_class="Defective",
            confidence=0.88,
            defect_probability=0.88,
            model_version="test-v1",
            submitted_by=self.other_engineer
        )

        self.client = APIClient()

    def test_engineer_sees_only_own_inspections(self):

        self.client.force_authenticate(user=self.engineer)

        response = self.client.get("/api/inspections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            response.data[0]["id"],
            self.inspection.id
        )

    def test_supervisor_sees_all_inspections(self):

        self.client.force_authenticate(user=self.supervisor)

        response = self.client.get("/api/inspections/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_engineer_cannot_submit_review(self):

        self.client.force_authenticate(user=self.engineer)

        response = self.client.post(
            f"/api/inspections/{self.inspection.id}/review/",
            {
                "reviewed_class": "Defective",
                "comment": "Testing permission"
            },
            format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )

        self.assertFalse(
            Review.objects.filter(
                inspection=self.inspection
            ).exists()
        )

    def test_supervisor_can_review_inspection(self):

        self.client.force_authenticate(user=self.supervisor)

        response = self.client.post(
            f"/api/inspections/{self.inspection.id}/review/",
            {
                "reviewed_class": "Defective",
                "comment": "Testing supervisor review"
            },
            format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED
        )

        self.inspection.refresh_from_db()

        # Original AI prediction must remain unchanged
        self.assertEqual(
            self.inspection.predicted_class,
            "Normal"
        )

        self.assertEqual(
            self.inspection.confidence,
            0.92
        )

        # Separate review must exist
        self.assertTrue(
            Review.objects.filter(
                inspection=self.inspection,
                reviewed_class="Defective"
            ).exists()
        )

    def test_product_creation_denied_for_engineer(self):

        self.client.force_authenticate(user=self.engineer)

        response = self.client.post(
            "/api/products/",
            {
                "product_id": "NEW-PLATE",
                "name": "New Plate",
                "description": "Testing"
            },
            format="json"
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN
        )
    def test_inspection_review_status_filters(self):

        self.client.force_authenticate(user=self.supervisor)

        # Create a confirmed review
        Review.objects.create(
            inspection=self.inspection,
            reviewed_class="Normal",
            reviewer=self.supervisor,
            comment="AI prediction is correct"
        )

        # Create a corrected review
        Review.objects.create(
            inspection=self.other_inspection,
            reviewed_class="Normal",
            reviewer=self.supervisor,
            comment="AI prediction corrected"
        )

        # Create an inspection waiting for review
        pending_inspection = Inspection.objects.create(
            product=self.product,
            original_filename="pending.jpg",
            image="pending.jpg",
            status="completed",
            predicted_class="Normal",
            confidence=0.85,
            defect_probability=0.15,
            model_version="test-v1",
            submitted_by=self.engineer
        )

        # Test pending filter
        response = self.client.get(
            "/api/inspections/?review_status=pending"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data],
            [pending_inspection.id]
        )

        # Test confirmed filter
        response = self.client.get(
            "/api/inspections/?review_status=confirmed"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data],
            [self.inspection.id]
        )

        # Test corrected filter
        response = self.client.get(
            "/api/inspections/?review_status=corrected"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.data],
            [self.other_inspection.id]
        )


class ReviewRuleTests(InspectionPermissionTests):

    def review_url(self, inspection):
        return f"/api/inspections/{inspection.id}/review/"

    def test_failed_inspection_cannot_be_reviewed_and_is_not_pending(self):
        failed = Inspection.objects.create(
            product=self.product,
            original_filename="bad.png",
            status="failed",
            failure_reason="Not an image",
            submitted_by=self.engineer,
        )
        self.client.force_authenticate(user=self.supervisor)

        response = self.client.post(
            self.review_url(failed), {"reviewed_class": "Normal"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        pending = self.client.get("/api/inspections/?review_status=pending")
        self.assertNotIn(failed.id, [row["id"] for row in pending.data])

    def test_second_review_is_refused_and_first_is_kept(self):
        self.client.force_authenticate(user=self.supervisor)
        first = self.client.post(
            self.review_url(self.inspection),
            {"reviewed_class": "Defective", "comment": "Scratch visible"},
            format="json",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.data["predicted_class"], "Normal")
        self.assertEqual(first.data["review"]["reviewed_class"], "Defective")
        self.assertEqual(first.data["review_status"], "corrected")

        second = self.client.post(
            self.review_url(self.inspection), {"reviewed_class": "Normal"}, format="json"
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Review.objects.get(inspection=self.inspection).reviewed_class, "Defective")

    def test_engineer_denied_and_nothing_changes(self):
        self.client.force_authenticate(user=self.engineer)
        response = self.client.post(
            self.review_url(self.inspection), {"reviewed_class": "Defective"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Review.objects.exists())
        self.inspection.refresh_from_db()
        self.assertEqual(self.inspection.predicted_class, "Normal")

    def test_engineer_cannot_open_another_engineers_record(self):
        self.client.force_authenticate(user=self.engineer)
        response = self.client.get(f"/api/inspections/{self.other_inspection.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_history_gives_a_protected_image_link_not_a_media_path(self):
        self.client.force_authenticate(user=self.engineer)
        row = self.client.get(f"/api/inspections/{self.inspection.id}/").data
        self.assertIn(f"/api/inspections/{self.inspection.id}/image/", row["image_url"])
        self.assertNotIn("image", [key for key in row if key == "image"])
