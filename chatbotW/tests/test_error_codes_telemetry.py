"""Tests for the TELEMETRY_DB_ERROR error code addition.

TDD RED: These tests verify the new ErrorCode enum member exists
with the correct value, user_message, and http_status.
"""
import json

import pytest
from error_codes import ErrorCode


class TestTelemetryDBError:
    """EC-1: ErrorCode must include TELEMETRY_DB_ERROR = "E-TEL-001"."""

    def test_telelemetry_db_error_exists(self):
        """ErrorCode must have a TELEMETRY_DB_ERROR member."""
        assert hasattr(ErrorCode, "TELEMETRY_DB_ERROR")

    def test_telemetry_db_error_value(self):
        """The value must be 'E-TEL-001'."""
        assert ErrorCode.TELEMETRY_DB_ERROR.value == "E-TEL-001"

    def test_telemetry_db_error_user_message(self):
        """Must have a user-friendly message in Spanish."""
        assert ErrorCode.TELEMETRY_DB_ERROR.user_message is not None
        assert len(ErrorCode.TELEMETRY_DB_ERROR.user_message) > 0

    def test_telemetry_db_error_http_status_503(self):
        """TELEMETRY_DB_ERROR must map to HTTP 503 (Service Unavailable)."""
        assert ErrorCode.TELEMETRY_DB_ERROR.http_status == 503


class TestTelemetryDBErrorIntegration:
    """TELEMETRY_DB_ERROR must work with AppError and error_handler."""

    def test_app_error_with_telemetry_code(self):
        """AppError(TELEMETRY_DB_ERROR) must create a valid error."""
        from exceptions import AppError
        err = AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="connection lost")
        assert err.code == ErrorCode.TELEMETRY_DB_ERROR
        assert err.detail == "connection lost"
        assert "E-TEL-001" in str(err)

    @pytest.mark.asyncio
    async def test_handler_returns_503_for_telemetry_error(self):
        """The error handler must map TELEMETRY_DB_ERROR to 503."""
        from error_handler import app_error_handler
        from exceptions import AppError
        from starlette.requests import Request

        request = Request({"type": "http", "method": "GET", "path": "/test"})
        exc = AppError(ErrorCode.TELEMETRY_DB_ERROR, detail="db timeout")
        response = await app_error_handler(request, exc)
        assert response.status_code == 503
        body = json.loads(response.body)
        assert body["error"]["code"] == "E-TEL-001"