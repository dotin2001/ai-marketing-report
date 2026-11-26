from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest
from playwright.async_api import async_playwright
from pypdf import PdfReader

from app.core.config import Settings
from app.db.repositories import report_snapshot_identity
from app.db.snapshots import ReportVersionSnapshotV2
from app.pdf.renderer import PdfRenderer
from app.pdf.version import SavedVersion


async def _browser_path() -> str:
    configured = os.environ.get("PDF_TEST_BROWSER_EXECUTABLE_PATH")
    if configured:
        if not Path(configured).is_file():
            pytest.skip("configured PDF test browser is unavailable")
        return configured
    async with async_playwright() as playwright:
        path = playwright.chromium.executable_path
        if Path(path).is_file():
            return path
    pytest.skip("Playwright Chromium is not installed")


def _long_version(version: SavedVersion) -> SavedVersion:
    data = json.loads(version.snapshot_json)
    phrase = "Chiến dịch tiếp cận khách hàng tại Việt Nam tăng trưởng ổn định. "
    data["narrative"] = [
        {
            "item_id": str(uuid4()),
            "section": "findings" if index % 2 == 0 else "recommendations",
            "ordinal": index + 1,
            "classification": "observation" if index % 2 == 0 else "hypothesis",
            "content": f"Đoạn {index + 1}. " + phrase * 18,
        }
        for index in range(12)
    ]
    data["metrics"] += [
        {**data["metrics"][0], "metric_result_id": str(uuid4()), "value": str(index + 3)}
        for index in range(20)
    ]
    data["charts"] += [
        {
            "chart_type": "bar" if index % 2 else "line",
            "title": "Biểu đồ hiệu quả " + "dài " * 20 + str(index),
            "scope": "report",
            "metric_result_ids": [
                data["metrics"][index + 3]["metric_result_id"],
                data["metrics"][index + 4]["metric_result_id"],
            ],
        }
        for index in range(8)
    ]
    snapshot = ReportVersionSnapshotV2.model_validate(data)
    return replace(
        version,
        snapshot_json=snapshot.model_dump_json().encode(),
        snapshot_identity=report_snapshot_identity(snapshot),
    )


@pytest.mark.asyncio
async def test_chromium_renders_vietnamese_and_long_multipage_report(
    valid_settings_data: dict[str, object],
    version_factory: Callable[..., SavedVersion],
) -> None:
    browser_path = await _browser_path()
    renderer_settings = Settings.model_validate(
        {
            **valid_settings_data,
            "PDF_BROWSER_EXECUTABLE_PATH": browser_path,
            "PDF_RENDER_TIMEOUT_SECONDS": 60,
        }
    )
    renderer = PdfRenderer(renderer_settings)
    short = version_factory()
    long = _long_version(short)
    review_dir = os.environ.get("PDF_RENDER_REVIEW_DIR")
    for name, version in (("short", short), ("long", long)):
        output = await renderer.render(version)
        if review_dir:
            target = Path(review_dir)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{name}.pdf").write_bytes(output)
        document = PdfReader(BytesIO(output), strict=True)
        all_text = "\n".join(page.extract_text() for page in document.pages)
        continuous_text = unicodedata.normalize(
            "NFC", re.sub(r"\s+(?=[\u0300-\u036f])", "", re.sub(r"\s+", " ", all_text))
        )
        assert "Báo cáo hiệu quả" in all_text
        assert "Đánh giá hiệu quả" in all_text
        if name == "short":
            assert "Thử chiến dịch mới" in continuous_text
        assert "1.2500" in all_text and "Zero denominator" in all_text
        if name == "long":
            assert len(document.pages) >= 3
            assert all_text.index("Đoạn 1.") < all_text.index("Đoạn 12.")
            assert "Biểu đồ hiệu quả" in all_text
        else:
            assert len(document.pages) == 2
        assert all(len(page.extract_text().strip()) > 30 for page in document.pages)
        images = []
        pdf = pdfium.PdfDocument(output)
        for index in range(len(pdf)):
            image = pdf[index].render(scale=1).to_pil().convert("RGB")
            images.append(image)
            assert 580 <= image.width <= 610 and 825 <= image.height <= 850
            grayscale = image.convert("L").point(lambda pixel: 255 if pixel < 205 else 0)
            bounds = grayscale.getbbox()
            assert bounds is not None
            assert bounds[0] > 12 and bounds[1] > 12
            assert bounds[2] < image.width - 12 and bounds[3] < image.height - 12
            if review_dir:
                target = Path(review_dir)
                target.mkdir(parents=True, exist_ok=True)
                image.save(target / f"{name}-page-{index + 1}.png")


@pytest.mark.asyncio
async def test_browser_blocks_page_scripts_and_network(
    valid_settings_data: dict[str, object],
) -> None:
    browser_path = await _browser_path()
    renderer = PdfRenderer(
        Settings.model_validate(
            {**valid_settings_data, "PDF_BROWSER_EXECUTABLE_PATH": browser_path}
        )
    )
    requests = 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            nonlocal requests
            requests += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        html = (
            "<html><body>Visible text"
            f'<img src="http://127.0.0.1:{server.server_port}/track">'
            '<script>document.body.innerHTML="EXECUTED"</script></body></html>'
        )
        output = await renderer._render_html(html)
        text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(output)).pages)
        assert "Visible text" in text and "EXECUTED" not in text
        assert requests == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
