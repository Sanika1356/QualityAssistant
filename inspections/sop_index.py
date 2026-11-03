"""
Scores SOP passages against a query, using an index of passage vectors.

The index only stores vectors for passages of mapped SOPs, keyed by product,
document ID, revision, page and text. The passage text itself always comes
fresh from sop_loader, so a stale index can never add text that is not in the
current mapped PDFs; it only saves recomputing vectors.

Embedding backends (SOP_EMBEDDING_BACKEND), as in Round 1:
  auto                   sentence-transformers if installed, else hash
  sentence-transformers  the real model, runs locally
  hash                   a tiny offline stand-in based on shared words
"""
import hashlib
import json
import math
import re
from pathlib import Path

from django.conf import settings

from . import sop_loader

_HASH_SIZE = 768
_SKIPPED_WORDS = frozenset(
    'a an and are as at be by can do does for from how i in is it of on or '
    'should that the this to was what when where which who why will with you '
    'your my our we not no any'.split()
)
_loaded_models = {}


def index_path():
    return Path(getattr(settings, 'SOP_INDEX_PATH', settings.BASE_DIR / 'sop_index' / 'sop_index.json'))


def backend():
    chosen = getattr(settings, 'SOP_EMBEDDING_BACKEND', 'auto')
    if chosen != 'auto':
        return chosen
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return 'hash'
    return 'sentence-transformers'


def _hash_embed(text):
    vector = [0.0] * _HASH_SIZE
    for word in re.findall(r'[a-z0-9]+', text.lower()):
        if word in _SKIPPED_WORDS:
            continue
        digest = hashlib.md5(word.encode()).digest()
        vector[int.from_bytes(digest[:4], 'big') % _HASH_SIZE] += 1.0
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector] if length else vector


def embed_texts(texts, name):
    if not texts:
        return []
    if name == 'hash':
        return [_hash_embed(text) for text in texts]
    if name == 'sentence-transformers':
        model_name = getattr(settings, 'SOP_EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
        if model_name not in _loaded_models:
            from sentence_transformers import SentenceTransformer
            _loaded_models[model_name] = SentenceTransformer(model_name)
        vectors = _loaded_models[model_name].encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return [vector.tolist() for vector in vectors]
    raise ValueError(f'Unknown SOP_EMBEDDING_BACKEND: {name!r}')


def _key(chunk):
    return '|'.join([chunk.product_id, chunk.document_id, chunk.revision, str(chunk.page_number), chunk.text])


def _load_index(name):
    try:
        data = json.loads(index_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    if data.get('backend') != name:
        return {}
    return data.get('vectors', {})


def build_index():
    """Index every product in the mapping. Returns (products indexed, passages, problems)."""
    name = backend()
    vectors, problems, products = {}, [], 0
    for product_id in sorted({row['product_id'] for row in sop_loader.load_mapping()}):
        try:
            chunks = sop_loader.get_sop_chunks(product_id)
        except sop_loader.MissingEvidence as error:
            problems.append(f'{product_id}: {error}')
            continue
        products += 1
        for chunk, vector in zip(chunks, embed_texts([c.text for c in chunks], name)):
            vectors[_key(chunk)] = vector

    path = index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'backend': name, 'vectors': vectors}), encoding='utf-8')
    return products, len(vectors), problems


def score_chunks(chunks, query):
    """Return [(score, chunk)] best first. Cosine similarity; higher is closer."""
    name = backend()
    stored = _load_index(name)
    missing = [chunk for chunk in chunks if _key(chunk) not in stored]
    for chunk, vector in zip(missing, embed_texts([c.text for c in missing], name)):
        stored[_key(chunk)] = vector

    query_vector = embed_texts([query], name)[0]
    scored = [
        (round(sum(a * b for a, b in zip(query_vector, stored[_key(chunk)])), 4), chunk)
        for chunk in chunks
    ]
    return sorted(scored, key=lambda pair: pair[0], reverse=True)
