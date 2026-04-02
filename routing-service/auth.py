"""Authentication — login endpoint and token verification dependency."""

import os
import secrets

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# In-memory token store: {token_hex: username}
_active_tokens: dict[str, str] = {}

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
async def login(creds: LoginRequest):
    if creds.username != ADMIN_USERNAME or creds.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    _active_tokens[token] = creds.username
    return {"token": token}


async def verify_token(authorization: str = Header(None)) -> str:
    """FastAPI dependency — extracts and validates Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    username = _active_tokens.get(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    return username
