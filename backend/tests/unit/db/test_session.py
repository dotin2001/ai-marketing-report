from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import create_session_factory, transaction


def test_session_factory_does_not_connect() -> None:
    engine = AsyncMock(spec=AsyncEngine)
    factory = create_session_factory(engine)

    assert factory.kw["expire_on_commit"] is False
    engine.connect.assert_not_called()


@pytest.mark.asyncio
async def test_transaction_closes_session_after_rollback() -> None:
    engine = AsyncMock(spec=AsyncEngine)
    factory = create_session_factory(engine)

    with pytest.raises(RuntimeError, match="rollback"):
        async with transaction(factory):
            raise RuntimeError("rollback")
