"""V4 Auth Middleware — extracts user_id from API token. Fail-closed on DB errors for protected paths."""
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import asyncpg

from app.security import get_database_url, extract_bearer_or_api_key

# Paths that never require auth
PUBLIC_PREFIXES = (
    "/api/time",
    "/api/v1/info",
    "/api/consult",
    "/api/cubes",
    "/.well-known",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/auth",
    "/auth",
    "/api/v7",   # v7 has its own key check (app/v7_auth.py); skip the per-request Postgres lookup
)

# Paths that always require a valid API token
PROTECTED_PREFIXES = (
    "/api/v4/sessions",
    "/api/v4/users",
    "/api/v4/cubes",
    "/api/execute/code",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = extract_bearer_or_api_key(request.headers)
        needs_auth = any(path.startswith(p) for p in PROTECTED_PREFIXES)

        if not token:
            if needs_auth:
                raise HTTPException(status_code=401, detail="API token required")
            return await call_next(request)

        url = get_database_url()
        if not url:
            import sqlite3
            row = sqlite3.connect("/data/skv/metadata_store/shared_master.db").execute(
                "select user_id from user_api_keys where api_key=? and is_active=1", (token,)
            ).fetchone()
            if row:
                request.state.user_id = row[0]
                return await call_next(request)
            if needs_auth:
                raise HTTPException(status_code=503, detail="Auth database unavailable")
            return await call_next(request)

        try:
            conn = await asyncpg.connect(url)
            try:
                # Support both column layouts: user_id or email as owner
                user = await conn.fetchrow(
                    """
                    SELECT user_id FROM user_api_keys
                    WHERE api_key = $1
                      AND COALESCE(is_active, TRUE) = TRUE
                    LIMIT 1
                    """,
                    token,
                )
                if not user:
                    # Some schemas store only api_key without is_active
                    user = await conn.fetchrow(
                        "SELECT user_id FROM user_api_keys WHERE api_key = $1 LIMIT 1",
                        token,
                    )
            finally:
                await conn.close()

            if not user:
                raise HTTPException(status_code=401, detail="Invalid token")

            request.state.user_id = user["user_id"]
            request.state.api_key = token
        except HTTPException:
            raise
        except Exception as e:
            print(f"[AUTH] DB error: {e}", flush=True)
            # Fail closed for protected endpoints — never trust client user_id
            if needs_auth:
                raise HTTPException(status_code=503, detail="Auth database unavailable")
            # Unprotected path with a provided token we couldn't validate: strip trust
            request.state.user_id = None

        return await call_next(request)
