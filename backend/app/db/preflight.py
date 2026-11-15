"""Credential-free PostgreSQL connectivity probe for the local verification workflow."""

from __future__ import annotations

import errno
import json
import os
import socket

import psycopg


def _classification(error: BaseException) -> str:
    if isinstance(error, PermissionError) or getattr(error, "errno", None) in {
        errno.EACCES,
        errno.EPERM,
    }:
        return "postgres_permission_denied"
    if isinstance(error, (ConnectionRefusedError, TimeoutError, socket.gaierror)) or getattr(
        error, "errno", None
    ) in {errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH}:
        return "postgres_unreachable"
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate[:2] in {"28", "3D", "42"}:
        return "postgres_access_denied"
    text = str(error).lower()
    if "permission denied" in text or "operation not permitted" in text:
        return "postgres_permission_denied"
    if "connection refused" in text or "timeout" in text or "could not translate host" in text:
        return "postgres_unreachable"
    if "authentication failed" in text or "does not exist" in text:
        return "postgres_access_denied"
    if isinstance(error, psycopg.OperationalError):
        return "postgres_unreachable"
    return "postgres_preflight_unknown"


def main() -> int:
    url = os.environ.get("AI_LOCAL_POSTGRES_PROBE_URL")
    if not url:
        print(
            json.dumps(
                {
                    "passed": False,
                    "code": "postgres_preflight_unknown",
                    "message": "Probe input is missing.",
                }
            )
        )
        return 1
    try:
        driver_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(driver_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as error:
        code = _classification(error)
        print(
            json.dumps(
                {"passed": False, "code": code, "message": "PostgreSQL connectivity probe failed."}
            )
        )
        return 1
    print(json.dumps({"passed": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
