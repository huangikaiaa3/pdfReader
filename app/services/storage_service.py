"""Document storage abstraction for local and future object-backed storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings


@dataclass(frozen=True)
class StorageObject:
    """Opaque storage metadata persisted in the database."""

    uri: str
    backend: str
    key: str


class BaseDocumentStorage:
    """Common interface for document storage backends."""

    backend_name: str

    def store_pdf(self, document_version_id, file_bytes: bytes) -> StorageObject:
        """Persist one uploaded PDF and return its storage metadata."""

        raise NotImplementedError

    def read_pdf_bytes(self, storage_uri: str) -> bytes:
        """Read one stored PDF by its opaque storage URI."""

        raise NotImplementedError

    def delete_pdf(self, storage_uri: str) -> None:
        """Delete one stored PDF by its opaque storage URI."""

        raise NotImplementedError

    def exists(self, storage_uri: str) -> bool:
        """Return whether one stored PDF is currently available."""

        raise NotImplementedError


class LocalDocumentStorage(BaseDocumentStorage):
    """Filesystem-backed storage for development and simple deployments."""

    backend_name = "local"

    def store_pdf(self, document_version_id, file_bytes: bytes) -> StorageObject:
        settings = get_settings()
        key = f"{settings.storage_key_prefix}/{document_version_id}.pdf"
        full_path = Path(settings.storage_root) / key
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(file_bytes)
        return StorageObject(uri=f"local://{key}", backend=self.backend_name, key=key)

    def read_pdf_bytes(self, storage_uri: str) -> bytes:
        parsed = urlparse(storage_uri)
        key = _parse_storage_key(parsed, expected_scheme="local")
        full_path = Path(get_settings().storage_root) / key
        return full_path.read_bytes()

    def delete_pdf(self, storage_uri: str) -> None:
        parsed = urlparse(storage_uri)
        key = _parse_storage_key(parsed, expected_scheme="local")
        full_path = Path(get_settings().storage_root) / key
        if full_path.exists():
            full_path.unlink()

    def exists(self, storage_uri: str) -> bool:
        parsed = urlparse(storage_uri)
        key = _parse_storage_key(parsed, expected_scheme="local")
        return (Path(get_settings().storage_root) / key).exists()


class S3DocumentStorage(BaseDocumentStorage):
    """Object-storage-oriented URI formatter for future S3-compatible storage."""

    backend_name = "s3"

    def store_pdf(self, document_version_id, file_bytes: bytes) -> StorageObject:
        settings = get_settings()
        key = f"{settings.storage_key_prefix}/{document_version_id}.pdf"
        return StorageObject(uri=f"s3://{settings.storage_bucket}/{key}", backend=self.backend_name, key=key)

    def read_pdf_bytes(self, storage_uri: str) -> bytes:
        raise NotImplementedError("S3 document reads are not implemented yet.")

    def delete_pdf(self, storage_uri: str) -> None:
        raise NotImplementedError("S3 document deletion is not implemented yet.")

    def exists(self, storage_uri: str) -> bool:
        raise NotImplementedError("S3 document existence checks are not implemented yet.")


def get_document_storage() -> BaseDocumentStorage:
    """Return the configured document storage backend."""

    settings = get_settings()
    if settings.storage_backend == "local":
        return LocalDocumentStorage()
    if settings.storage_backend == "s3":
        return S3DocumentStorage()
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")


def read_pdf_bytes(storage_uri: str) -> bytes:
    """Read one stored PDF via the backend encoded in its URI."""

    parsed = urlparse(storage_uri)
    if parsed.scheme == "local":
        return LocalDocumentStorage().read_pdf_bytes(storage_uri)
    if parsed.scheme == "s3":
        return S3DocumentStorage().read_pdf_bytes(storage_uri)
    raise ValueError(f"Unsupported storage URI scheme: {parsed.scheme}")


def delete_pdf(storage_uri: str) -> None:
    """Delete one stored PDF via the backend encoded in its URI."""

    parsed = urlparse(storage_uri)
    if parsed.scheme == "local":
        LocalDocumentStorage().delete_pdf(storage_uri)
        return
    if parsed.scheme == "s3":
        S3DocumentStorage().delete_pdf(storage_uri)
        return
    raise ValueError(f"Unsupported storage URI scheme: {parsed.scheme}")


def storage_exists(storage_uri: str) -> bool:
    """Return whether one stored PDF is available via its storage URI."""

    parsed = urlparse(storage_uri)
    if parsed.scheme == "local":
        return LocalDocumentStorage().exists(storage_uri)
    if parsed.scheme == "s3":
        return S3DocumentStorage().exists(storage_uri)
    return False


def _parse_storage_key(parsed_uri, expected_scheme: str) -> str:
    """Normalize a storage URI into the persisted object key."""

    if parsed_uri.scheme != expected_scheme:
        raise ValueError(f"Expected {expected_scheme} storage URI, got: {parsed_uri.scheme}")
    key = f"{parsed_uri.netloc}{parsed_uri.path}".lstrip("/")
    if not key:
        raise ValueError("Storage URI is missing an object key.")
    return key
