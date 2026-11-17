"""Allow-listed storage instrumentation with no provider or object identity fields."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.storage.errors import StorageError
from app.storage.types import StoragePurpose

logger = logging.getLogger("app.storage")


def elapsed_bucket(seconds: float) -> str:
    if seconds < 0.1:
        return "lt_100ms"
    if seconds < 1:
        return "lt_1s"
    if seconds < 10:
        return "lt_10s"
    return "gte_10s"


@contextmanager
def instrument_storage(
    *, operation: str, purpose: StoragePurpose, correlation_id: str
) -> Iterator[None]:
    started = time.monotonic()
    outcome = "succeeded"
    try:
        yield
    except StorageError as exc:
        outcome = exc.code.value
        raise
    except BaseException:
        outcome = "storage_unavailable"
        raise
    finally:
        logger.info(
            "storage correlation_id=%s operation=%s purpose=%s outcome=%s elapsed=%s",
            correlation_id,
            operation,
            purpose.value,
            outcome,
            elapsed_bucket(time.monotonic() - started),
        )
