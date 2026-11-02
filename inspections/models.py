import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def inspection_upload_path(instance, filename):
    # Store under a random name so the uploaded filename never matters on disk.
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg'):
        suffix = ''
    return f'inspections/{uuid.uuid4().hex}{suffix}'


class Product(models.Model):
    product_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    def __str__(self):
        return f'{self.product_id} - {self.name}'


class Batch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='batches')
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='batches'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'batches'

    def __str__(self):
        return f'Batch {self.pk} ({self.product.product_id})'


class Inspection(models.Model):
    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    class PredictedClass(models.TextChoices):
        NORMAL = 'Normal', 'Normal'
        DEFECTIVE = 'Defective', 'Defective'

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='inspections')
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, null=True, blank=True, related_name='items'
    )
    # Empty for uploads that failed validation: untrusted bytes are not kept on disk.
    image = models.FileField(upload_to=inspection_upload_path, max_length=255, blank=True)
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    failure_reason = models.TextField(blank=True)
    predicted_class = models.CharField(
        max_length=20, choices=PredictedClass.choices, null=True, blank=True
    )
    confidence = models.FloatField(null=True, blank=True)
    defect_probability = models.FloatField(null=True, blank=True)
    model_version = models.CharField(max_length=50, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='inspections'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'Inspection {self.pk} [{self.status}] {self.original_filename}'


class Review(models.Model):
    """A Supervisor's decision, kept apart from the model's original output."""

    inspection = models.OneToOneField(Inspection, on_delete=models.PROTECT, related_name='review')
    reviewed_class = models.CharField(max_length=20, choices=Inspection.PredictedClass.choices)
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='inspection_reviews'
    )
    comment = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Review for inspection {self.inspection_id}'
