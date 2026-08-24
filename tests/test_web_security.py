"""Web認証、セッション、CSRF、レート制限の純粋ロジックを検証する。"""

from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher

from app.security.login_csrf import LoginCsrfManager
from app.security.login_rate_limit import LoginRateLimiter
from app.security.session import SessionManager
from app.security.web_auth import WebAuthenticator


class MutableClock:
    """境界時刻を決定的に進められるテスト用Clock。"""

    def __init__(self) -> None:
        self.now = datetime(2026, 8, 23, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **values: float) -> None:
        """指定量だけ現在時刻を進める。"""

        self.now += timedelta(**values)


def test_session_is_regenerated_and_expires_at_idle_boundary() -> None:
    """ログイン再生成と無操作期限の境界を検証する。"""

    clock = MutableClock()
    tokens = iter(("old-id", "old-csrf", "new-id", "new-csrf"))
    manager = SessionManager(
        idle_seconds=1800,
        absolute_seconds=28800,
        clock=clock,
        token_generator=lambda: next(tokens),
        hmac_key=b"s" * 32,
    )
    old_id, _ = manager.create()
    new_id, _ = manager.create(old_session_id=old_id)

    assert manager.get(old_id) is None
    assert manager.get(new_id, touch=False) is not None
    clock.advance(seconds=1800)
    assert manager.get(new_id) is None


def test_form_token_is_one_time_and_only_latest_five_are_kept() -> None:
    """質問トークンの再利用拒否と最大件数を検証する。"""

    clock = MutableClock()
    tokens = iter(("session", "csrf", "one", "two", "three", "four", "five", "six"))
    manager = SessionManager(
        idle_seconds=1800,
        absolute_seconds=28800,
        clock=clock,
        token_generator=lambda: next(tokens),
    )
    _, session = manager.create()
    issued = [manager.issue_form_token(session) for _ in range(6)]

    assert manager.consume_form_token(session, issued[0]) is False
    assert manager.consume_form_token(session, issued[-1]) is True
    assert manager.consume_form_token(session, issued[-1]) is False


def test_login_csrf_requires_matching_signature_and_expires() -> None:
    """認証前CSRFの二重送信、署名、10分期限を検証する。"""

    clock = MutableClock()
    manager = LoginCsrfManager(
        clock=clock,
        token_generator=lambda: "nonce",
        signing_key=b"c" * 32,
    )
    token = manager.issue()

    assert manager.verify(token, token) is True
    assert manager.verify(token, f"{token}x") is False
    clock.advance(minutes=10)
    assert manager.verify(token, token) is False


def test_web_authenticator_uses_argon2id_and_rejects_wrong_credentials() -> None:
    """利用者名とArgon2idパスワードの両方を照合する。"""

    authenticator = WebAuthenticator("admin", PasswordHasher().hash("correct"))

    assert authenticator.verify("admin", "correct") is True
    assert authenticator.verify("other", "correct") is False
    assert authenticator.verify("admin", "wrong") is False


def test_rate_limiter_blocks_sixth_attempt_and_clears_on_success() -> None:
    """5回失敗後の制限と成功後の履歴削除を検証する。"""

    clock = MutableClock()
    limiter = LoginRateLimiter(
        window_seconds=900,
        max_attempts=5,
        lock_seconds=900,
        clock=clock,
    )
    for _ in range(5):
        assert limiter.retry_after(ip="127.0.0.1", username="admin") is None
        limiter.record_failure(ip="127.0.0.1", username="admin")

    assert limiter.retry_after(ip="127.0.0.1", username="admin") == 900
    limiter.clear(ip="127.0.0.1", username="admin")
    assert limiter.retry_after(ip="127.0.0.1", username="admin") is None
