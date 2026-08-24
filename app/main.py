"""設定に応じてRouter、MiddlewareおよびDB依存を組み立てる。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health_router import router as health_router
from app.api.measurement_router import router as measurement_router
from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.observability.middleware import RequestContextMiddleware
from app.security.headers import WebSecurityHeadersMiddleware
from app.security.login_csrf import LoginCsrfManager
from app.security.login_rate_limit import LoginRateLimiter
from app.security.session import SessionManager
from app.security.web_auth import WebAuthenticator
from app.web.router import router as web_router


def create_app(settings: Settings) -> FastAPI:
    """指定された設定でFastAPIアプリケーションを生成する。"""

    docs_url = "/docs" if settings.api_docs_enabled else None
    redoc_url = "/redoc" if settings.api_docs_enabled else None
    openapi_url = "/openapi.json" if settings.api_docs_enabled else None

    application = FastAPI(
        title=settings.title,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    application.state.settings = settings
    application.state.session_factory = None
    application.state.agent_handler = None
    # DB未設定でもLiveチェックを起動でき、測定APIは利用不能として503を返す。
    if settings.database_url is not None:
        engine = create_db_engine(settings)
        application.state.db_engine = engine
        application.state.session_factory = create_session_factory(engine)
    application.add_middleware(WebSecurityHeadersMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(measurement_router)
    if settings.web_enabled:
        assert settings.web_username is not None
        assert settings.web_password_hash is not None
        application.state.web_sessions = SessionManager(
            idle_seconds=settings.web_session_idle_seconds,
            absolute_seconds=settings.web_session_absolute_seconds,
        )
        application.state.login_csrf = LoginCsrfManager()
        application.state.login_rate_limiter = LoginRateLimiter(
            window_seconds=settings.web_login_window_seconds,
            max_attempts=settings.web_login_max_attempts,
            lock_seconds=settings.web_login_lock_seconds,
        )
        application.state.web_authenticator = WebAuthenticator(
            settings.web_username,
            settings.web_password_hash.get_secret_value(),
        )
        application.mount(
            "/static",
            StaticFiles(directory=Path(__file__).parent / "web" / "static"),
            name="static",
        )
        application.include_router(web_router)
    return application


app = create_app(Settings())
