from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from presensi_api.api.errors import OPENAPI_ERROR_RESPONSES, ApiProblem
from presensi_api.api.security.config import AuthSettings
from presensi_api.api.security.dependencies import (
    get_auth_settings,
    get_current_user,
    get_password_change_user,
    issue_access_token,
)
from presensi_api.api.security.passwords import hash_password, verify_password
from presensi_api.api.security.roles import AuthenticatedUser, principal_for_user
from presensi_api.api.v1.schemas.auth import (
    CurrentUserResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    TokenResponse,
)
from presensi_api.db.models import AuditLog, User
from presensi_api.db.session import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


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
