"""ブラウザ向け応答へ共通セキュリティヘッダーを付与する。"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class WebSecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Web画面をキャッシュ・埋込み・意図しない資源読込みから保護する。"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path in {"/login", "/agent", "/agent/questions", "/logout"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self'; img-src 'self'; "
                "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Frame-Options"] = "DENY"
        return response
