"""Bounded, network-isolated Playwright rendering of saved report versions."""

from __future__ import annotations

import asyncio
from io import BytesIO

from playwright.async_api import Route, async_playwright
from pypdf import PdfReader

from app.core.config import Settings
from app.pdf.errors import PdfRenderFailure
from app.pdf.html import render_report_html
from app.pdf.version import SavedVersion


def validate_pdf_bytes(data: bytes, max_bytes: int) -> bytes:
    if not data or len(data) > max_bytes or not data.startswith(b"%PDF-"):
        raise PdfRenderFailure("artifact_validation_failed")
    try:
        document = PdfReader(BytesIO(data), strict=True)
        if len(document.pages) < 1:
            raise ValueError
        for page in document.pages:
            if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                raise ValueError
    except Exception:
        raise PdfRenderFailure("artifact_validation_failed") from None
    return data


class PdfRenderer:
    def __init__(self, settings: Settings) -> None:
        self.timeout_seconds = settings.pdf_render_timeout_seconds
        self.max_bytes = settings.generated_pdf_max_bytes
        self.browser_executable_path = settings.pdf_browser_executable_path

    async def _render_html(self, html: str) -> bytes:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                executable_path=self.browser_executable_path,
                args=["--disable-background-networking", "--no-first-run"],
            )
            try:
                context = await browser.new_context(
                    java_script_enabled=False,
                    service_workers="block",
                    offline=True,
                    accept_downloads=False,
                )
                try:

                    async def block_request(route: Route) -> None:
                        await route.abort()

                    await context.route("**/*", block_request)
                    page = await context.new_page()
                    await page.set_content(
                        html, wait_until="load", timeout=int(self.timeout_seconds * 1000)
                    )
                    await page.evaluate("() => document.fonts.ready.then(() => true)")
                    return await page.pdf(
                        format="A4",
                        prefer_css_page_size=True,
                        print_background=True,
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    )
                finally:
                    await context.close()
            finally:
                await browser.close()

    async def render(self, version: SavedVersion) -> bytes:
        try:
            html = render_report_html(version)
            async with asyncio.timeout(self.timeout_seconds):
                data = await self._render_html(html)
            return validate_pdf_bytes(data, self.max_bytes)
        except PdfRenderFailure:
            raise
        except TimeoutError:
            raise PdfRenderFailure("renderer_timeout") from None
        except Exception:
            raise PdfRenderFailure("render_failed") from None
