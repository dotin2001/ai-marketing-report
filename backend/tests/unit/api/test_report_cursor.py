from __future__ import annotations

import base64
import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest

from app.db.models import Report
from app.domain.reports import InvalidCursor, ReportServices


def test_cursor_binds_owner_route_order_and_expiry() -> None:
    owner = uuid4()
    report = Report(
        owner_id=owner,
        name="R",
        period_start=datetime(2026, 1, 1).date(),
        period_end=datetime(2026, 1, 31).date(),
    )
    report.id = uuid4()
    report.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    service = ReportServices(None, "x" * 32)  # type: ignore[arg-type]
    cursor = service._encode_cursor(owner, report)
    assert service._decode_cursor(owner, cursor) == (report.created_at, report.id)
    with pytest.raises(InvalidCursor):
        service._decode_cursor(uuid4(), cursor)
    with pytest.raises(InvalidCursor):
        service._decode_cursor(owner, cursor + "x")

    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    body = json.loads(raw[:-32])
    for changed in ({"route": "/api/v1/other"}, {"order": "id:asc"}, {"expires_at": 1}):
        forged = {**body, **changed}
        payload = json.dumps(forged, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(b"x" * 32, payload, sha256).digest()
        token = base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")
        with pytest.raises(InvalidCursor):
            service._decode_cursor(owner, token)
