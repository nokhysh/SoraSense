"""devicesモデルのメタデータを検証する。"""

from typing import cast

from sqlalchemy import CheckConstraint, DateTime, String, Table

from app.models.device import Device


def test_device_model_matches_database_design() -> None:
    """devicesモデルのスキーマ、カラム、NULL条件を確認する。"""

    table = cast(Table, Device.__table__)
    device_id_type = cast(String, table.c.device_id.type)

    assert table.schema == "app"
    assert set(table.columns.keys()) == {
        "device_id",
        "registered_at",
        "last_alert_evaluated_at",
    }
    assert table.primary_key.columns.keys() == ["device_id"]
    assert device_id_type.length == 64
    assert table.c.device_id.nullable is False
    assert table.c.registered_at.nullable is False
    assert table.c.registered_at.server_default is not None
    assert table.c.last_alert_evaluated_at.nullable is True

    assert isinstance(table.c.registered_at.type, DateTime)
    assert table.c.registered_at.type.timezone is True
    assert isinstance(table.c.last_alert_evaluated_at.type, DateTime)
    assert table.c.last_alert_evaluated_at.type.timezone is True


def test_device_model_has_device_id_format_constraint() -> None:
    """devicesモデルにデバイスID形式のCHECK制約がある。"""

    table = cast(Table, Device.__table__)
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert constraints == {
        "ck_devices_device_id_format": (
            "device_id ~ '^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$'"
        )
    }
