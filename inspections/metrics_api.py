"""GET /api/metrics/: the saved result of `python manage.py evaluate_samples`. Never computed or invented here."""
import json
from pathlib import Path

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import HasAnyRole

RUN_COMMAND = 'python manage.py evaluate_samples'


def metrics_path():
    return Path(getattr(settings, 'METRICS_REPORT_JSON', Path(settings.BASE_DIR) / 'metrics_report.json'))


class MetricsView(APIView):
    permission_classes = [HasAnyRole]

    def get(self, request):
        path = metrics_path()
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return Response(
                {'detail': f'No metrics report yet. Run "{RUN_COMMAND}" on the server, then reload.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (OSError, ValueError):
            return Response(
                {'detail': f'The metrics report could not be read. Run "{RUN_COMMAND}" again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(data)
