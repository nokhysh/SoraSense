"""アプリケーション設定を定義する。"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """アプリケーションの実行環境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """環境変数から読み込む、生成後に変更不能なアプリケーション設定。

    DBとデバイス認証を任意型にすることでLiveチェックだけの最小アプリも生成できる。
    Composeで測定APIを起動する場合は、Compose側でこれらを必須化する。
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.DEVELOPMENT
    title: str = "SoraSense API"
    database_url: PostgresDsn | None = None
    device_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$",
    )
    device_api_key_hash: SecretStr | None = None
    measurement_body_max_bytes: int = Field(default=16 * 1024, gt=0)

    @field_validator("device_id", "device_api_key_hash", mode="before")
    @classmethod
    def empty_secret_settings_are_unset(cls, value: object) -> object:
        """Composeから渡される空の任意設定を未設定として扱う。"""

        return None if value == "" else value

    @property
    def api_docs_enabled(self) -> bool:
        """APIドキュメントを公開する環境かを返す。"""

        return self.environment is not Environment.PRODUCTION


class HealthResponse(BaseModel):
    """Liveヘルスチェックの応答。"""

    model_config = ConfigDict(frozen=True)

    status: str = "ok"
