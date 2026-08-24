"""ログイン失敗をIPと利用者名の両軸で制限する。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.security.session import Clock, utc_now


@dataclass
class AttemptState:
    """1つの匿名化キーに対する失敗時刻とロック期限。"""

    failures: deque[datetime] = field(default_factory=deque)
    locked_until: datetime | None = None
    updated_at: datetime | None = None


class LoginRateLimiter:
    """有限サイズのプロセス内ストアでログイン総当たりを抑止する。"""

    def __init__(
        self,
        *,
        window_seconds: int,
        max_attempts: int,
        lock_seconds: int,
        clock: Clock = utc_now,
        hmac_key: bytes | None = None,
        max_keys: int = 10_000,
    ) -> None:
        self._window = timedelta(seconds=window_seconds)
        self._max_attempts = max_attempts
        self._lock_time = timedelta(seconds=lock_seconds)
        self._clock = clock
        self._hmac_key = hmac_key or secrets.token_bytes(32)
        self._max_keys = max_keys
        self._states: dict[str, AttemptState] = {}
        self._lock = threading.Lock()

    def retry_after(self, *, ip: str, username: str) -> int | None:
        """いずれかのキーが制限中なら残り秒数を返す。"""

        now = self._clock()
        with self._lock:
            remaining = [
                self._remaining(self._states.get(key), now) for key in self._keys(ip, username)
            ]
        active = [seconds for seconds in remaining if seconds is not None]
        return max(active) if active else None

    def record_failure(self, *, ip: str, username: str) -> None:
        """IPと利用者名の両方へ認証失敗を記録する。"""

        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            for key in self._keys(ip, username):
                state = self._states.setdefault(key, AttemptState())
                self._trim_failures(state, now)
                state.failures.append(now)
                state.updated_at = now
                if len(state.failures) >= self._max_attempts:
                    state.locked_until = now + self._lock_time
            self._enforce_capacity()

    def clear(self, *, ip: str, username: str) -> None:
        """正常認証後に関連する失敗履歴を削除する。"""

        with self._lock:
            for key in self._keys(ip, username):
                self._states.pop(key, None)

    def anonymize(self, kind: str, value: str) -> str:
        """ログ相関に使える鍵付きハッシュを返す。"""

        return self._key(kind, value)

    def _keys(self, ip: str, username: str) -> Iterable[str]:
        return (self._key("ip", ip), self._key("username", username))

    def _key(self, kind: str, value: str) -> str:
        payload = f"{kind}\0{value}".encode()
        return hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()

    def _remaining(self, state: AttemptState | None, now: datetime) -> int | None:
        if state is None or state.locked_until is None or state.locked_until <= now:
            return None
        return max(1, int((state.locked_until - now).total_seconds()))

    def _trim_failures(self, state: AttemptState, now: datetime) -> None:
        while state.failures and now - state.failures[0] >= self._window:
            state.failures.popleft()

    def _purge_expired(self, now: datetime) -> None:
        removable: list[str] = []
        for key, state in self._states.items():
            self._trim_failures(state, now)
            if state.locked_until is not None and state.locked_until <= now:
                state.locked_until = None
            if not state.failures and state.locked_until is None:
                removable.append(key)
        for key in removable:
            del self._states[key]

    def _enforce_capacity(self) -> None:
        overflow = len(self._states) - self._max_keys
        if overflow <= 0:
            return
        oldest = sorted(
            self._states,
            key=lambda key: (
                self._states[key].updated_at or datetime.min.replace(tzinfo=self._clock().tzinfo)
            ),
        )
        for key in oldest[:overflow]:
            del self._states[key]
