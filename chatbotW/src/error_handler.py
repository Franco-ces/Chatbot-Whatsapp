from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from exceptions import AppError
from error_codes import ErrorCode


def _build_error(code: str, message: str, detail: str = "") -> dict:
    return {
        "status": "error",
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
        },
    }


async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.code.http_status,
        content=_build_error(
            code=exc.code.value,
            message=exc.code.user_message,
            detail=exc.detail,
        ),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=_build_error(
            code=ErrorCode.API_INVALID_PAYLOAD.value,
            message=ErrorCode.API_INVALID_PAYLOAD.user_message,
            detail=str(exc.errors()),
        ),
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        code = ErrorCode.API_NOT_FOUND
    elif 400 <= exc.status_code < 500:
        code = ErrorCode.API_INVALID_PAYLOAD
    else:
        code = ErrorCode.API_SERVER_ERROR
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error(
            code=code.value,
            message=code.user_message,
            detail=str(exc.detail) if isinstance(exc.detail, str) else "Error",
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=_build_error(
            code=ErrorCode.SYS_UNEXPECTED.value,
            message=ErrorCode.SYS_UNEXPECTED.user_message,
            detail=str(exc),
        ),
    )


def register_error_handlers(app: FastAPI):
    app.exception_handler(AppError)(app_error_handler)
    app.exception_handler(RequestValidationError)(validation_error_handler)
    app.exception_handler(StarletteHTTPException)(http_error_handler)
    app.exception_handler(Exception)(unhandled_error_handler)
