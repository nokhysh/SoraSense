"""フェーズ2で追加するSQLAlchemyモデルのメタデータを検証する。"""

from typing import cast

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint

from app.models import AIRequest, Alert, Measurement


def test_phase2_models_use_app_schema_and_expected_columns() -> None:
    """各モデルのスキーマと物理カラムを確認する。"""

    assert Measurement.__table__.schema == "app"
    assert set(Measurement.__table__.columns.keys()) == {
        "id",
        "device_id",
        "message_id",
        "measured_at",
        "temperature_c",
        "humidity_percent",
        "received_at",
    }
    assert Alert.__table__.schema == "app"
    assert set(Alert.__table__.columns.keys()) == {
        "id",
        "device_id",
        "metric",
        "direction",
        "status",
        "threshold_value",
        "trigger_value",
        "hysteresis",
        "started_at",
        "last_detected_at",
        "resolved_at",
    }
    assert AIRequest.__table__.schema == "app"
    assert set(AIRequest.__table__.columns.keys()) == {
        "id",
        "question",
        "answer",
        "status",
        "model",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "error_code",
        "created_at",
        "completed_at",
    }


def test_phase2_models_have_required_constraints_and_indexes() -> None:
    """重複防止・状態整合制約と検索用索引の名前を確認する。"""

    measurement_table = cast(Table, Measurement.__table__)
    alert_table = cast(Table, Alert.__table__)
    ai_request_table = cast(Table, AIRequest.__table__)
    measurement_constraints = {
        constraint.name
        for constraint in measurement_table.constraints
        if isinstance(constraint, (CheckConstraint, UniqueConstraint))
    }
    assert {
        "ck_measurements_device_id_format",
        "ck_measurements_temperature_range",
        "ck_measurements_humidity_range",
        "uq_measurements_device_message",
    } <= measurement_constraints
    assert {index.name for index in measurement_table.indexes} == {
        "ix_measurements_device_measured",
        "ix_measurements_device_received",
    }

    alert_constraints = {
        constraint.name
        for constraint in alert_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_alerts_metric_value",
        "ck_alerts_direction_value",
        "ck_alerts_status_value",
        "ck_alerts_hysteresis_positive",
        "ck_alerts_status_resolved_at",
    } <= alert_constraints
    alert_indexes = {str(index.name): index for index in alert_table.indexes}
    assert set(alert_indexes) == {
        "ix_alerts_device_started",
        "ix_alerts_device_status_started",
        "uq_alerts_open_condition",
    }
    assert isinstance(alert_indexes["uq_alerts_open_condition"], Index)
    assert alert_indexes["uq_alerts_open_condition"].unique is True

    ai_constraints = {
        constraint.name
        for constraint in ai_request_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_ai_requests_status_value",
        "ck_ai_requests_status_result",
        "ck_ai_requests_tool_calls_nonnegative",
        "ck_ai_requests_input_tokens_nonnegative",
        "ck_ai_requests_output_tokens_nonnegative",
    } <= ai_constraints
    assert {index.name for index in ai_request_table.indexes} == {
        "ix_ai_requests_created",
        "ix_ai_requests_status_created",
    }
