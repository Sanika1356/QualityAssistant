from django.urls import reverse
from rest_framework import serializers

from .models import Batch, Incident, Inspection, Product, Review


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



# Round 3: Incident serializers

class IncidentSerializer(serializers.ModelSerializer):
    inspection_id = serializers.IntegerField(read_only=True)
    created_by = serializers.CharField(source='created_by.username', read_only=True)
    reviewer = serializers.CharField(
        source='reviewer.username',
        read_only=True,
        allow_null=True
    )

    human_correction = serializers.SerializerMethodField()

    # Short display number (INC-<number>); incident_id stays the real identifier.
    incident_number = serializers.IntegerField(source='pk', read_only=True)
    incident_code = serializers.SerializerMethodField()

    def get_incident_code(self, incident):
        return f'INC-{incident.pk}'

    # The saved Round 2 inspection the incident came from.
    inspection_image_url = serializers.SerializerMethodField()
    inspection_original_filename = serializers.CharField(
        source='inspection.original_filename', read_only=True
    )
    inspection_inspected_at = serializers.DateTimeField(source='inspection.created_at', read_only=True)
    inspection_submitted_by = serializers.CharField(
        source='inspection.submitted_by.username', read_only=True
    )

    def get_inspection_image_url(self, incident):
        # Same access-checked endpoint as Round 2, never the raw media file.
        return BatchItemSerializer(context=self.context).get_image_url(incident.inspection)

    def get_human_correction(self, incident):
        # Shown apart from the classifier's original result; it never changes it.
        from .sop_assistant import build_human_correction

        return build_human_correction(incident.inspection)

    class Meta:
        model = Incident
        fields = [
            'incident_id',
            'incident_number',
            'incident_code',
            'inspection_id',
            'inspection_image_url',
            'inspection_original_filename',
            'inspection_inspected_at',
            'inspection_submitted_by',
            'product_id_snapshot',
            'product_name_snapshot',
            'original_prediction',
            'human_correction',
            'original_confidence',
            'original_defect_probability',
            'model_version_snapshot',
            'summary',
            'actions',
            'sources',
            'evidence_status',
            'evidence_reason',
            'manual_review_required',
            'created_by',
            'created_at',
            'updated_at',
            'decision',
            'reviewer',
            'review_comment',
            'reviewed_at',
        ]
        read_only_fields = fields


class IncidentCreateSerializer(serializers.Serializer):
    inspection_id = serializers.IntegerField(min_value=1)


class IncidentDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[
            Incident.Decision.APPROVED,
            Incident.Decision.NEEDS_MORE_INFO,
        ]
    )
    review_comment = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True
    )

    def validate(self, attrs):
        incident = self.context['incident']

        if (
            attrs['decision'] == Incident.Decision.APPROVED
            and incident.evidence_status != Incident.EvidenceStatus.SUFFICIENT
        ):
            raise serializers.ValidationError({
                'decision': 'An incident with insufficient evidence cannot be approved.'
            })

        if incident.decision != Incident.Decision.PENDING:
            raise serializers.ValidationError(
                'This incident has already received a decision.'
            )

        return attrs
