from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import create_schema, get_session
from .models import Task
from .schemas import TaskCreate, TaskPage, TaskPatch, TaskRead

SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_schema()
    yield


app = FastAPI(title="Basic Task API", version="1.0.0", lifespan=lifespan)


def require_task(session: Session, task_id: int) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, response: Response, session: SessionDep) -> Task:
    task = Task(title=payload.title)
    session.add(task)
    session.commit()
    session.refresh(task)
    response.headers["Location"] = f"/tasks/{task.id}"
    return task


@app.get("/tasks", response_model=TaskPage)
def list_tasks(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TaskPage:
    statement = select(Task).order_by(Task.id).limit(limit).offset(offset)
    items = list(session.scalars(statement))
    return TaskPage(items=items, limit=limit, offset=offset)


@app.get("/tasks/{task_id}", response_model=TaskRead)
def read_task(task_id: int, session: SessionDep) -> Task:
    return require_task(session, task_id)


@app.patch("/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: TaskPatch, session: SessionDep) -> Task:
    task = require_task(session, task_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Patched fields cannot be null")
    for name, value in changes.items():
        setattr(task, name, value)
    session.commit()
    session.refresh(task)
    return task


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, session: SessionDep) -> Response:
    task = require_task(session, task_id)
    session.delete(task)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/health/live", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}
