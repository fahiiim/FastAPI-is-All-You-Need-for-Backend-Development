from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import get_session

from .models import User
from .schemas import LoginInput, RegisterInput, TokenRead, UserRead
from .security import DUMMY_PASSWORD_HASH, issue_session, password_hash

router = APIRouter(prefix="/v1/auth", tags=["identity"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterInput, session: SessionDep) -> UserRead:
    user = User(
        email=str(payload.email).lower(),
        password_hash=password_hash.hash(payload.password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered") from exc
    return UserRead(id=user.id, email=user.email)


@router.post("/login", response_model=TokenRead)
def login(payload: LoginInput, session: SessionDep) -> TokenRead:
    user = session.scalar(select(User).where(User.email == str(payload.email).lower()))
    stored_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    valid = password_hash.verify(payload.password, stored_hash)
    if not valid or user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token, ttl = issue_session(session, user)
    return TokenRead(access_token=token, expires_in=ttl)
