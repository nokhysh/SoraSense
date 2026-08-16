"""測定受付APIのHTTP境界を検証する。"""

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Environment, Settings
from app.main import create_app
from app.services.measurement_service import AcceptanceResult


def create_client() -> TestClient:
    """認証設定済みでDB未接続のテストクライアントを返す。"""

    return TestClient(
        create_app(
            Settings(
                environment=Environment.TEST,
                device_id="living-room-01",
                device_api_key_hash=PasswordHasher().hash("test-key"),
            )
        )
    )


def valid_payload() -> dict[str, object]:
    """正常なAPI要求本文を返す。"""

    return {
        "schema_version": 1,
        "message_id": str(uuid4()),
        "device_id": "living-room-01",
        "measured_at": datetime.now(UTC).isoformat(),
        "temperature_c": 24.5,
        "humidity_percent": 50.0,
    }


def test_measurement_api_rejects_missing_authentication() -> None:
    """APIキーがない要求を安全な共通応答で拒否する。"""

    response = create_client().post(
        "/api/v1/devices/living-room-01/measurements", json=valid_payload()
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_measurement_api_rejects_device_mismatch_after_authentication() -> None:
    """認証後にURLと本文のデバイス不一致を拒否する。"""

    response = create_client().post(
        "/api/v1/devices/other-device/measurements",
        json=valid_payload(),
        headers={"Authorization": "Bearer test-key"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "DEVICE_MISMATCH"


def test_measurement_api_rejects_invalid_media_type_and_oversized_body() -> None:
    """JSON以外と16 KiBを超える本文を保存処理前に拒否する。"""

    client = create_client()
    unsupported = client.post(
        "/api/v1/devices/living-room-01/measurements",
        content="value",
        headers={"Content-Type": "text/plain"},
    )
    oversized = client.post(
        "/api/v1/devices/living-room-01/measurements",
        content=b"{" + b" " * (16 * 1024) + b"}",
        headers={"Content-Type": "application/json"},
    )

    assert unsupported.status_code == 415
    assert oversized.status_code == 413


def test_measurement_api_returns_400_for_invalid_json() -> None:
    """壊れたJSONを400で拒否する。"""

    response = create_client().post(
        "/api/v1/devices/living-room-01/measurements",
        content="{",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_measurement_api_returns_503_when_database_is_not_configured() -> None:
    """DB未設定を503へ変換する。"""

    request_id = str(uuid4())
    response = create_client().post(
        "/api/v1/devices/living-room-01/measurements",
        json=valid_payload(),
        headers={"Authorization": "Bearer test-key", "X-Request-ID": request_id},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["request_id"] == request_id


def test_rejected_measurement_is_logged_as_structured_event(caplog: Any) -> None:
    """認証拒否を分類済みの構造化ログへ記録する。"""

    with caplog.at_level(logging.WARNING, logger="sorasense.measurements"):
        response = create_client().post(
            "/api/v1/devices/living-room-01/measurements", json=valid_payload()
        )

    record = json.loads(caplog.records[-1].message)
    assert response.status_code == 401
    assert record["event"] == "measurement.rejected"
    assert record["result"] == "rejected"
    assert record["error_code"] == "UNAUTHENTICATED"
    assert "temperature_c" not in record


def test_database_work_is_delegated_and_success_is_logged(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    """同期DB処理をスレッドへ移譲し、新規受付イベントを記録する。"""

    import app.api.measurement_router as measurement_router

    delegated = False

    class FakeMeasurementService:
        """DBを使用せず新規受付結果を返す。"""

        def __init__(self, session_factory: object) -> None:
            pass

        def accept(self, measurement: object) -> AcceptanceResult:
            return AcceptanceResult.CREATED

    async def fake_run_in_threadpool(function: Any, *args: Any) -> Any:
        """スレッド移譲関数を呼び出した事実を記録する。"""

        nonlocal delegated
        delegated = True
        return function(*args)

    monkeypatch.setattr(measurement_router, "MeasurementService", FakeMeasurementService)
    monkeypatch.setattr(measurement_router, "run_in_threadpool", fake_run_in_threadpool)
    client = create_client()
    client.app.state.session_factory = object()

    with caplog.at_level(logging.INFO, logger="sorasense.measurements"):
        response = client.post(
            "/api/v1/devices/living-room-01/measurements",
            json=valid_payload(),
            headers={"Authorization": "Bearer test-key"},
        )

    record = json.loads(caplog.records[-1].message)
    assert delegated is True
    assert response.status_code == 201
    assert record["event"] == "measurement.accepted"
    assert record["result"] == "success"
    assert "message_id" in record
