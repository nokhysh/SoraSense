"""FastAPIアプリケーションを生成する。"""

from fastapi import FastAPI

from app.api.health_router import router as health_router
from app.config import Settings


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
    application.include_router(health_router)
    return application


app = create_app(Settings())
