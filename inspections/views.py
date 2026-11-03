import logging

from django.core.exceptions import SuspiciousFileOperation
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from PIL import Image, UnidentifiedImageError
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Batch, Inspection, Product
from .permissions import (
    SUPERVISOR,
    IsAdministratorOrReadOnly,
    IsEngineer,
    IsEngineerOrSupervisor,
    IsEngineerSubmitter,
    IsSupervisor,
    in_group,
)
from .serializers import (
    BatchSerializer,
    InspectionSerializer,
    ProductSerializer,
    ReviewCreateSerializer,
)
from .tasks import process_inspection
from .validators import validate_image

logger = logging.getLogger(__name__)

MAX_BATCH_FILES = 10


QUEUE_UNAVAILABLE = 'Could not queue this image for processing (task queue unavailable).'


def queue_inspection(inspection_id):
    """Queue one item. Returns False (and marks the item failed) if the task queue is unavailable."""
    try:
        process_inspection.delay(inspection_id)
        return True
    except Exception:
        # Broker down: say so on the item instead of leaving it queued forever.
        logger.exception('Could not queue inspection %s', inspection_id)
        Inspection.objects.filter(pk=inspection_id, status=Inspection.Status.QUEUED).update(
            status=Inspection.Status.FAILED, failure_reason=QUEUE_UNAVAILABLE,
        )
        return False


def queue_batch(inspection_ids):
    # After the first failure the queue is down: fail the rest at once instead of waiting on each.
    for index, inspection_id in enumerate(inspection_ids):
        if not queue_inspection(inspection_id):
            Inspection.objects.filter(
                pk__in=inspection_ids[index + 1:], status=Inspection.Status.QUEUED
            ).update(status=Inspection.Status.FAILED, failure_reason=QUEUE_UNAVAILABLE)
            return


def batch_queryset():
    return Batch.objects.select_related('product', 'submitted_by').prefetch_related('items')


def find_product(product_ref):
    """Look a product up by its product_id (e.g. P-PLATE01), or by numeric pk as a fallback."""
    product = Product.objects.filter(product_id=product_ref).first()
    if product is None and product_ref.isdigit():
        product = Product.objects.filter(pk=int(product_ref)).first()
    return product


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
        product = find_product(product_ref)
        if product is None:
            return Response(
                {'detail': f'Unknown product "{product_ref}".'}, status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            batch = Batch.objects.create(product=product, submitted_by=request.user)
            to_queue = []
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
                    to_queue.append(item.pk)
            transaction.on_commit(lambda ids=tuple(to_queue): queue_batch(ids))

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


class ProductListCreateAPIView(generics.ListCreateAPIView):
    queryset = Product.objects.all().order_by('product_id')
    serializer_class = ProductSerializer
    permission_classes = [IsAdministratorOrReadOnly]


def visible_inspections(user):
    """Supervisors see every inspection. Engineers see only their own."""
    inspections = Inspection.objects.select_related(
        'product', 'batch', 'submitted_by', 'review', 'review__reviewer'
    )
    if in_group(user, SUPERVISOR):
        return inspections
    return inspections.filter(submitted_by=user)


class InspectionListAPIView(generics.ListAPIView):
    """GET: history, filtered with ?prediction= and ?review_status=.
    POST: inspect one image now, in this request (validate-then-predict flow by Person 2).
    """

    serializer_class = InspectionSerializer
    permission_classes = [IsEngineerOrSupervisor]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsEngineerSubmitter()]
        return super().get_permissions()

    def post(self, request):
        files = request.FILES.getlist('file')
        if len(files) != 1:
            message = 'Attach one image in the "file" field.' if not files else (
                f'Send exactly one image in the "file" field; got {len(files)}. Use /api/batches/ for more.'
            )
            return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)
        upload = files[0]

        product_ref = str(request.data.get('product') or '').strip()
        if not product_ref:
            return Response(
                {'detail': 'Choose a product, for example P-PLATE01.'}, status=status.HTTP_400_BAD_REQUEST
            )
        product = find_product(product_ref)
        if product is None:
            return Response(
                {'detail': f'Unknown product "{product_ref}".'}, status=status.HTTP_400_BAD_REQUEST
            )

        # Check the bytes first: an invalid upload is never stored and never reaches the model.
        reason = validate_image(upload)
        if reason:
            return Response({'detail': reason}, status=status.HTTP_400_BAD_REQUEST)

        item = Inspection(
            product=product,
            original_filename=upload.name[:255],
            submitted_by=request.user,
            status=Inspection.Status.QUEUED,
        )
        item.image.save(upload.name, upload, save=False)
        item.save()

        # Same predict-and-save code the batch worker uses, called directly: no Celery, no Redis.
        process_inspection(item.pk)

        item = visible_inspections(request.user).get(pk=item.pk)
        if item.status != Inspection.Status.COMPLETED:
            return Response(
                {'detail': f'{item.failure_reason} The upload was saved as failed inspection {item.pk}.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        data = InspectionSerializer(item, context={'request': request}).data
        return Response(data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        inspections = visible_inspections(self.request.user).order_by('-created_at', '-id')

        prediction = self.request.query_params.get('prediction')
        if prediction in Inspection.PredictedClass.values:
            inspections = inspections.filter(predicted_class=prediction)

        review_status = self.request.query_params.get('review_status')
        if review_status == 'pending':
            # A failed upload has no prediction, so there is nothing to review.
            inspections = inspections.filter(status=Inspection.Status.COMPLETED, review__isnull=True)
        elif review_status == 'confirmed':
            inspections = inspections.filter(review__reviewed_class=F('predicted_class'))
        elif review_status == 'corrected':
            inspections = inspections.filter(review__isnull=False).exclude(
                review__reviewed_class=F('predicted_class')
            )
        return inspections


class InspectionDetailAPIView(generics.RetrieveAPIView):
    serializer_class = InspectionSerializer
    permission_classes = [IsEngineerOrSupervisor]

    def get_queryset(self):
        return visible_inspections(self.request.user)


class InspectionReviewAPIView(APIView):
    """Supervisors confirm or correct a completed inspection. The original output is never edited."""

    permission_classes = [IsSupervisor]

    def post(self, request, pk):
        inspection = get_object_or_404(Inspection, pk=pk)
        serializer = ReviewCreateSerializer(data=request.data, context={'inspection': inspection})
        serializer.is_valid(raise_exception=True)
        serializer.save(inspection=inspection, reviewer=request.user)
        fresh = visible_inspections(request.user).get(pk=pk)
        return Response(
            InspectionSerializer(fresh, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )
