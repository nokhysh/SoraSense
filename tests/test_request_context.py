"""リクエストID処理を検証する。"""

from uuid import UUID, uuid4

from app.observability.middleware import normalize_request_id


def test_valid_uuid_v4_request_id_is_preserved() -> None:
    """正規形式のUUID v4をそのまま採用する。"""

    request_id = str(uuid4())

    assert normalize_request_id(request_id) == request_id


def test_invalid_request_id_is_replaced_with_uuid_v4() -> None:
    """不正な値を新しいUUID v4へ置き換える。"""

    result = UUID(normalize_request_id("not-a-uuid"))

    assert result.version == 4
