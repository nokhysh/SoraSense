"""単一Web利用者のArgon2id認証を提供する。"""

import hmac

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError


class WebAuthenticator:
    """利用者の存在を応答差から推測しにくい固定利用者認証器。"""

    def __init__(self, username: str, password_hash: str) -> None:
        parameters = extract_parameters(password_hash)
        if parameters.type is not Type.ID:
            raise ValueError("web password hash must use Argon2id")
        self._username = username
        self._password_hash = password_hash
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash(secrets_for_dummy_hash())

    def verify(self, username: str, password: str) -> bool:
        """利用者名とパスワードの両方が一致した場合だけ成功する。"""

        username_matches = hmac.compare_digest(self._username, username)
        selected_hash = self._password_hash if username_matches else self._dummy_hash
        password_matches: bool
        try:
            password_matches = self._hasher.verify(selected_hash, password)
        except (InvalidHashError, VerificationError):
            password_matches = False
        return username_matches and password_matches


def secrets_for_dummy_hash() -> str:
    """ダミーハッシュ生成専用の固定されない値を返す。"""

    import secrets

    return secrets.token_urlsafe(32)
