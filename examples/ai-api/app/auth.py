from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from app.config import Settings

demo_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True, slots=True)
class DemoPrincipal:
    client_id: str


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def require_demo_principal(
    supplied_key: Annotated[str | None, Depends(demo_api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DemoPrincipal:
    expected = settings.demo_api_key.get_secret_value()
    if supplied_key is None or not hmac.compare_digest(supplied_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API credential",
        )
    return DemoPrincipal(client_id="demo-client")
