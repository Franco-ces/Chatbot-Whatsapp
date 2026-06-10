"""Tests for the COM_SEND_DOCUMENT_FAILED error code addition.

TDD RED: These tests verify the new ErrorCode enum member exists
with the correct value, user_message, and http_status.
"""
import json

import pytest
from error_codes import ErrorCode


class TestSendDocumentErrorCode:
    """Task 1.1: ErrorCode must include COM_SEND_DOCUMENT_FAILED = "E-COM-008"."""

    def test_send_document_error_exists(self):
        """ErrorCode must have a COM_SEND_DOCUMENT_FAILED member."""
        assert hasattr(ErrorCode, "COM_SEND_DOCUMENT_FAILED")

    def test_send_document_error_value(self):
        """The value must be 'E-COM-008'."""
        assert ErrorCode.COM_SEND_DOCUMENT_FAILED.value == "E-COM-008"

    def test_send_document_error_user_message(self):
        """Must have a user-friendly message in Spanish."""
        assert ErrorCode.COM_SEND_DOCUMENT_FAILED.user_message is not None
        assert len(ErrorCode.COM_SEND_DOCUMENT_FAILED.user_message) > 0

    def test_send_document_error_http_status(self):
        """COM_SEND_DOCUMENT_FAILED must map to HTTP 502 (Bad Gateway)
        since it's a failure communicating with an upstream service."""
        assert ErrorCode.COM_SEND_DOCUMENT_FAILED.http_status == 502


class TestSendDocumentErrorCodeIntegration:
    """COM_SEND_DOCUMENT_FAILED must work with AppError and error_handler."""

    def test_app_error_with_send_document_code(self):
        """AppError(COM_SEND_DOCUMENT_FAILED) must create a valid error."""
        from exceptions import AppError
        err = AppError(ErrorCode.COM_SEND_DOCUMENT_FAILED, detail="sendMedia returned 400")
        assert err.code == ErrorCode.COM_SEND_DOCUMENT_FAILED
        assert err.detail == "sendMedia returned 400"
        assert "E-COM-008" in str(err)

    @pytest.mark.asyncio
    async def test_handler_returns_502_for_send_document_error(self):
        """The error handler must map COM_SEND_DOCUMENT_FAILED to 502."""
        from error_handler import app_error_handler
        from exceptions import AppError
        from starlette.requests import Request

        request = Request({"type": "http", "method": "GET", "path": "/test"})
        exc = AppError(ErrorCode.COM_SEND_DOCUMENT_FAILED, detail="timeout")
        response = await app_error_handler(request, exc)
        assert response.status_code == 502
        body = json.loads(response.body)
        assert body["error"]["code"] == "E-COM-008"