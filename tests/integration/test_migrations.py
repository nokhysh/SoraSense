"""Alembic Revisionのupgradeとdowngradeを検証する。"""

import os

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command


@pytest.fixture
def migration_database_url() -> str:
    """結合テスト用のMigration接続URLを返す。"""

    database_url = os.getenv("TEST_MIGRATION_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_MIGRATION_DATABASE_URL is not set")
    return database_url


def _configure_migration_environment(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
) -> None:
    """テスト用URLをAlembicが使用する環境変数へ展開する。"""

    url = make_url(database_url)
    assert url.host is not None
    assert url.database is not None
    assert url.username is not None
    assert url.password is not None
    monkeypatch.setenv("MIGRATION_DB_HOST", url.host)
    monkeypatch.setenv("MIGRATION_DB_PORT", str(url.port or 5432))
    monkeypatch.setenv("MIGRATION_DB_NAME", url.database)
    monkeypatch.setenv("MIGRATION_DB_USER", url.username)
    monkeypatch.setenv("MIGRATION_DB_PASSWORD", url.password)


def _app_tables(database_url: str) -> set[str]:
    """appスキーマに存在するテーブル名を返す。"""

    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'app'
            """
        ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.integration
def test_migrations_upgrade_from_empty_and_downgrade_each_revision(
    migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IT-007として空DB相当から各Revisionを順方向・逆方向へ適用する。"""

    _configure_migration_environment(monkeypatch, migration_database_url)
    config = Config("alembic.ini")
    expected_tables = {
        "0001_devices": {"devices"},
        "0002_measurements": {"devices", "measurements"},
        "0003_alerts": {"devices", "measurements", "alerts"},
        "0004_ai_requests": {"devices", "measurements", "alerts", "ai_requests"},
    }

    try:
        command.downgrade(config, "base")
        assert _app_tables(migration_database_url) == set()

        for revision, tables in expected_tables.items():
            command.upgrade(config, revision)
            assert _app_tables(migration_database_url) == tables

        for revision, tables in reversed(list(expected_tables.items())[:-1]):
            command.downgrade(config, revision)
            assert _app_tables(migration_database_url) == tables
    finally:
        command.upgrade(config, "head")
