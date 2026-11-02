import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Batch, Inspection, Product
from .permissions import SUPERVISOR, IsEngineer, IsEngineerOrSupervisor, in_group
from .serializers import BatchSerializer
from .tasks import process_inspection
from .validators import validate_image

logger = logging.getLogger(__name__)

MAX_BATCH_FILES = 10


def queue_inspection(inspection_id):
    try:
        process_inspection.delay(inspection_id)
    except Exception:
        # Broker down: say so on the item instead of leaving it queued forever.
        logger.exception('Could not queue inspection %s', inspection_id)
        Inspection.objects.filter(pk=inspection_id, status=Inspection.Status.QUEUED).update(
            status=Inspection.Status.FAILED,
            failure_reason='Could not queue this image for processing (task queue unavailable).',
        )


def batch_queryset():
    return Batch.objects.select_related('product', 'submitted_by').prefetch_related('items')


class BatchCreateView(APIView):
    permission_classes = [IsEngineer]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        files = request.FILES.getlist('files')
        if not 1 <= len(files) <= MAX_BATCH_FILES:
            return Response(
                {'detail': f'Send between 1 and {MAX_BATCH_FILES} files in the "files" field; got {len(files)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product_ref = str(request.data.get('product') or '').strip()
        product = Product.objects.filter(product_id=product_ref).first()
        if product is None and product_ref.isdigit():
            product = Product.objects.filter(pk=int(product_ref)).first()
        if product is None:
            return Response(
                {'detail': f'Unknown product "{product_ref}".'}, status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            batch = Batch.objects.create(product=product, submitted_by=request.user)
            for upload in files:
                reason = validate_image(upload)
                item = Inspection(
                    product=product,
                    batch=batch,
                    original_filename=upload.name[:255],
                    submitted_by=request.user,
                )
                if reason:
                    item.status = Inspection.Status.FAILED
                    item.failure_reason = reason
                else:
                    item.status = Inspection.Status.QUEUED
                    item.image.save(upload.name, upload, save=False)
                item.save()
                if not reason:
                    transaction.on_commit(lambda pk=item.pk: queue_inspection(pk))

        data = BatchSerializer(batch_queryset().get(pk=batch.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)


class BatchDetailView(APIView):
    permission_classes = [IsEngineerOrSupervisor]

    def get(self, request, pk):
        batches = batch_queryset()
        if not in_group(request.user, SUPERVISOR):
            batches = batches.filter(submitted_by=request.user)
        return Response(BatchSerializer(get_object_or_404(batches, pk=pk)).data)
