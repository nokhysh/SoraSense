"""Alembic専用のデータベース接続設定を定義する。"""

import os
from typing import Self

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class MigrationSettings(BaseSettings):
    """環境変数からMigration専用の接続設定を読み込む。"""

    model_config = SettingsConfigDict(
        env_prefix="MIGRATION_DB_",
        extra="ignore",
        frozen=True,
    )

    host: str
    port: int = 5432
    name: str
    user: str = "sorasense_migrator"
    password: SecretStr

    @classmethod
    def from_environment(cls) -> Self:
        """Migration用環境変数を読み込んで設定を生成する。"""

        environment_names = {
            "host": "MIGRATION_DB_HOST",
            "port": "MIGRATION_DB_PORT",
            "name": "MIGRATION_DB_NAME",
            "user": "MIGRATION_DB_USER",
            "password": "MIGRATION_DB_PASSWORD",
        }
        values = {
            field_name: value
            for field_name, environment_name in environment_names.items()
            if (value := os.getenv(environment_name)) is not None
        }
        return cls.model_validate(values)

    def create_url(self) -> URL:
        """Secretを含むSQLAlchemy接続URLを生成する。"""

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )
