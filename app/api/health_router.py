"""プロセスと必須依存関係のヘルスチェックAPIを提供する。"""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("sorasense.health")


@router.get("/live", response_model=HealthResponse)
def get_liveness() -> HealthResponse:
    """FastAPIプロセスが応答可能であることを返す。"""

    return HealthResponse()


@router.get("/ready", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def get_readiness(request: Request) -> HealthResponse | JSONResponse:
    """必須設定とDB接続を確認し、測定受付の準備状態を返す。

    Geminiは測定収集の必須依存ではないため判定対象に含めない。例外の内容や
    接続情報は応答・ログへ出さず、監視用の固定イベントだけを記録する。
    """

    settings = request.app.state.settings
    engine = getattr(request.app.state, "readiness_engine", None)
    required_settings_present = (
        settings.database_url is not None
        and settings.device_id is not None
        and settings.device_api_key_hash is not None
    )
    if not required_settings_present or engine is None:
        _log_ready_failure(request, "configuration_unavailable")
        return JSONResponse(status_code=503, content={"status": "unavailable"})

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        _log_ready_failure(request, "database_unavailable")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return HealthResponse()


def _log_ready_failure(request: Request, error_code: str) -> None:
    """秘密値や内部例外を含めずReady失敗を構造化ログへ記録する。"""

    logger.warning(
        json.dumps(
            {
                "event": "health.ready.failed",
                "request_id": getattr(request.state, "request_id", None),
                "result": "failure",
                "error_code": error_code,
            }
        )
    )
