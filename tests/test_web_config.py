"""AI質問画面の設定境界を検証する。"""

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Environment, Settings


def test_web_credentials_must_be_configured_together() -> None:
    """利用者名とパスワードハッシュの片側設定を拒否する。"""

    with pytest.raises(ValidationError):
        Settings(environment=Environment.TEST, web_username="admin")


def test_web_routes_can_be_disabled_outside_production() -> None:
    """開発・テストでは認証情報未設定時にWeb UIだけを無効化できる。"""

    settings = Settings(environment=Environment.TEST)

    assert settings.web_enabled is False


def test_production_requires_web_credentials() -> None:
    """本番でWeb認証設定不足を拒否する。"""

    with pytest.raises(ValidationError):
        Settings(environment=Environment.PRODUCTION)

    settings = Settings(
        environment=Environment.PRODUCTION,
        web_username="admin",
        web_password_hash=SecretStr("hash"),
    )
    assert settings.web_enabled is True


def test_absolute_session_lifetime_must_exceed_idle_lifetime() -> None:
    """絶対期限が無操作期限以下になる設定を拒否する。"""

    with pytest.raises(ValidationError):
        Settings(
            environment=Environment.TEST,
            web_session_idle_seconds=1800,
            web_session_absolute_seconds=1800,
        )
