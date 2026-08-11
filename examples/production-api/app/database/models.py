from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import mappings so Alembic sees every table through Base.metadata.
from app.identity import models as identity_models  # noqa: F401
from app.projects import models as project_models  # noqa: F401
