"""Authentication — login endpoint and token verification dependency."""

import os
import secrets
import time
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# In-memory token store: {token_hex: (username, created_at)}
_active_tokens: dict[str, tuple[str, float]] = {}
ADMIN_TOKEN_TTL = 8 * 3600  # 8 hours
SESSION_TTL_SECONDS = 3600  # 1 hour
CLEANUP_INTERVAL = 300  # 5 minutes
_last_cleanup: float = 0.0

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str

@dataclass
class UserSession:
    username: str
    email: str
    databricks_host: str
    pat: str # kept in memory only, never persisted
    workspace_client: WorkspaceClient
    created_at: float
    expires_at: float

@dataclass
class UserContext:
    username: str
    is_admin: bool
    session: UserSession | None # None for admin users, who don't have a session or workspace client

class TokenRequest(BaseModel):
    databricks_host: str
    access_token: str

# In-memory session store: {token_hex: UserSession}
_user_sessions: dict[str, UserSession] = {}

def _get_user_session(token: str) -> UserSession | None:
    """Look up a user session, returning None if missing or expired."""
    session = _user_sessions.get(token)
    if session is None:
        return None
    if time.time() > session.expires_at:
        del _user_sessions[token]
        return None
    return session

def _cleanup_expired_sessions() -> None:
    """Remove all expired sessions. Called lazily, not on every request."""
    now = time.time()
    expired = [t for t, s in _user_sessions.items() if now > s.expires_at]
    for t in expired:
        del _user_sessions[t]

@router.post("/api/auth/login")
async def login(creds: LoginRequest):
    if creds.username != ADMIN_USERNAME or creds.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_hex(32)
    _active_tokens[token] = (creds.username, time.time())
    return {"token": token}

@router.post("/api/auth/token")
async def create_token(req: TokenRequest):
    """Authenicate an SDK user via Databricks PAT. No prior auth required."""
    try:
        wc = WorkspaceClient(host=req.databricks_host, token=req.access_token)
        me = wc.current_user.me()
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Databricks credentials")
    now = time.time()
    token = secrets.token_hex(32)
    email = me.emails[0].value if me.emails else me.user_name
    _user_sessions[token] = UserSession(
        username=me.user_name,
        email=email,
        databricks_host=req.databricks_host,
        pat=req.access_token,
        workspace_client=wc,
        created_at=now,
        expires_at=now + SESSION_TTL_SECONDS,
    )
    return {"token": token,
            "username": me.user_name,
            "email": email,
            "expires_in": SESSION_TTL_SECONDS,
            }


async def verify_token(authorization: str = Header(None)) -> UserContext:
    """FastAPI dependency — extracts and validates Bearer token (admin or user)."""
    global _last_cleanup
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]

    # Periodic cleanup of expired sessions and admin tokens
    now = time.time()
    if now - _last_cleanup > CLEANUP_INTERVAL:
        _cleanup_expired_sessions()
        _cleanup_expired_tokens()
        _last_cleanup = now

    # Check admin tokens first
    entry = _active_tokens.get(token)
    if entry:
        username, created_at = entry
        if now - created_at > ADMIN_TOKEN_TTL:
            del _active_tokens[token]
        else:
            return UserContext(username=username, is_admin=True, session=None)
    # Check user sessions
    session = _get_user_session(token)
    if session:
        return UserContext(username=session.username, is_admin=False, session=session)
    raise HTTPException(status_code=401, detail="Invalid token")


def _cleanup_expired_tokens() -> None:
    """Remove all expired admin tokens."""
    now = time.time()
    expired = [t for t, (_, created) in _active_tokens.items()
               if now - created > ADMIN_TOKEN_TTL]
    for t in expired:
        del _active_tokens[t]