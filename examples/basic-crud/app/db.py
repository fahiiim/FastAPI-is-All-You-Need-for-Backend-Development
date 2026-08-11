from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DATABASE_URL = "sqlite:///./basic_crud.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


def create_schema() -> None:
    """Create the tutorial schema.

    Production applications apply reviewed Alembic migrations before serving traffic.
    """
    Base.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with SessionFactory() as session:
        yield session
