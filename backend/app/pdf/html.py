"""Autoescaped report-v1 HTML composition with packaged print assets."""

from __future__ import annotations

import base64
from functools import lru_cache
from importlib import resources

from jinja2 import Environment, PackageLoader, select_autoescape

from app.pdf.version import SavedVersion
from app.pdf.view_model import build_report_view


@lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(
        loader=PackageLoader("app.pdf", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        auto_reload=False,
    )


@lru_cache(maxsize=1)
def _font_data_uri() -> str:
    font = resources.files("app.pdf").joinpath("assets", "NotoSans.ttf").read_bytes()
    if len(font) < 100_000 or font[:4] not in {b"\x00\x01\x00\x00", b"OTTO"}:
        raise ValueError("packaged report font is unavailable")
    return "data:font/ttf;base64," + base64.b64encode(font).decode("ascii")


def render_report_html(version: SavedVersion) -> str:
    report = build_report_view(version)
    return (
        _environment()
        .get_template("report-v1.html")
        .render(report=report, font_data_uri=_font_data_uri())
    )
