"""認証済みWebセッションとフォーム用トークンをプロセス内で管理する。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

Clock = Callable[[], datetime]
TokenGenerator = Callable[[], str]


def utc_now() -> datetime:
    """現在のUTC日時を返す。"""

    return datetime.now(UTC)


def secure_token() -> str:
    """256ビットのURL-safeトークンを生成する。"""

    return secrets.token_urlsafe(32)


@dataclass
class WebSession:
    """サーバー側だけで保持する認証済みセッション状態。"""

    user_id: str
    created_at: datetime
    last_seen_at: datetime
    csrf_token: str
    form_tokens: OrderedDict[str, datetime] = field(default_factory=OrderedDict)


class SessionManager:
    """セッションの生成、期限判定、破棄、ワンタイムトークン消費を直列化する。"""

    def __init__(
        self,
        *,
        idle_seconds: int,
        absolute_seconds: int,
        clock: Clock = utc_now,
        token_generator: TokenGenerator = secure_token,
        hmac_key: bytes | None = None,
    ) -> None:
        self._idle_lifetime = timedelta(seconds=idle_seconds)
        self._absolute_lifetime = timedelta(seconds=absolute_seconds)
        self._form_lifetime = timedelta(minutes=30)
        self._clock = clock
        self._token_generator = token_generator
        self._hmac_key = hmac_key or secrets.token_bytes(32)
        self._sessions: dict[str, WebSession] = {}
        self._lock = threading.Lock()

    def create(self, *, old_session_id: str | None = None) -> tuple[str, WebSession]:
        """既存セッションを破棄し、推測困難な新規セッションを発行する。"""

        now = self._clock()
        session_id = self._token_generator()
        session = WebSession(
            user_id="default-user",
            created_at=now,
            last_seen_at=now,
            csrf_token=self._token_generator(),
        )
        with self._lock:
            if old_session_id:
                self._sessions.pop(self._digest(old_session_id), None)
            self._sessions[self._digest(session_id)] = session
        return session_id, session

    def get(self, session_id: str | None, *, touch: bool = True) -> WebSession | None:
        """有効なセッションを返し、期限切れなら同時に削除する。"""

        if not session_id:
            return None
        now = self._clock()
        key = self._digest(session_id)
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if (
                now - session.last_seen_at >= self._idle_lifetime
                or now - session.created_at >= self._absolute_lifetime
            ):
                self._sessions.pop(key, None)
                return None
            if touch:
                session.last_seen_at = now
            return session

    def revoke(self, session_id: str | None) -> bool:
        """指定セッションを失効させ、存在していたか返す。"""

        if not session_id:
            return False
        with self._lock:
            return self._sessions.pop(self._digest(session_id), None) is not None

    @staticmethod
    def csrf_matches(session: WebSession, supplied_token: str | None) -> bool:
        """セッションのCSRFトークンを定時間比較する。"""

        return supplied_token is not None and hmac.compare_digest(
            session.csrf_token, supplied_token
        )

    def issue_form_token(self, session: WebSession) -> str:
        """質問フォーム用トークンを発行し、未使用の最新5件だけ保持する。"""

        token = self._token_generator()
        now = self._clock()
        with self._lock:
            self._purge_expired_form_tokens(session, now)
            session.form_tokens[token] = now
            while len(session.form_tokens) > 5:
                session.form_tokens.popitem(last=False)
        return token

    def consume_form_token(self, session: WebSession, supplied_token: str | None) -> bool:
        """有効な質問トークンを原子的に1回だけ消費する。"""

        if not supplied_token:
            return False
        now = self._clock()
        with self._lock:
            self._purge_expired_form_tokens(session, now)
            for token in tuple(session.form_tokens):
                if hmac.compare_digest(token, supplied_token):
                    del session.form_tokens[token]
                    return True
        return False

    def _digest(self, session_id: str) -> str:
        """Cookie値を直接保存しないためのHMACキーを作る。"""

        return hmac.new(self._hmac_key, session_id.encode(), hashlib.sha256).hexdigest()

    def _purge_expired_form_tokens(self, session: WebSession, now: datetime) -> None:
        expired = [
            token
            for token, issued_at in session.form_tokens.items()
            if now - issued_at >= self._form_lifetime
        ]
        for token in expired:
            del session.form_tokens[token]
