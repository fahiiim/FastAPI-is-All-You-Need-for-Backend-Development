from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.session import get_session

from .models import LoginSession, User

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("not-a-real-password")
bearer = HTTPBearer(auto_error=False)


def digest_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def issue_session(session: Session, user: User) -> tuple[str, int]:
    ttl = get_settings().session_ttl_seconds
    raw_token = token_urlsafe(32)
    login = LoginSession(
        user_id=user.id,
        token_digest=digest_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
    )
    session.add(login)
    session.commit()
    return raw_token, ttl


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")

    statement = (
        select(User)
        .join(LoginSession, LoginSession.user_id == User.id)
        .where(
            LoginSession.token_digest == digest_token(credentials.credentials),
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > datetime.now(UTC),
        )
    )
    user = session.scalar(statement)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired credentials")
    return user
