"""AlembicのMigration実行環境を構成する。"""

from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.db.migration_config import MigrationSettings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    # 同一プロセスでMigrationを実行するテストや管理処理のLoggerを無効化しない。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DBへ接続せず、Migration SQLを生成する。"""

    database_url = MigrationSettings.from_environment().create_url()
    context.configure(
        url=database_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """DBへ接続し、Migrationをトランザクション内で実行する。"""

    engine = create_engine(MigrationSettings.from_environment().create_url(), poolclass=NullPool)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
