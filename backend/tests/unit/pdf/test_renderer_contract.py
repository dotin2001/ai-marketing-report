from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from dotenv import dotenv_values
from pydantic import ValidationError
from pypdf import PdfWriter

from app.core.config import Settings
from app.pdf.errors import PdfRenderFailure
from app.pdf.renderer import PdfRenderer, validate_pdf_bytes
from app.pdf.version import SavedVersion


def test_example_renderer_settings_and_bounds(valid_settings_data: dict[str, Any]) -> None:
    example = dotenv_values(".env.example")
    merged = {**example, **valid_settings_data}
    merged.pop("TEST_DATABASE_URL", None)
    merged.pop("MIGRATION_DATABASE_URL", None)
    settings = Settings.model_validate(merged)
    assert settings.pdf_render_timeout_seconds == 30
    assert settings.pdf_browser_executable_path is None
    for value in (0, -1, 121):
        with pytest.raises(ValidationError):
            Settings.model_validate({**merged, "PDF_RENDER_TIMEOUT_SECONDS": value})
    with pytest.raises(ValidationError):
        Settings.model_validate({**merged, "PDF_BROWSER_EXECUTABLE_PATH": "relative/browser"})


def _valid_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_artifact_signature_parse_and_size() -> None:
    valid = _valid_pdf()
    assert validate_pdf_bytes(valid, len(valid)) == valid
    for invalid, max_bytes in (
        (b"", 1000),
        (b"not a pdf", 1000),
        (b"%PDF-1.7\ntruncated", 1000),
        (valid, len(valid) - 1),
    ):
        with pytest.raises(PdfRenderFailure) as error:
            validate_pdf_bytes(invalid, max_bytes)
        assert error.value.code == "artifact_validation_failed"


@pytest.mark.asyncio
async def test_renderer_sanitizes_launch_timeout_and_invalid_output(
    settings: Settings,
    version_factory: Callable[..., SavedVersion],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    renderer = PdfRenderer(settings)
    version = version_factory()

    async def launch_failure(**_kwargs: object) -> object:
        raise RuntimeError("customer text and secret provider details")

    class FailingPlaywright:
        async def __aenter__(self) -> object:
            return SimpleNamespace(chromium=SimpleNamespace(launch=launch_failure))

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("app.pdf.renderer.async_playwright", FailingPlaywright)
    with pytest.raises(PdfRenderFailure) as error:
        await renderer.render(version)
    assert error.value.code == "render_failed"
    assert "customer" not in str(error.value)
    assert "customer text" not in caplog.text

    async def invalid_output(_html: str) -> bytes:
        return b"%PDF-1.7\ntruncated"

    monkeypatch.setattr(renderer, "_render_html", invalid_output)
    with pytest.raises(PdfRenderFailure) as error:
        await renderer.render(version)
    assert error.value.code == "artifact_validation_failed"

    async def slow(_html: str) -> bytes:
        import asyncio

        await asyncio.sleep(0.02)
        return _valid_pdf()

    renderer.timeout_seconds = 0.001
    monkeypatch.setattr(renderer, "_render_html", slow)
    with pytest.raises(PdfRenderFailure) as error:
        await renderer.render(version)
    assert error.value.code == "renderer_timeout"
