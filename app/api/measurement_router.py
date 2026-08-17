"""測定受付APIのHTTP境界を提供する。

Content-Type、本文サイズ、認証および入力形式を検証し、Serviceの結果と例外を
HTTP応答へ変換する。DB操作と冪等性の判断はServiceへ委譲する。
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.schemas.measurement import ApiResponse, MeasurementRequest
from app.security.device_auth import device_ids_match, verify_device_credentials
from app.services.measurement_service import (
    AcceptanceResult,
    DatabaseUnavailableError,
    MeasurementPersistenceError,
    MeasurementService,
)

# URL構造とOpenAPI上の分類をこのRouterへ閉じ込め、アプリ生成側を簡潔に保つ。
router = APIRouter(prefix="/api/v1/devices", tags=["measurements"])
logger = logging.getLogger("sorasense.measurements")


def error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    """共通形式のエラー応答を生成する。"""

    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(code=code, message=message, request_id=request_id).model_dump(),
    )


def log_measurement_result(
    event: str,
    request_id: str,
    device_id: str,
    result: str,
    *,
    message_id: str | None = None,
    error_code: str | None = None,
) -> None:
    """秘密情報や測定値を含めずに測定受付結果を構造化して記録する。"""

    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": "WARNING" if result == "rejected" else "INFO",
        "service": "sorasense-api",
        "event": event,
        "request_id": request_id,
        "device_id": device_id,
        "result": result,
    }
    if message_id is not None:
        record["message_id"] = message_id
    if error_code is not None:
        record["error_code"] = error_code
    # APIキーと測定値は調査に不要なため、運用ログへ複製しない。
    log_method = logger.warning if result == "rejected" else logger.info
    log_method(json.dumps(record))


def rejected_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    device_id: str,
) -> JSONResponse:
    """分類済み拒否イベントを記録して共通エラー応答を返す。"""

    log_measurement_result(
        "measurement.rejected",
        request_id,
        device_id,
        "rejected",
        error_code=code,
    )
    return error_response(status_code, code, message, request_id)


@router.post("/{device_id}/measurements", response_model=ApiResponse)
async def create_measurement(device_id: str, request: Request) -> JSONResponse:
    """認証・検証した測定を冪等に保存する。"""

    request_id = request.state.request_id
    settings = request.app.state.settings
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return rejected_response(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "Content-Type must be application/json",
            request_id,
            device_id,
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.measurement_body_max_bytes:
                return rejected_response(
                    413, "PAYLOAD_TOO_LARGE", "Request body is too large", request_id, device_id
                )
        except ValueError:
            return rejected_response(
                400, "VALIDATION_ERROR", "Invalid Content-Length", request_id, device_id
            )
    body = await request.body()
    if len(body) > settings.measurement_body_max_bytes:
        return rejected_response(
            413, "PAYLOAD_TOO_LARGE", "Request body is too large", request_id, device_id
        )

    api_key_hash = (
        settings.device_api_key_hash.get_secret_value()
        if settings.device_api_key_hash is not None
        else None
    )
    if not verify_device_credentials(
        request.headers.get("authorization"), settings.device_id, api_key_hash
    ):
        return rejected_response(
            401, "UNAUTHENTICATED", "Authentication failed", request_id, device_id
        )

    try:
        payload: Any = json.loads(body)
        measurement = MeasurementRequest.model_validate(payload)
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError):
        return rejected_response(
            400, "VALIDATION_ERROR", "Request body is invalid", request_id, device_id
        )

    if settings.device_id is None or not device_ids_match(
        settings.device_id, device_id, measurement.device_id
    ):
        return rejected_response(
            403, "DEVICE_MISMATCH", "Device does not match", request_id, device_id
        )

    session_factory = request.app.state.session_factory
    if session_factory is None:
        return error_response(503, "DATABASE_UNAVAILABLE", "Database is unavailable", request_id)
    try:
        # SQLAlchemyは同期APIのため、イベントループを止めないようスレッドへ移譲する。
        result = await run_in_threadpool(
            MeasurementService(session_factory, settings.alerts).accept,
            measurement,
        )
    except DatabaseUnavailableError:
        return error_response(503, "DATABASE_UNAVAILABLE", "Database is unavailable", request_id)
    except MeasurementPersistenceError:
        logger.exception("measurement persistence failed", extra={"request_id": request_id})
        return error_response(500, "INTERNAL_ERROR", "Internal server error", request_id)

    if result is AcceptanceResult.CREATED:
        log_measurement_result(
            "measurement.accepted",
            request_id,
            device_id,
            "success",
            message_id=str(measurement.message_id),
        )
        return JSONResponse(
            status_code=201,
            content=ApiResponse(
                code="MEASUREMENT_CREATED", message="Measurement accepted", request_id=request_id
            ).model_dump(),
        )
    log_measurement_result(
        "measurement.duplicate",
        request_id,
        device_id,
        "success",
        message_id=str(measurement.message_id),
    )
    return JSONResponse(
        status_code=200,
        content=ApiResponse(
            code="MEASUREMENT_ALREADY_ACCEPTED",
            message="Measurement already accepted",
            request_id=request_id,
        ).model_dump(),
    )
