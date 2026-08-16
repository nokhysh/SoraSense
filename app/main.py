"""設定に応じてRouter、MiddlewareおよびDB依存を組み立てる。"""

from fastapi import FastAPI

from app.api.health_router import router as health_router
from app.api.measurement_router import router as measurement_router
from app.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.observability.middleware import RequestContextMiddleware


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
    # DB未設定でもLiveチェックを起動でき、測定APIは利用不能として503を返す。
    if settings.database_url is not None:
        engine = create_db_engine(settings)
        application.state.db_engine = engine
        application.state.session_factory = create_session_factory(engine)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(measurement_router)
    return application


app = create_app(Settings())
