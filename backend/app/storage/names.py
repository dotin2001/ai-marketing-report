"""Safe persisted and response filenames derived without storage identity data."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\:;\"']+")
_SPACES = re.compile(r"\s+")


def safe_filename(value: str, *, default_stem: str, extension: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _UNSAFE.sub("_", normalized)
    normalized = _SPACES.sub(" ", normalized).strip(" ._")
    if normalized.lower().endswith(extension.lower()):
        normalized = normalized[: -len(extension)].strip(" ._")
    stem = normalized or default_stem
    encoded = stem.encode("utf-8")
    while len(encoded) > 240:
        stem = stem[:-1]
        encoded = stem.encode("utf-8")
    return f"{stem}{extension}"


def attachment_content_disposition(filename: str) -> str:
    safe = safe_filename(filename, default_stem="report", extension=".pdf")
    ascii_name = safe.encode("ascii", "ignore").decode() or "report.pdf"
    ascii_name = _UNSAFE.sub("_", ascii_name)
    encoded = quote(safe, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
