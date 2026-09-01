"""DB接続設定からSQLAlchemyのEngineとSession Factoryを生成する。

アプリ生成時の接続部品だけを担当し、Sessionのトランザクション管理はServiceへ委譲する。
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import Settings

READINESS_CONNECT_TIMEOUT_SECONDS = 2
READINESS_STATEMENT_TIMEOUT_MILLISECONDS = 1000


def create_db_engine(settings: Settings) -> Engine:
    """設定された接続先を使用するSQLAlchemy Engineを生成する。"""

    if settings.database_url is None:
        raise ValueError("APP_DATABASE_URL must be set")

    url = make_url(str(settings.database_url))
    # driver省略URLでも、インストール済みのpsycopg v3を選択して環境差をなくす。
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True)


def create_readiness_engine(settings: Settings) -> Engine:
    """Ready確認専用の短い期限と接続非保持を設定したEngineを生成する。

    通常処理用Engineへ短いstatement timeoutを適用せず、監視要求が停止したDB接続や
    接続プールを占有し続けないよう、Ready確認だけを独立させる。
    """

    if settings.database_url is None:
        raise ValueError("APP_DATABASE_URL must be set")

    url = make_url(str(settings.database_url))
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "connect_timeout": READINESS_CONNECT_TIMEOUT_SECONDS,
            "options": (
                f"-c statement_timeout={READINESS_STATEMENT_TIMEOUT_MILLISECONDS}"
            ),
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """指定されたEngineに紐づくSession Factoryを生成する。"""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
