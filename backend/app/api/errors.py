"""API 공통 오류 형식 (docs/API_SPEC.md 1. 공통 계약)."""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """팀 API 문서에 정해진 모양으로 돌려줄 오류."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def _error_body(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": "req-" + uuid4().hex[:8],
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": [str(part) for part in error.get("loc", ())], "msg": str(error.get("msg", "")), "type": str(error.get("type", ""))}
            for error in exc.errors()
        ]
        only_query = bool(errors) and all(error["loc"][:1] == ["query"] for error in errors)
        code = "INVALID_FILTER" if only_query else "INVALID_REQUEST"
        return JSONResponse(
            status_code=422,
            content=_error_body(code, "요청 값이 올바르지 않습니다.", {"errors": errors}),
        )
