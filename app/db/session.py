"""SQLAlchemyのEngineとSession Factoryを生成する。"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    """設定された接続先を使用するSQLAlchemy Engineを生成する。"""

    if settings.database_url is None:
        raise ValueError("APP_DATABASE_URL must be set")

    return create_engine(str(settings.database_url), pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """指定されたEngineに紐づくSession Factoryを生成する。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
