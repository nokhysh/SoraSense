"""SQLAlchemyの接続設定とSession Factoryを検証する。"""

import pytest
from pydantic import ValidationError

from app.config import Environment, Settings
from app.db.session import create_db_engine, create_session_factory


def test_create_db_engine_uses_database_url() -> None:
    """設定したURLからPostgreSQL用Engineを生成する。"""

    settings = Settings.model_validate(
        {
            "environment": Environment.TEST,
            "database_url": "postgresql+psycopg://app_user:password@postgres:5432/sorasense",
        }
    )

    engine = create_db_engine(settings)

    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "postgres"
    assert engine.url.port == 5432
    assert engine.url.database == "sorasense"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_create_db_engine_rejects_missing_database_url() -> None:
    """DB接続URLが未設定の場合はEngineを生成しない。"""

    settings = Settings(environment=Environment.TEST)

    with pytest.raises(ValueError, match="APP_DATABASE_URL must be set"):
        create_db_engine(settings)


def test_settings_rejects_non_postgresql_database_url() -> None:
    """PostgreSQL以外の接続URLを設定として受け付けない。"""

    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "environment": Environment.TEST,
                "database_url": "sqlite:///test.db",
            }
        )


def test_create_session_factory_binds_engine() -> None:
    """Session Factoryを指定したEngineへ紐づける。"""

    settings = Settings.model_validate(
        {
            "environment": Environment.TEST,
            "database_url": "postgresql+psycopg://app_user:password@postgres:5432/sorasense",
        }
    )
    engine = create_db_engine(settings)

    session_factory = create_session_factory(engine)

    assert session_factory.kw["bind"] is engine
    assert session_factory.kw["autoflush"] is False
    assert session_factory.kw["expire_on_commit"] is False
    engine.dispose()
