"""Alembicの接続設定を検証する。"""

import configparser
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.db.migration_config import MigrationSettings

PROJECT_ROOT = Path(__file__).parent.parent


def test_migration_settings_create_postgresql_url() -> None:
    """環境別設定からMigration専用URLを生成する。"""

    settings = MigrationSettings.model_validate(
        {
            "host": "postgres",
            "port": 5432,
            "name": "sorasense",
            "user": "sorasense_migrator",
            "password": "test-password",
        }
    )

    database_url = settings.create_url()

    assert database_url.drivername == "postgresql+psycopg"
    assert database_url.username == "sorasense_migrator"
    assert database_url.host == "postgres"
    assert database_url.port == 5432
    assert database_url.database == "sorasense"


def test_migration_settings_require_connection_values() -> None:
    """必須の接続設定がない場合は検証エラーにする。"""

    with pytest.raises(ValidationError):
        MigrationSettings.model_validate({})


def test_migration_settings_load_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Migration専用環境変数から設定を読み込む。"""

    monkeypatch.setenv("MIGRATION_DB_HOST", "postgres")
    monkeypatch.setenv("MIGRATION_DB_NAME", "sorasense")
    monkeypatch.setenv("MIGRATION_DB_PASSWORD", "test-password")

    settings = MigrationSettings.from_environment()

    assert settings.host == "postgres"
    assert settings.name == "sorasense"
    assert settings.password.get_secret_value() == "test-password"


def test_alembic_ini_does_not_contain_database_url() -> None:
    """Alembic設定ファイルへ接続情報を記録しない。"""

    parser = configparser.ConfigParser()
    parser.read(PROJECT_ROOT / "alembic.ini")

    assert "sqlalchemy.url" not in parser["alembic"]
