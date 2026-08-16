"""設定済みデバイスに対するBearer APIキー認証を提供する。

認証の成否だけを返し、ID不一致とキー不一致の詳細を外部へ公開しない。
"""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


def verify_device_credentials(
    authorization: str | None,
    configured_device_id: str | None,
    configured_api_key_hash: str | None,
) -> bool:
    """Bearer APIキーをArgon2idハッシュと照合する。"""

    if configured_device_id is None or configured_api_key_hash is None:
        return False
    scheme, separator, api_key = (authorization or "").partition(" ")
    if not separator or not secrets.compare_digest(scheme.lower(), "bearer") or not api_key:
        return False
    try:
        # 平文キーを保存せず、Argon2idの計算コストを含むverifyへ照合を委ねる。
        return PasswordHasher().verify(configured_api_key_hash, api_key)
    except (InvalidHashError, VerificationError):
        return False


def device_ids_match(*device_ids: str) -> bool:
    """設定値、URLおよび本文のデバイスIDを定時間比較可能な関数で照合する。"""

    first, *rest = device_ids
    return all(secrets.compare_digest(first, candidate) for candidate in rest)
