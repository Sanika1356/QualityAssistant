"""Opens a mapped SOP PDF for signed-in users. Used by source_url with #page=N."""
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from . import sop_loader


@require_GET
@login_required
def sop_pdf(request, document_id, revision):
    # Only a file named in the mapping for this exact document and revision is served.
    try:
        rows = sop_loader.load_mapping()
    except sop_loader.MissingEvidence:
        raise Http404('The SOP mapping is not available.')
    row = next(
        (r for r in rows if r['document_id'] == document_id and r['revision'] == revision), None
    )
    if row is None:
        raise Http404('This SOP is not in the mapping.')

    path = sop_loader.sop_dir() / sop_loader.Path(row['pdf_filename']).name
    if not path.is_file():
        raise Http404('The SOP PDF is not available.')
    return FileResponse(path.open('rb'), content_type='application/pdf', filename=path.name)
