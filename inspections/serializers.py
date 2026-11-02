from django.urls import reverse
from rest_framework import serializers

from .models import Batch, Inspection


class BatchItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Inspection
        fields = [
            'id', 'original_filename', 'status', 'failure_reason', 'predicted_class',
            'confidence', 'defect_probability', 'model_version', 'image_url',
        ]

    def get_image_url(self, item):
        # Points at the access-checked endpoint, never at the raw media file.
        if not item.image:
            return None
        url = reverse('inspection-image', args=[item.pk])
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url


class BatchSerializer(serializers.ModelSerializer):
    product = serializers.CharField(source='product.product_id')
    submitted_by = serializers.CharField(source='submitted_by.username')
    status_counts = serializers.SerializerMethodField()
    items = BatchItemSerializer(many=True)

    class Meta:
        model = Batch
        fields = ['id', 'product', 'submitted_by', 'created_at', 'status_counts', 'items']

    def get_status_counts(self, batch):
        counts = {status: 0 for status in Inspection.Status.values}
        for item in batch.items.all():
            counts[item.status] += 1
        return counts
