from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    decode_browser_session_token,
    get_auth_settings,
    get_current_user,
    get_password_change_user,
    issue_access_token,
    issue_browser_session_token,
)
from presensi_api.api.security.passwords import hash_password, verify_password
from presensi_api.api.security.roles import AuthenticatedUser, principal_for_user
from presensi_api.api.v1.schemas.auth import (
    CurrentUserResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    TokenResponse,
)
from presensi_api.db.models import AuditLog, AuthSession, User
from presensi_api.db.session import get_db_session
from presensi_api.session_lifecycle import as_utc

router = APIRouter(prefix="/auth", tags=["auth"])
SESSION_COOKIE_NAME = "presensi_session"
SESSION_HEADER_NAME = "x-presensi-session"
SESSION_HEADER_VALUE = "browser"


def _set_session_cookie(response: Response, token: str, settings: AuthSettings) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_hours * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def _clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def _require_browser_session_header(request: Request) -> None:
    if request.headers.get(SESSION_HEADER_NAME) != SESSION_HEADER_VALUE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Browser session request is missing its required header.",
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Exchange credentials for an access token",
    description=(
        "Accepts OAuth2 password form fields; the username is the account email."
    ),
)
def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_db_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenResponse:
    email = form.username.strip().casefold()
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    valid_password = verify_password(
        form.password, user.password_hash if user is not None else None
    )
    if user is None or not user.is_active or not valid_password:
        attempt_id = uuid4()
        session.add(
            AuditLog(
                id=attempt_id,
                action="auth.login.failed",
                entity_type="authentication_attempt",
                entity_id=attempt_id,
                after_state={"method": "password", "result": "failure"},
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = principal_for_user(session, user)
    if not principal.roles:
        attempt_id = uuid4()
        session.add(
            AuditLog(
                id=attempt_id,
                action="auth.login.failed",
                entity_type="authentication_attempt",
                entity_id=attempt_id,
                after_state={"method": "password", "result": "failure"},
            )
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in_seconds = issue_access_token(
        user.id,
        settings,
        password_change_only=user.must_change_password,
        token_version=user.auth_token_version,
    )
    if request.headers.get(SESSION_HEADER_NAME) == SESSION_HEADER_VALUE:
        now = datetime.now(UTC)
        session_id = uuid4()
        session.add(
            AuthSession(
                id=session_id,
                user_id=user.id,
                created_at=now,
                expires_at=now + timedelta(hours=settings.session_ttl_hours),
            )
        )
        _set_session_cookie(
            response,
            issue_browser_session_token(
                user.id,
                session_id,
                settings,
                token_version=user.auth_token_version,
                now=now,
            ),
            settings,
        )
    session.add(
        AuditLog(
            action="auth.login.succeeded",
            actor_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            after_state={"method": "password", "result": "success"},
        )
    )
    session.commit()
    return TokenResponse(
        access_token=token,
        expires_in_seconds=expires_in_seconds,
        password_change_required=user.must_change_password,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Refresh the short-lived access token for the current browser session",
)
def refresh_session(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: Session = Depends(get_db_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenResponse:
    _require_browser_session_header(request)
    claims = (
        decode_browser_session_token(session_token, settings)
        if session_token is not None
        else None
    )
    now = datetime.now(UTC)
    auth_session = session.get(AuthSession, claims.session_id) if claims else None
    user = session.get(User, claims.user_id) if claims else None
    if (
        claims is None
        or auth_session is None
        or auth_session.user_id != claims.user_id
        or auth_session.revoked_at is not None
        or as_utc(auth_session.expires_at) <= now
        or user is None
        or not user.is_active
        or user.auth_token_version != claims.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired browser session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    principal = principal_for_user(session, user)
    if not principal.roles:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired browser session.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_session.last_used_at = now
    session.commit()
    token, expires_in_seconds = issue_access_token(
        user.id,
        settings,
        password_change_only=user.must_change_password,
        token_version=user.auth_token_version,
        now=now,
    )
    return TokenResponse(
        access_token=token,
        expires_in_seconds=expires_in_seconds,
        password_change_required=user.must_change_password,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Revoke the current browser session",
)
def logout_session(
    request: Request,
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: Session = Depends(get_db_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> Response:
    _require_browser_session_header(request)
    _clear_session_cookie(response, settings)
    claims = (
        decode_browser_session_token(session_token, settings)
        if session_token is not None
        else None
    )
    if claims is not None:
        auth_session = session.get(AuthSession, claims.session_id)
        if (
            auth_session is not None
            and auth_session.user_id == claims.user_id
            and auth_session.revoked_at is None
        ):
            now = datetime.now(UTC)
            auth_session.revoked_at = now
            session.add(
                AuditLog(
                    action="auth.logout.succeeded",
                    actor_user_id=claims.user_id,
                    entity_type="auth_session",
                    entity_id=claims.session_id,
                    after_state={"result": "success"},
                )
            )
            session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Get the authenticated account",
)
def get_me(
    principal: AuthenticatedUser = Depends(get_current_user),
) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=principal.id,
        email=principal.email,
        full_name=principal.full_name,
        roles=sorted(role.value for role in principal.roles),
        must_change_password=principal.must_change_password,
    )


@router.post(
    "/change-password",
    response_model=PasswordChangeResponse,
    responses=OPENAPI_ERROR_RESPONSES,
    summary="Change the current account password",
)
def change_password(
    request: PasswordChangeRequest,
    principal: AuthenticatedUser = Depends(get_password_change_user),
    session: Session = Depends(get_db_session),
) -> PasswordChangeResponse:
    user = session.get(User, principal.id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(request.current_password, user.password_hash):
        session.add(
            AuditLog(
                action="auth.password_change.failed",
                actor_user_id=user.id,
                entity_type="user",
                entity_id=user.id,
                after_state={"result": "invalid_current_password"},
            )
        )
        session.commit()
        raise ApiProblem(
            400,
            "current_password_invalid",
            "Kata sandi saat ini tidak benar.",
        )
    if verify_password(request.new_password, user.password_hash):
        raise ApiProblem(
            400,
            "password_unchanged",
            "Kata sandi baru harus berbeda dari kata sandi saat ini.",
        )

    user.password_hash = hash_password(request.new_password)
    user.must_change_password = False
    user.auth_token_version += 1
    session.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    session.add(
        AuditLog(
            action="auth.password_changed",
            actor_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            before_state={"must_change_password": principal.must_change_password},
            after_state={"must_change_password": False},
        )
    )
    session.commit()
    return PasswordChangeResponse(password_changed=True, sign_in_again=True)
