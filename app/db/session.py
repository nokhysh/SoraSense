"""DB接続設定からSQLAlchemyのEngineとSession Factoryを生成する。

アプリ生成時の接続部品だけを担当し、Sessionのトランザクション管理はServiceへ委譲する。
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    """設定された接続先を使用するSQLAlchemy Engineを生成する。"""

    if settings.database_url is None:
        raise ValueError("APP_DATABASE_URL must be set")

    url = make_url(str(settings.database_url))
    # driver省略URLでも、インストール済みのpsycopg v3を選択して環境差をなくす。
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """指定されたEngineに紐づくSession Factoryを生成する。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
