"""Stable, content-free renderer failures for export orchestration."""

from __future__ import annotations

from typing import Literal

PdfFailureCode = Literal[
    "invalid_snapshot", "render_failed", "artifact_validation_failed", "renderer_timeout"
]

_MESSAGES: dict[PdfFailureCode, str] = {
    "invalid_snapshot": "The saved report version cannot be rendered.",
    "render_failed": "The report PDF could not be rendered.",
    "artifact_validation_failed": "The generated PDF is invalid.",
    "renderer_timeout": "The report PDF timed out.",
}


class PdfRenderFailure(Exception):
    def __init__(self, code: PdfFailureCode) -> None:
        self.code = code
        super().__init__(_MESSAGES[code])
