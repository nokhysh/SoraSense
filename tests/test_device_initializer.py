"""初期デバイス登録処理を検証する。"""

from unittest.mock import MagicMock

from sqlalchemy.engine import Engine

from app.db.device_initializer import register_device


def test_register_device_reports_inserted_row() -> None:
    """登録結果が返された場合は新規登録として扱う。"""

    engine = MagicMock(spec=Engine)
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one_or_none.return_value = "living-room-01"

    assert register_device(engine, "living-room-01") is True


def test_register_device_reports_existing_row() -> None:
    """競合時に結果がない場合は登録済みとして扱う。"""

    engine = MagicMock(spec=Engine)
    connection = engine.begin.return_value.__enter__.return_value
    connection.execute.return_value.scalar_one_or_none.return_value = None

    assert register_device(engine, "living-room-01") is False
