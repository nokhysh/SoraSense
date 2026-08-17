"""異常判定設定の起動時検証を確認する。"""

import pytest
from pydantic import ValidationError

from app.config import AlertSettings, Settings, ThresholdSettings


@pytest.mark.parametrize(
    ("lower", "upper", "hysteresis"),
    [("35", "10", "1"), ("10", "35", "0"), ("10", "35", "12.5")],
)
def test_invalid_threshold_settings_are_rejected(
    lower: str, upper: str, hysteresis: str
) -> None:
    """逆転した閾値と不正な復帰幅を拒否する。"""

    with pytest.raises(ValidationError):
        ThresholdSettings(
            lower=lower,
            upper=upper,
            hysteresis=hysteresis,
            minimum="-40",
            maximum="85",
        )


def test_nested_environment_overrides_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """運用環境変数で個別の閾値を上書きできる。"""

    monkeypatch.setenv("APP_ALERTS__TEMPERATURE__UPPER", "32.5")

    settings = Settings()

    assert settings.alerts.temperature.upper == 32.5
    assert settings.alerts == AlertSettings(
        temperature=settings.alerts.temperature,
        humidity=settings.alerts.humidity,
    )
