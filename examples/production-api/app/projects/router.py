from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_session
from app.identity.models import User
from app.identity.security import get_current_user

from .models import Project
from .schemas import ProjectCreate, ProjectPage, ProjectRead
from .service import create_project, get_owned_project

router = APIRouter(prefix="/v1/projects", tags=["projects"])
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create(
    payload: ProjectCreate,
    response: Response,
    session: SessionDep,
    user: CurrentUser,
) -> Project:
    project = create_project(session, owner=user, name=payload.name)
    response.headers["Location"] = f"/v1/projects/{project.id}"
    return project


@router.get("", response_model=ProjectPage)
def list_projects(
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectPage:
    statement = (
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.created_at, Project.id)
        .limit(limit)
        .offset(offset)
    )
    return ProjectPage(items=list(session.scalars(statement)), limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectRead)
def read(project_id: UUID, session: SessionDep, user: CurrentUser) -> Project:
    return get_owned_project(session, owner=user, project_id=project_id)
