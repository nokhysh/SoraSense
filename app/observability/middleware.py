"""すべてのHTTP要求に共通する追跡情報とアクセスログを提供する。

業務イベントの記録は各RouterまたはServiceが担当し、このMiddlewareは要求単位の
相関IDとHTTP結果だけを扱う。
"""

import json
import logging
import time
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("sorasense.access")


def normalize_request_id(value: str | None) -> str:
    """有効なUUID v4を採用し、それ以外では新しく発行する。"""

    try:
        parsed = UUID(value or "")
        if value is not None and parsed.version == 4 and str(parsed) == value.lower():
            return str(parsed)
    except (AttributeError, ValueError):
        pass
    return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    """応答へリクエストIDを付与し、アクセス結果をJSONで記録する。

    クライアント指定値はUUID v4として検証し、ログ注入や追跡IDの形式不統一を防ぐ。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = time.monotonic()
        request_id = normalize_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )
        )
        return response
