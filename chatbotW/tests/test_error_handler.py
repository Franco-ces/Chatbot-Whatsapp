import json

import pytest
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from error_handler import (
    _build_error,
    app_error_handler,
    validation_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
from exceptions import AppError, CommunicationError, RAGError, APIError, ConfigError
from error_codes import ErrorCode


@pytest.fixture
def mock_request():
    return Request({"type": "http", "method": "GET", "path": "/test"})


class TestBuildError:
    def test_build_error_structure(self):
        result = _build_error("E-COM-001", "Mensaje", "Detalle")
        assert result == {
            "status": "error",
            "error": {
                "code": "E-COM-001",
                "message": "Mensaje",
                "detail": "Detalle",
            },
        }

    def test_build_error_empty_detail(self):
        result = _build_error("E-API-001", "Solicitud inválida.")
        assert result["error"]["detail"] == ""


class TestAppErrorHandler:

    @pytest.mark.parametrize("exc_class,error_code,expected_status", [
        (CommunicationError, ErrorCode.COM_CONNECTION_FAILED, 500),
        (CommunicationError, ErrorCode.COM_SEND_MESSAGE_FAILED, 500),
        (CommunicationError, ErrorCode.COM_GET_AUDIO_FAILED, 500),
        (RAGError, ErrorCode.RAG_QUERY_FAILED, 500),
        (RAGError, ErrorCode.RAG_AUDIO_FAILED, 500),
        (APIError, ErrorCode.API_INVALID_PAYLOAD, 400),
        (APIError, ErrorCode.API_NOT_FOUND, 404),
        (ConfigError, ErrorCode.CFG_READ_FAILED, 500),
        (ConfigError, ErrorCode.CFG_WRITE_FAILED, 500),
    ])
    @pytest.mark.asyncio
    async def test_returns_correct_code_and_status(self, mock_request, exc_class, error_code, expected_status):
        exc = exc_class(error_code)
        response = await app_error_handler(mock_request, exc)
        body = json.loads(response.body)
        assert response.status_code == expected_status
        assert body["status"] == "error"
        assert body["error"]["code"] == error_code.value

    @pytest.mark.asyncio
    async def test_rag_no_pdfs_returns_503(self, mock_request):
        exc = RAGError(ErrorCode.RAG_NO_PDFS)
        response = await app_error_handler(mock_request, exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_sys_dependency_missing_returns_503(self, mock_request):
        exc = AppError(ErrorCode.SYS_DEPENDENCY_MISSING)
        response = await app_error_handler(mock_request, exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_detail_uses_user_message_when_empty(self, mock_request):
        exc = CommunicationError(ErrorCode.COM_CONNECTION_FAILED)
        response = await app_error_handler(mock_request, exc)
        body = json.loads(response.body)
        assert body["error"]["detail"] == ErrorCode.COM_CONNECTION_FAILED.user_message

    @pytest.mark.asyncio
    async def test_detail_uses_provided_value(self, mock_request):
        exc = CommunicationError(ErrorCode.COM_CONNECTION_FAILED, detail="custom detail")
        response = await app_error_handler(mock_request, exc)
        body = json.loads(response.body)
        assert body["error"]["detail"] == "custom detail"


class TestValidationErrorHandler:

    @pytest.mark.asyncio
    async def test_returns_400_with_api_invalid_payload(self, mock_request):
        exc = RequestValidationError([])
        response = await validation_error_handler(mock_request, exc)
        assert response.status_code == 400
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.API_INVALID_PAYLOAD.value
        assert body["error"]["message"] == ErrorCode.API_INVALID_PAYLOAD.user_message

    @pytest.mark.asyncio
    async def test_includes_validation_errors(self, mock_request):
        errors = [{"loc": ("body", "name"), "msg": "field required", "type": "value_error"}]
        exc = RequestValidationError(errors)
        response = await validation_error_handler(mock_request, exc)
        body = json.loads(response.body)
        assert "field required" in body["error"]["detail"]


class TestHTTPErrorHandler:

    @pytest.mark.asyncio
    async def test_404_returns_api_not_found(self, mock_request):
        exc = StarletteHTTPException(404)
        response = await http_error_handler(mock_request, exc)
        assert response.status_code == 404
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.API_NOT_FOUND.value

    @pytest.mark.asyncio
    async def test_400_returns_invalid_payload(self, mock_request):
        exc = StarletteHTTPException(400)
        response = await http_error_handler(mock_request, exc)
        assert response.status_code == 400
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.API_INVALID_PAYLOAD.value

    @pytest.mark.asyncio
    async def test_403_returns_invalid_payload(self, mock_request):
        exc = StarletteHTTPException(403)
        response = await http_error_handler(mock_request, exc)
        assert response.status_code == 403
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.API_INVALID_PAYLOAD.value

    @pytest.mark.asyncio
    async def test_500_returns_server_error(self, mock_request):
        exc = StarletteHTTPException(500)
        response = await http_error_handler(mock_request, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.API_SERVER_ERROR.value


class TestUnhandledErrorHandler:

    @pytest.mark.asyncio
    async def test_returns_sys_unexpected(self, mock_request):
        exc = RuntimeError("boom")
        response = await unhandled_error_handler(mock_request, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body["error"]["code"] == ErrorCode.SYS_UNEXPECTED.value

    @pytest.mark.asyncio
    async def test_includes_exception_message(self, mock_request):
        exc = ValueError("invalid value")
        response = await unhandled_error_handler(mock_request, exc)
        body = json.loads(response.body)
        assert "invalid value" in body["error"]["detail"]
