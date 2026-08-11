from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.errors import ApplicationError
from app.database.session import engine
from app.identity.router import router as identity_router
from app.projects.router import router as projects_router

app = FastAPI(title="Production Project API", version="1.0.0")
app.include_router(identity_router)
app.include_router(projects_router)


@app.exception_handler(ApplicationError)
async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.detail}},
    )


@app.get("/health/live", include_in_schema=False)
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def ready() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ready"}
