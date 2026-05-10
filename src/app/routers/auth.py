from fastapi import APIRouter, Request, HTTPException
import asyncpg
import os
import secrets
import hashlib
import uuid
import requests
import json

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://skv_user:skv_secret_2026@127.0.0.1:5432/skv_db")
RESEND_KEY = "re_S7pvVUex_GjH4EYHJVcjs72Xt7Lbbrz5s"

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

def hash_password(password: str) -> str:
    salt = os.getenv("SKV_SALT", "skv_default_salt_2026")
    return hashlib.sha256((password + salt).encode()).hexdigest()

def generate_code() -> str:
    return secrets.token_hex(3).upper()

def send_email(email: str, code: str) -> bool:
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "SKV-Network/2.0"
            },
            json={
                "from": "SKV Network <noreply@skv.network>",
                "to": email,
                "subject": "SKV Network - Email Confirmation",
                "text": f"Your SKV confirmation code: {code}"
            },
            timeout=10
        )
        if resp.status_code == 200:
            print(f"[SKV] Email sent to {email}: {resp.json().get('id', 'ok')}")
            return True
        else:
            print(f"[SKV] Email error: {resp.status_code} {resp.text[:100]}")
            return False
    except Exception as e:
        print(f"[SKV] Email error for {email}: {e}")
        return False

@router.post("/api/auth/register")
async def register(request: Request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    password_hash = hash_password(password)
    confirmation_code = generate_code()

    try:
        conn = await get_db()
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if existing:
            await conn.close()
            raise HTTPException(status_code=409, detail="Email already registered")

        await conn.execute(
            "INSERT INTO users (email, password_hash, confirmation_code) VALUES ($1, $2, $3)",
            email, password_hash, confirmation_code
        )
        await conn.close()

        send_email(email, confirmation_code)
        return {"status": "ok", "message": "Confirmation code sent to email"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@router.post("/api/auth/confirm")
async def confirm(request: Request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip().upper()

    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and code required")

    try:
        conn = await get_db()
        user = await conn.fetchrow(
            "SELECT id, confirmation_code, confirmed FROM users WHERE email = $1", email
        )
        if not user:
            await conn.close()
            raise HTTPException(status_code=404, detail="User not found")
        if user["confirmed"]:
            await conn.close()
            return {"status": "ok", "message": "Already confirmed"}
        if user["confirmation_code"] != code:
            await conn.close()
            raise HTTPException(status_code=400, detail="Invalid confirmation code")

        await conn.execute("UPDATE users SET confirmed = TRUE, confirmation_code = NULL WHERE id = $1", user["id"])
        await conn.close()
        return {"status": "ok", "message": "Email confirmed"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])

@router.post("/api/auth/login")
async def login(request: Request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    password_hash = hash_password(password)

    try:
        conn = await get_db()
        user = await conn.fetchrow(
            "SELECT id, confirmed FROM users WHERE email = $1 AND password_hash = $2",
            email, password_hash
        )
        if not user:
            await conn.close()
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user["confirmed"]:
            await conn.close()
            raise HTTPException(status_code=403, detail="Email not confirmed")

        # Генерируем и сохраняем постоянный API-токен
        api_token = str(uuid.uuid4())
        await conn.execute("UPDATE users SET api_token = $1 WHERE id = $2", api_token, user["id"])
        await conn.close()
        return {"status": "ok", "api_token": api_token, "message": "Use this token in Authorization header to access your personal data."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
