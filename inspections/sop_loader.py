"""
Reads the SOP PDFs that pack_data/product_sop_mapping.csv maps to a product.

Working version for testing. Person 2 owns this file and may replace it, as
long as get_sop_chunks(product_id) and MissingEvidence keep the same shape.

Every problem raises MissingEvidence with a reason a user can read. Reasons
name the document ID or file name only, never a server path.
"""
import csv
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

# Pages are cut into passages of about this many characters so each citation
# points at a short, specific piece of text.
PASSAGE_CHARS = 700


class MissingEvidence(Exception):
    """A mapping row, SOP PDF or its text is missing or unreadable."""


@dataclass(frozen=True)
class SopChunk:
    product_id: str
    document_id: str
    revision: str
    pdf_filename: str
    page_number: int  # one-based, as shown in a PDF viewer
    text: str


def pack_dir():
    return Path(getattr(settings, 'SOP_PACK_DIR', settings.BASE_DIR / 'pack_data'))


def mapping_path():
    return pack_dir() / 'product_sop_mapping.csv'


def sop_dir():
    return pack_dir() / 'SOPs'


def clean_text(text):
    """Turn odd spaces and PDF bullet symbols into plain spaces."""
    text = re.sub(r'[    •]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def load_mapping():
    """Return every mapping row as a dict. Raises MissingEvidence if unreadable."""
    path = mapping_path()
    if not path.is_file():
        raise MissingEvidence('The product to SOP mapping file is missing.')
    try:
        with path.open(newline='', encoding='utf-8-sig') as handle:
            rows = [
                {key.strip(): (value or '').strip() for key, value in row.items() if key}
                for row in csv.DictReader(handle)
            ]
    except (OSError, UnicodeDecodeError, csv.Error):
        raise MissingEvidence('The product to SOP mapping file could not be read.')

    needed = {'product_id', 'document_id', 'revision', 'pdf_filename'}
    if not rows or not needed.issubset(rows[0]):
        raise MissingEvidence('The product to SOP mapping file has no usable rows.')
    return rows


def mapped_documents(product_id):
    """The mapping rows for this exact product ID. Raises MissingEvidence if none."""
    rows = [row for row in load_mapping() if row['product_id'] == product_id]
    if not rows:
        raise MissingEvidence(f'No SOP is mapped to product {product_id}.')
    for row in rows:
        if not (row['document_id'] and row['revision'] and row['pdf_filename']):
            raise MissingEvidence(f'The SOP mapping for product {product_id} is incomplete.')
    return rows


def _split_page(text):
    """Cut one page of text into passages at sentence ends."""
    sentences = re.split(r'(?<=[.:])\s+', text)
    passages, current = [], ''
    for sentence in sentences:
        if current and len(current) + len(sentence) > PASSAGE_CHARS:
            passages.append(current)
            current = sentence
        else:
            current = f'{current} {sentence}'.strip()
    if current:
        passages.append(current)
    return passages


def _read_pdf(row):
    """Return (page_number, text) for each page. Checks the PDF matches the mapping."""
    try:
        import pymupdf
    except ImportError:
        raise MissingEvidence('The PDF reader (PyMuPDF) is not installed on this server.')

    name = Path(row['pdf_filename']).name  # never follow a path out of the SOP folder
    path = sop_dir() / name
    label = f"{row['document_id']} revision {row['revision']}"
    if not path.is_file():
        raise MissingEvidence(f'The SOP PDF for {label} ({name}) is missing.')

    try:
        with pymupdf.open(path) as document:
            pages = [(number, clean_text(page.get_text())) for number, page in enumerate(document, start=1)]
    except Exception:
        raise MissingEvidence(f'The SOP PDF for {label} ({name}) could not be read.')

    if not any(text for _, text in pages):
        raise MissingEvidence(f'The SOP PDF for {label} ({name}) has no readable text.')

    # The first page states the document ID and revision. A different PDF or
    # revision under the mapped file name must not be used as evidence.
    first = pages[0][1]
    found_id = re.search(r'Document ID:\s*([A-Z0-9-]+)', first)
    found_revision = re.search(r'Revision:\s*([0-9.]+)', first)
    if not found_id or found_id.group(1) != row['document_id']:
        raise MissingEvidence(f'The SOP PDF {name} does not contain document {row["document_id"]}.')
    if not found_revision or found_revision.group(1).rstrip('.') != row['revision']:
        raise MissingEvidence(
            f'The SOP PDF {name} is not revision {row["revision"]} of {row["document_id"]}.'
        )
    return pages


def get_sop_chunks(product_id):
    """Return the passages of every SOP mapped to this product, page by page."""
    chunks = []
    for row in mapped_documents(product_id):
        for page_number, text in _read_pdf(row):
            for passage in _split_page(text):
                chunks.append(
                    SopChunk(
                        product_id=product_id,
                        document_id=row['document_id'],
                        revision=row['revision'],
                        pdf_filename=Path(row['pdf_filename']).name,
                        page_number=page_number,
                        text=passage,
                    )
                )
    return chunks
