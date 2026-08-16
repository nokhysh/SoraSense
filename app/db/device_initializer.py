"""環境設定された初期デバイスを冪等に登録する。"""

from typing import Annotated

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import insert

from app.models.device import DEVICE_ID_PATTERN, Device


class DeviceInitializationSettings(BaseSettings):
    """初期デバイス登録に必要な環境変数を読み込む。"""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    database_url: PostgresDsn
    device_id: Annotated[str, Field(pattern=DEVICE_ID_PATTERN)]


def register_device(engine: Engine, device_id: str) -> bool:
    """デバイスを未登録の場合だけ追加し、追加したかを返す。"""

    statement = (
        insert(Device)
        .values(device_id=device_id)
        .on_conflict_do_nothing(index_elements=[Device.device_id])
        .returning(Device.device_id)
    )
    with engine.begin() as connection:
        return connection.execute(statement).scalar_one_or_none() is not None


def main() -> None:
    """環境変数からDBへ接続し、初期デバイスを登録する。"""

    settings = DeviceInitializationSettings()  # type: ignore[call-arg]
    engine = create_engine(settings.database_url.encoded_string())
    try:
        register_device(engine, settings.device_id)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
