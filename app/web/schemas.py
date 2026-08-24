"""WebフォームとAgent表示結果の型を定義する。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LoginForm:
    """検証済みログインフォーム。"""

    username: str
    password: str
    csrf_token: str


@dataclass(frozen=True)
class QuestionForm:
    """検証済み質問フォーム。"""

    question: str
    csrf_token: str
    form_token: str


@dataclass(frozen=True)
class AgentDisplayResult:
    """HTMLへ安全に表示するためのAgent結果。"""

    answer: str
    device_id: str | None = None
    period: str | None = None
    evidence: tuple[str, ...] = ()


class FormValidationError(ValueError):
    """利用者へ定型メッセージで返せるフォーム境界違反。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
