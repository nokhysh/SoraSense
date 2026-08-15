"""ヘルスチェックAPIを提供する。"""

from fastapi import APIRouter

from app.config import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
def get_liveness() -> HealthResponse:
    """FastAPIプロセスが応答可能であることを返す。"""

    return HealthResponse()
