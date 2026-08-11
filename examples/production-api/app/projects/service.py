from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.identity.models import User

from .models import Project


def create_project(session: Session, *, owner: User, name: str) -> Project:
    project = Project(owner_id=owner.id, name=name)
    session.add(project)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("A project with this name already exists") from exc
    session.refresh(project)
    return project


def get_owned_project(session: Session, *, owner: User, project_id: UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if project is None:
        raise NotFoundError("Project not found")
    return project
