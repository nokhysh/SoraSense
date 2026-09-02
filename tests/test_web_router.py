"""AI質問Web画面のHTTP境界とブラウザ向け防御を検証する。"""

import re
from typing import Any, cast

from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Environment, Settings
from app.main import create_app
from app.web.schemas import AgentDisplayResult


def create_web_client() -> TestClient:
    """Web認証を有効にしたテストクライアントを返す。"""

    return TestClient(
        create_app(
            Settings(
                environment=Environment.TEST,
                web_username="admin",
                web_password_hash=SecretStr(PasswordHasher().hash("test-password")),
            )
        )
    )


def hidden_value(html: str, name: str) -> str:
    """テスト対象HTMLからhidden input値を取得する。"""

    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def login(client: TestClient) -> None:
    """CSRF付きフォームで正常ログインする。"""

    page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "test-password",
            "csrf_token": hidden_value(page.text, "csrf_token"),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_web_routes_are_absent_when_credentials_are_not_configured() -> None:
    """開発・テストで認証情報未設定ならWeb経路を公開しない。"""

    client = TestClient(create_app(Settings(environment=Environment.TEST)))

    assert client.get("/login").status_code == 404


def test_login_regenerates_session_and_sets_security_headers() -> None:
    """ログイン成功時のCookie属性と画面ヘッダーを検証する。"""

    client = create_web_client()
    page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "test-password",
            "csrf_token": hidden_value(page.text, "csrf_token"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "Secure" not in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    agent = client.get("/agent")
    assert agent.status_code == 200
    assert 'href="http://127.0.0.1:3000/d/sorasense-overview/sorasense-overview"' in agent.text
    assert agent.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in agent.headers["Content-Security-Policy"]


def test_login_rejects_csrf_and_rate_limits_sixth_failure() -> None:
    """ログインCSRF拒否とIP・利用者名単位の試行制限を検証する。"""

    client = create_web_client()
    assert (
        client.post(
            "/login",
            data={"username": "admin", "password": "wrong", "csrf_token": "wrong"},
        ).status_code
        == 403
    )
    for _ in range(5):
        page = client.get("/login")
        response = client.post(
            "/login",
            data={
                "username": "admin",
                "password": "wrong",
                "csrf_token": hidden_value(page.text, "csrf_token"),
            },
        )
        assert response.status_code == 403
    page = client.get("/login")
    limited = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "wrong",
            "csrf_token": hidden_value(page.text, "csrf_token"),
        },
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_question_requires_csrf_and_consumes_form_token_once() -> None:
    """質問POSTのCSRFとワンタイムフォームトークンを検証する。"""

    client = create_web_client()
    login(client)
    page = client.get("/agent")
    csrf_token = hidden_value(page.text, "csrf_token")
    form_token = hidden_value(page.text, "form_token")
    invalid = client.post(
        "/agent/questions",
        data={"question": "現在値は？", "csrf_token": "wrong", "form_token": form_token},
    )
    assert invalid.status_code == 403
    first = client.post(
        "/agent/questions",
        data={"question": "現在値は？", "csrf_token": csrf_token, "form_token": form_token},
    )
    second = client.post(
        "/agent/questions",
        data={"question": "現在値は？", "csrf_token": csrf_token, "form_token": form_token},
    )
    assert first.status_code == 503
    assert second.status_code == 409


def test_question_output_is_html_escaped() -> None:
    """Agent境界から返るHTMLを実行可能な形で表示しない。"""

    client = create_web_client()

    async def fake_agent(question: str) -> AgentDisplayResult:
        return AgentDisplayResult(answer=f"<script>{question}</script>", evidence=("<b>24.0℃</b>",))

    cast(FastAPI, client.app).state.agent_handler = fake_agent
    login(client)
    page = client.get("/agent")
    response = client.post(
        "/agent/questions",
        data={
            "question": "alert(1)",
            "csrf_token": hidden_value(page.text, "csrf_token"),
            "form_token": hidden_value(page.text, "form_token"),
        },
    )

    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "&lt;b&gt;24.0℃&lt;/b&gt;" in response.text


def test_agent_exception_returns_safe_retry_form(caplog: Any) -> None:
    """Agent例外を秘密情報のない503画面へ変換し、新しいフォームを返す。"""

    client = create_web_client()

    async def failing_agent(question: str) -> AgentDisplayResult:
        raise RuntimeError("secret-agent-detail")

    cast(FastAPI, client.app).state.agent_handler = failing_agent
    login(client)
    page = client.get("/agent")
    old_form_token = hidden_value(page.text, "form_token")

    with caplog.at_level("ERROR", logger="sorasense.web"):
        response = client.post(
            "/agent/questions",
            data={
                "question": "現在値は？",
                "csrf_token": hidden_value(page.text, "csrf_token"),
                "form_token": old_form_token,
            },
        )

    assert response.status_code == 503
    assert "AI機能は現在利用できません" in response.text
    assert "リクエストID:" in response.text
    assert hidden_value(response.text, "form_token") != old_form_token
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "web_agent_unavailable" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "secret-agent-detail" not in caplog.text


def test_logout_rejects_csrf_and_revokes_session() -> None:
    """ログアウトのCSRF検証とサーバー側失効を確認する。"""

    client = create_web_client()
    login(client)
    page = client.get("/agent")
    csrf_token = hidden_value(page.text, "csrf_token")
    assert client.post("/logout", data={"csrf_token": "wrong"}).status_code == 403
    response = client.post(
        "/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/agent", follow_redirects=False).headers["location"].startswith("/login")


def test_question_rejects_invalid_media_type_and_oversized_body() -> None:
    """質問入力のContent-Typeと本文上限をAgent呼出し前に拒否する。"""

    client = create_web_client()
    login(client)

    unsupported = client.post(
        "/agent/questions",
        content="question=value",
        headers={"Content-Type": "text/plain"},
    )
    oversized = client.post(
        "/agent/questions",
        content=b"question=" + b"a" * 4097,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert unsupported.status_code == 415
    assert oversized.status_code == 413, oversized.text
