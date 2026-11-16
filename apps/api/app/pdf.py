from hashlib import sha256
from typing import BinaryIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.errors import APIError

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_PDF_BYTES + 64 * 1024
CHUNK_BYTES = 64 * 1024


def too_large() -> APIError:
    return APIError(413, "PDF_TOO_LARGE", "PDF files are limited to 20 MiB.")


def pdf_metadata(stream: BinaryIO) -> tuple[int, str]:
    if not stream.read(8).startswith(b"%PDF-"):
        raise APIError(400, "INVALID_PDF", "A valid PDF file is required.")

    stream.seek(0)
    size = 0
    digest = sha256()
    while chunk := stream.read(CHUNK_BYTES):
        size += len(chunk)
        if size > MAX_PDF_BYTES:
            raise too_large()
        digest.update(chunk)

    try:
        stream.seek(0)
        reader = PdfReader(stream, strict=True)
        if reader.is_encrypted:
            raise APIError(
                400, "ENCRYPTED_PDF", "Password-protected PDFs are not supported."
            )
        # Check the document catalog without extracting or rendering page contents.
        if reader.root_object["/Pages"]["/Count"] < 1:
            raise PdfReadError("Missing or empty page tree")
    except (PdfReadError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise APIError(400, "INVALID_PDF", "A valid PDF file is required.") from exc

    stream.seek(0)
    return size, digest.hexdigest()
