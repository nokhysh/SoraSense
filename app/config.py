"""アプリケーション設定を定義する。"""

from decimal import Decimal
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PostgresDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """アプリケーションの実行環境。"""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class ThresholdSettings(BaseModel):
    """1つの測定項目に対する異常開始閾値と復帰幅。"""

    model_config = ConfigDict(frozen=True)

    lower: Decimal
    upper: Decimal
    hysteresis: Decimal
    minimum: Decimal = Field(exclude=True)
    maximum: Decimal = Field(exclude=True)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ThresholdSettings":
        """閾値の順序、測定可能範囲および復帰幅を検証する。"""

        if not self.minimum <= self.lower < self.upper <= self.maximum:
            raise ValueError("thresholds must be ordered within the measurable range")
        if not Decimal("0") < self.hysteresis < (self.upper - self.lower) / 2:
            raise ValueError("hysteresis must be positive and less than half the threshold span")
        return self


class TemperatureThresholdSettings(ThresholdSettings):
    """温度の測定可能範囲を含む既定の監視条件。"""

    lower: Decimal = Decimal("10.0")
    upper: Decimal = Decimal("35.0")
    hysteresis: Decimal = Decimal("0.5")
    minimum: Decimal = Field(default=Decimal("-40.0"), exclude=True)
    maximum: Decimal = Field(default=Decimal("85.0"), exclude=True)


class HumidityThresholdSettings(ThresholdSettings):
    """湿度の測定可能範囲を含む既定の監視条件。"""

    lower: Decimal = Decimal("30.0")
    upper: Decimal = Decimal("70.0")
    hysteresis: Decimal = Decimal("2.0")
    minimum: Decimal = Field(default=Decimal("0.0"), exclude=True)
    maximum: Decimal = Field(default=Decimal("100.0"), exclude=True)


class AlertSettings(BaseModel):
    """温度・湿度の異常判定設定。"""

    model_config = ConfigDict(frozen=True)

    temperature: TemperatureThresholdSettings = Field(
        default_factory=TemperatureThresholdSettings
    )
    humidity: HumidityThresholdSettings = Field(default_factory=HumidityThresholdSettings)


class Settings(BaseSettings):
    """環境変数から読み込む、生成後に変更不能なアプリケーション設定。

    DBとデバイス認証を任意型にすることでLiveチェックだけの最小アプリも生成できる。
    Composeで測定APIを起動する場合は、Compose側でこれらを必須化する。
    """

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_nested_delimiter="__",
        nested_model_default_partial_update=True,
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
    alerts: AlertSettings = Field(default_factory=AlertSettings)

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
