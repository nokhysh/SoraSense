"""AI質問画面の認証、セッションおよび入力境界を提供する。"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.security.login_csrf import LoginCsrfManager
from app.security.login_rate_limit import LoginRateLimiter
from app.security.session import SessionManager, WebSession
from app.security.web_auth import WebAuthenticator
from app.web.schemas import AgentDisplayResult, FormValidationError, LoginForm, QuestionForm

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
logger = logging.getLogger("sorasense.web")

AgentHandler = Callable[[str], Awaitable[AgentDisplayResult]]
LOGIN_CSRF_COOKIE = "sorasense_login_csrf"


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _sessions(request: Request) -> SessionManager:
    return cast(SessionManager, request.app.state.web_sessions)


def _login_csrf(request: Request) -> LoginCsrfManager:
    return cast(LoginCsrfManager, request.app.state.login_csrf)


def _rate_limiter(request: Request) -> LoginRateLimiter:
    return cast(LoginRateLimiter, request.app.state.login_rate_limiter)


def _session_id(request: Request) -> str | None:
    return request.cookies.get(_settings(request).web_session_cookie_name)


def _client_ip(request: Request) -> str:
    """ASGIサーバーが確定した接続元だけを使用する。"""

    return request.client.host if request.client is not None else "unknown"


def _render(
    request: Request,
    name: str,
    context: Mapping[str, object],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={"request_id": request.state.request_id, **context},
        status_code=status_code,
    )


def _log(request: Request, event: str, level: int, **values: object) -> None:
    logger.log(
        level,
        json.dumps({"event": event, "request_id": request.state.request_id, **values}),
    )


async def _read_form(request: Request) -> dict[str, str]:
    """許可した形式だけを上限付きで読み込み、重複項目を拒否する。"""

    settings = _settings(request)
    content_type = request.headers.get("content-type", "")
    media_type, *parameters = [part.strip() for part in content_type.split(";")]
    if media_type.lower() != "application/x-www-form-urlencoded":
        raise FormValidationError("送信形式が正しくありません", status_code=415)
    for parameter in parameters:
        if (
            parameter.lower().startswith("charset=")
            and parameter.split("=", 1)[1].lower() != "utf-8"
        ):
            raise FormValidationError("文字コードはUTF-8を使用してください")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            parsed_content_length = int(content_length)
        except ValueError:
            # 転送時に重複・変形したContent-Lengthは信用せず、実読込み量で判定する。
            parsed_content_length = None
        if (
            parsed_content_length is not None
            and parsed_content_length > settings.web_form_max_bytes
        ):
            raise FormValidationError("入力が大きすぎます", status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.web_form_max_bytes:
            raise FormValidationError("入力が大きすぎます", status_code=413)
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FormValidationError("文字コードはUTF-8を使用してください") from error
    parsed = parse_qs(decoded, keep_blank_values=True, strict_parsing=True)
    if any(len(values) != 1 for values in parsed.values()):
        raise FormValidationError("同じ入力項目を複数指定できません")
    return {key: values[0] for key, values in parsed.items()}


def _login_form(values: Mapping[str, str]) -> LoginForm:
    allowed = {"username", "password", "csrf_token"}
    if set(values) != allowed:
        raise FormValidationError("ログイン入力が正しくありません")
    username = values["username"]
    password = values["password"]
    if not 1 <= len(username) <= 128 or not 1 <= len(password) <= 256:
        raise FormValidationError("ログイン入力が正しくありません")
    return LoginForm(username=username, password=password, csrf_token=values["csrf_token"])


def _question_form(values: Mapping[str, str]) -> QuestionForm:
    allowed = {"question", "csrf_token", "form_token"}
    if set(values) != allowed:
        raise FormValidationError("質問入力が正しくありません")
    question = values["question"].strip()
    if not 1 <= len(question) <= 2000:
        raise FormValidationError("質問は1文字以上2000文字以内で入力してください")
    return QuestionForm(
        question=question,
        csrf_token=values["csrf_token"],
        form_token=values["form_token"],
    )


def _require_session(request: Request, *, touch: bool = True) -> WebSession | None:
    return _sessions(request).get(_session_id(request), touch=touch)


def _delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.web_session_cookie_name,
        path="/",
        secure=settings.secure_web_cookie,
        httponly=True,
        samesite="lax",
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    """ログインフォームを表示し、認証前CSRFトークンを発行する。"""

    if _require_session(request) is not None:
        return RedirectResponse("/agent", status_code=303)
    token = _login_csrf(request).issue()
    reason = (
        "セッションの有効期限が切れました。再度ログインしてください。"
        if request.query_params.get("reason") == "session_expired"
        else None
    )
    response = _render(
        request, "login.html", {"csrf_token": token, "error": None, "reason": reason}
    )
    response.set_cookie(
        LOGIN_CSRF_COOKIE,
        token,
        max_age=600,
        path="/login",
        secure=_settings(request).secure_web_cookie,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    """入力境界、CSRF、制限、Argon2id認証の順にログインを処理する。"""

    try:
        form = _login_form(await _read_form(request))
    except (FormValidationError, ValueError) as error:
        status_code = error.status_code if isinstance(error, FormValidationError) else 400
        return _render(request, "error.html", {"message": str(error)}, status_code=status_code)
    if not _login_csrf(request).verify(request.cookies.get(LOGIN_CSRF_COOKIE), form.csrf_token):
        _log(request, "web_csrf_rejected", logging.WARNING, authentication="anonymous")
        return _render(
            request, "error.html", {"message": "フォームの有効期限が切れました"}, status_code=403
        )
    limiter = _rate_limiter(request)
    ip = _client_ip(request)
    retry_after = limiter.retry_after(ip=ip, username=form.username)
    if retry_after is not None:
        _log(request, "web_login_rate_limited", logging.WARNING, retry_after=retry_after)
        response = _render(
            request,
            "error.html",
            {"message": "しばらく待ってから再試行してください"},
            status_code=429,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response
    authenticator = cast(WebAuthenticator, request.app.state.web_authenticator)
    if not authenticator.verify(form.username, form.password):
        limiter.record_failure(ip=ip, username=form.username)
        _log(
            request,
            "web_login_failed",
            logging.WARNING,
            ip_hash=limiter.anonymize("log-ip", ip),
            username_hash=limiter.anonymize("log-username", form.username),
        )
        return _render(
            request,
            "login.html",
            {
                "csrf_token": form.csrf_token,
                "error": "利用者名またはパスワードが正しくありません",
                "reason": None,
            },
            status_code=403,
        )
    limiter.clear(ip=ip, username=form.username)
    session_id, _ = _sessions(request).create(old_session_id=_session_id(request))
    redirect = RedirectResponse("/agent", status_code=303)
    redirect.set_cookie(
        _settings(request).web_session_cookie_name,
        session_id,
        path="/",
        secure=_settings(request).secure_web_cookie,
        httponly=True,
        samesite="lax",
    )
    redirect.delete_cookie(LOGIN_CSRF_COOKIE, path="/login")
    _log(request, "web_login_succeeded", logging.INFO, user_id="default-user")
    return redirect


@router.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request) -> Response:
    """認証済み利用者へ新しい質問フォームを表示する。"""

    session = _require_session(request)
    if session is None:
        response = RedirectResponse("/login?reason=session_expired", status_code=303)
        _delete_session_cookie(response, _settings(request))
        return response
    form_token = _sessions(request).issue_form_token(session)
    return _render(
        request,
        "agent.html",
        {"csrf_token": session.csrf_token, "form_token": form_token, "result": None, "error": None},
    )


@router.post("/agent/questions", response_class=HTMLResponse)
async def ask_question(request: Request) -> Response:
    """認証・入力・ワンタイム性を確認してからAgent境界を呼び出す。"""

    session = _require_session(request)
    if session is None:
        return _render(
            request, "error.html", {"message": "セッションが失効しました"}, status_code=401
        )
    try:
        form = _question_form(await _read_form(request))
    except (FormValidationError, ValueError) as error:
        status_code = error.status_code if isinstance(error, FormValidationError) else 400
        return _render(request, "error.html", {"message": str(error)}, status_code=status_code)
    if not _sessions(request).csrf_matches(session, form.csrf_token):
        _log(request, "web_csrf_rejected", logging.WARNING, authentication="authenticated")
        return _render(request, "error.html", {"message": "不正なフォームです"}, status_code=403)
    if not _sessions(request).consume_form_token(session, form.form_token):
        _log(request, "web_form_token_rejected", logging.INFO, reason="invalid")
        return _render(
            request, "error.html", {"message": "この質問フォームは使用できません"}, status_code=409
        )
    handler = cast(AgentHandler | None, getattr(request.app.state, "agent_handler", None))
    next_token = _sessions(request).issue_form_token(session)
    if handler is None:
        return _render(
            request,
            "agent.html",
            {
                "csrf_token": session.csrf_token,
                "form_token": next_token,
                "result": None,
                "error": "AI機能は現在利用できません。測定収集とGrafanaは引き続き利用できます。",
            },
            status_code=503,
        )
    try:
        result = await handler(form.question)
    except Exception as error:
        # Agent境界の障害を測定収集へ波及させず、例外本文もログへ出さない。
        _log(
            request,
            "web_agent_unavailable",
            logging.ERROR,
            error_type=type(error).__name__,
        )
        return _render(
            request,
            "agent.html",
            {
                "csrf_token": session.csrf_token,
                "form_token": next_token,
                "result": None,
                "error": "AI機能は現在利用できません。測定収集とGrafanaは引き続き利用できます。",
            },
            status_code=503,
        )
    return _render(
        request,
        "agent.html",
        {
            "csrf_token": session.csrf_token,
            "form_token": next_token,
            "result": result,
            "error": None,
        },
    )


@router.post("/logout")
async def logout(request: Request) -> Response:
    """CSRF検証後にサーバー側セッションとCookieを破棄する。"""

    session_id = _session_id(request)
    session = _require_session(request, touch=False)
    if session is None:
        return _render(
            request, "error.html", {"message": "セッションが失効しました"}, status_code=401
        )
    try:
        values = await _read_form(request)
    except (FormValidationError, ValueError) as error:
        status_code = error.status_code if isinstance(error, FormValidationError) else 400
        return _render(request, "error.html", {"message": str(error)}, status_code=status_code)
    if set(values) != {"csrf_token"} or not _sessions(request).csrf_matches(
        session, values.get("csrf_token")
    ):
        _log(request, "web_csrf_rejected", logging.WARNING, authentication="authenticated")
        return _render(request, "error.html", {"message": "不正なフォームです"}, status_code=403)
    _sessions(request).revoke(session_id)
    response = RedirectResponse("/login", status_code=303)
    _delete_session_cookie(response, _settings(request))
    _log(request, "web_logout_succeeded", logging.INFO, user_id=session.user_id)
    return response
