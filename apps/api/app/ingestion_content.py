from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from os import environ
from pathlib import Path

from app.pdf import MAX_PDF_BYTES
from app.storage import ObjectStorage

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSIONS = 384
MAX_PAGES = 500
MAX_CHUNKS = 2_000
CHUNK_LENGTH = 800
CHUNK_OVERLAP = 120


class IngestionError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TextChunk:
    page_number: int
    content: str


def chunk_page(text: str, page_number: int) -> list[TextChunk]:
    normalized = " ".join(text.replace("\x00", "").split())
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + CHUNK_LENGTH, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", end - CHUNK_OVERLAP, end)
            if boundary != -1:
                end = boundary
        chunks.append(TextChunk(page_number, normalized[start:end].strip()))
        if end == len(normalized):
            break
        target = end - CHUNK_OVERLAP
        boundary = normalized.find(" ", target, end)
        start = boundary + 1 if boundary != -1 else target
    return chunks


def extract_pdf(data: bytes) -> tuple[int, list[TextChunk]]:
    import pymupdf

    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise IngestionError("ENCRYPTED_PDF")
            page_count = len(pdf)
            if page_count > MAX_PAGES:
                raise IngestionError("PDF_PAGE_LIMIT")
            chunks: list[TextChunk] = []
            for page_number, page in enumerate(pdf, start=1):
                chunks.extend(chunk_page(page.get_text(sort=True), page_number))
                if len(chunks) > MAX_CHUNKS:
                    raise IngestionError("PDF_TEXT_LIMIT")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise IngestionError("INVALID_PDF") from exc

    if not chunks:
        raise IngestionError("NO_EXTRACTABLE_TEXT")
    return page_count, chunks


def load_pdf(storage: ObjectStorage, key: str, checksum: str) -> bytes:
    with storage.open(key) as stream:
        data = stream.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES or sha256(data).hexdigest() != checksum:
        raise IngestionError("PDF_INTEGRITY_ERROR")
    return data


@lru_cache
def embedding_model():
    from fastembed import TextEmbedding

    cache = environ.get("DOCMIND_EMBEDDING_CACHE")
    if not cache:
        cache = str(Path(__file__).resolve().parents[3] / ".docmind-data" / "models")
    return TextEmbedding(
        model_name=MODEL_NAME,
        cache_dir=cache,
        threads=2,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in embedding_model().embed(texts, batch_size=32)]


def validate_vectors(vectors: list[list[float]], count: int) -> None:
    if len(vectors) != count or any(
        len(vector) != DIMENSIONS or not all(map(isfinite, vector)) or not any(vector)
        for vector in vectors
    ):
        raise ValueError("The embedding model returned invalid vectors")
