from django.urls import reverse
from rest_framework import serializers

from .models import Batch, Inspection, Product, Review


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


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'product_id', 'name', 'description']


class ReviewSerializer(serializers.ModelSerializer):
    reviewer = serializers.CharField(source='reviewer.username', read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'reviewed_class', 'reviewer', 'comment', 'reviewed_at']
        read_only_fields = fields


class InspectionSerializer(BatchItemSerializer):
    """Full inspection record: the original model output plus any separate review."""

    product = serializers.CharField(source='product.product_id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    submitted_by = serializers.CharField(source='submitted_by.username', read_only=True)
    review = serializers.SerializerMethodField()
    review_status = serializers.SerializerMethodField()

    class Meta(BatchItemSerializer.Meta):
        fields = BatchItemSerializer.Meta.fields + [
            'product', 'product_name', 'batch', 'submitted_by', 'created_at', 'review', 'review_status',
        ]
        read_only_fields = fields

    def _review(self, item):
        return getattr(item, 'review', None)

    def get_review(self, item):
        review = self._review(item)
        return ReviewSerializer(review).data if review else None

    def get_review_status(self, item):
        review = self._review(item)
        if review is None:
            return 'pending' if item.status == Inspection.Status.COMPLETED else 'not_reviewable'
        return 'confirmed' if review.reviewed_class == item.predicted_class else 'corrected'


class ReviewCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ['reviewed_class', 'comment']

    def validate(self, attrs):
        inspection = self.context['inspection']
        if inspection.status != Inspection.Status.COMPLETED:
            raise serializers.ValidationError('Only completed inspections can be reviewed.')
        if Review.objects.filter(inspection=inspection).exists():
            raise serializers.ValidationError('This inspection has already been reviewed.')
        return attrs
