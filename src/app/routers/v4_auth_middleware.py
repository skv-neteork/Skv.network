import os
"""V4 Auth Middleware — извлекает user_id из API токена."""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL", "")

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Пропускаем публичные эндпоинты
        public_paths = ["/api/time", "/api/v1/info", "/api/consult", "/api/cubes", "/.well-known", "/docs", "/openapi.json"]
        if any(request.url.path.startswith(p) for p in public_paths):
            return await call_next(request)
        
        # Извлекаем токен
        token = request.headers.get("X-API-Key", "") or request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            # Для персональных эндпоинтов — токен обязателен
            if "/api/v4/sessions" in request.url.path or "/api/v4/users" in request.url.path:
                raise HTTPException(status_code=401, detail="API token required")
            return await call_next(request)
        
        # Проверяем токен в БД
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            user = await conn.fetchrow("SELECT api_key FROM user_api_keys WHERE api_key = $1", token)
            await conn.close()
            
            if user:
                request.state.user_id = user["user_id"]
            else:
                raise HTTPException(status_code=401, detail="Invalid token")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[AUTH] DB error: {e}", flush=True)
            # Если БД недоступна — разрешаем с user_id из тела запроса
            pass
        
        return await call_next(request)
