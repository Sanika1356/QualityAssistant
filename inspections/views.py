import logging

from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from PIL import Image, UnidentifiedImageError
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

        batch = batch_queryset().get(pk=batch.pk)
        data = BatchSerializer(batch, context={'request': request}).data
        return Response(data, status=status.HTTP_201_CREATED)


class BatchDetailView(APIView):
    permission_classes = [IsEngineerOrSupervisor]

    def get(self, request, pk):
        batches = batch_queryset()
        if not in_group(request.user, SUPERVISOR):
            batches = batches.filter(submitted_by=request.user)
        batch = get_object_or_404(batches, pk=pk)
        return Response(BatchSerializer(batch, context={'request': request}).data)


IMAGE_CONTENT_TYPES = {'JPEG': 'image/jpeg', 'PNG': 'image/png'}


class InspectionImageView(APIView):
    """Stream a saved inspection image to its owner or a Supervisor. Media is never public."""

    permission_classes = [IsEngineerOrSupervisor]

    def get(self, request, pk):
        inspections = Inspection.objects.all()
        if not in_group(request.user, SUPERVISOR):
            inspections = inspections.filter(submitted_by=request.user)
        inspection = get_object_or_404(inspections, pk=pk)
        if not inspection.image:
            raise Http404('This inspection has no saved image.')

        try:
            # Storage.open keeps the path inside MEDIA_ROOT.
            file = inspection.image.storage.open(inspection.image.name, 'rb')
        except (FileNotFoundError, SuspiciousFileOperation):
            logger.warning('Image file missing for inspection %s', pk)
            raise Http404('Image file is not available.')

        # Content type comes from the bytes, not from the stored name.
        try:
            with Image.open(file) as image:
                content_type = IMAGE_CONTENT_TYPES.get(image.format)
        except (UnidentifiedImageError, OSError):
            content_type = None
        if content_type is None:
            file.close()
            raise Http404('Image file is not available.')
        file.seek(0)

        response = FileResponse(file, content_type=content_type)
        response['Content-Disposition'] = 'inline'
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
