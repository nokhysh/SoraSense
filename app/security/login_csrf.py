"""認証前ログインフォーム用の署名付きCSRFトークンを提供する。"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.security.session import Clock, TokenGenerator, secure_token, utc_now


class LoginCsrfManager:
    """サーバー側セッションを作らずログインCSRFを検証する。"""

    def __init__(
        self,
        *,
        clock: Clock = utc_now,
        token_generator: TokenGenerator = secure_token,
        signing_key: bytes | None = None,
    ) -> None:
        self._clock = clock
        self._token_generator = token_generator
        self._signing_key = signing_key or secrets.token_bytes(32)
        self._lifetime = timedelta(minutes=10)

    def issue(self) -> str:
        """発行時刻と乱数へ署名したトークンを返す。"""

        issued_at = int(self._clock().timestamp())
        payload = f"{issued_at}.{self._token_generator()}"
        return f"{payload}.{self._signature(payload)}"

    def verify(self, cookie_token: str | None, form_token: str | None) -> bool:
        """Cookieとフォーム値、署名および期限がすべて正しいか検証する。"""

        if not cookie_token or not form_token or not hmac.compare_digest(cookie_token, form_token):
            return False
        try:
            issued_text, nonce, signature = cookie_token.split(".", 2)
            issued_at = datetime.fromtimestamp(int(issued_text), tz=self._clock().tzinfo)
        except (OverflowError, TypeError, ValueError):
            return False
        payload = f"{issued_text}.{nonce}"
        age = self._clock() - issued_at
        return timedelta(0) <= age < self._lifetime and hmac.compare_digest(
            signature, self._signature(payload)
        )

    def _signature(self, payload: str) -> str:
        return hmac.new(self._signing_key, payload.encode(), hashlib.sha256).hexdigest()
