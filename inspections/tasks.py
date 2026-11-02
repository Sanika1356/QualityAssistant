import logging

from celery import shared_task

from .model.inference import predict
from .models import Inspection

logger = logging.getLogger(__name__)

Status = Inspection.Status


@shared_task
def process_inspection(inspection_id):
    """Run the frozen model on one queued inspection. Safe to run more than once."""
    # Claim the item atomically. Completed or failed items are never touched again.
    # 'processing' is allowed so a task redelivered after a worker crash can finish the job.
    claimed = Inspection.objects.filter(
        pk=inspection_id, status__in=[Status.QUEUED, Status.PROCESSING]
    ).update(status=Status.PROCESSING)
    if not claimed:
        logger.info('Inspection %s is missing or already finished; skipping.', inspection_id)
        return 'skipped'

    inspection = Inspection.objects.get(pk=inspection_id)
    try:
        result = predict(inspection.image.path)
    except Exception as exc:
        logger.exception('Inference failed for inspection %s', inspection_id)
        Inspection.objects.filter(pk=inspection_id, status=Status.PROCESSING).update(
            status=Status.FAILED,
            # Full details stay in the worker log; users get a short reason without server paths.
            failure_reason=f'Model could not process this image ({type(exc).__name__}).',
        )
        return 'failed'

    # Only a still-processing row is written, so a parallel duplicate run cannot overwrite it.
    Inspection.objects.filter(pk=inspection_id, status=Status.PROCESSING).update(
        status=Status.COMPLETED,
        failure_reason='',
        predicted_class=result['predicted_class'],
        confidence=result['confidence'],
        defect_probability=result['defect_probability'],
        model_version=result['model_version'],
    )
    return 'completed'
