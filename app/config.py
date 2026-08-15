"""アプリケーション設定を定義する。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """アプリケーションの実行環境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """環境変数から読み込むアプリケーション設定。"""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    title: str = "SoraSense API"

    @property
    def api_docs_enabled(self) -> bool:
        """APIドキュメントを公開する環境かを返す。"""

        return self.environment is not Environment.PRODUCTION


class HealthResponse(BaseModel):
    """Liveヘルスチェックの応答。"""

    model_config = ConfigDict(frozen=True)

    status: str = "ok"
