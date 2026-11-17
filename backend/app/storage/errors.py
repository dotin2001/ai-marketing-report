"""Stable, sanitized storage failure categories."""

from __future__ import annotations

from enum import StrEnum


class StorageErrorCode(StrEnum):
    TIMEOUT = "storage_timeout"
    UNAVAILABLE = "storage_unavailable"
    FORBIDDEN = "storage_forbidden"
    COLLISION = "object_collision"
    INTEGRITY_FAILED = "integrity_failed"


class StorageError(RuntimeError):
    """An internal storage error whose text is always safe to expose internally."""

    def __init__(self, code: StorageErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ContentRejected(ValueError):
    """Prepared content violated a local, pre-provider contract."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
