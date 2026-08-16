"""デバイスAPI認証を検証する。"""

from argon2 import PasswordHasher

from app.security.device_auth import device_ids_match, verify_device_credentials


def test_device_api_key_is_verified_with_argon2id() -> None:
    """正しいBearer APIキーだけを受け付ける。"""

    hashed = PasswordHasher().hash("correct-secret")

    assert verify_device_credentials("Bearer correct-secret", "device-01", hashed) is True
    assert verify_device_credentials("Bearer wrong-secret", "device-01", hashed) is False
    assert verify_device_credentials(None, "device-01", hashed) is False


def test_device_ids_must_all_match() -> None:
    """設定、URLおよび本文のデバイスIDを照合する。"""

    assert device_ids_match("device-01", "device-01", "device-01") is True
    assert device_ids_match("device-01", "device-02", "device-01") is False
