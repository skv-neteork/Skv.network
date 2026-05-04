from fastapi import APIRouter, Request, HTTPException
import asyncpg
import os
import secrets
import hashlib
import smtplib
from email.mime.text import MIMEText
import threading

router = APIRouter()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://skv_user:skv_secret_2026@skv_postgres:5432/skv_db")

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

def hash_password(password: str) -> str:
    salt = os.getenv("SKV_SALT", "skv_default_salt_2026")
    return hashlib.sha256((password + salt).encode()).hexdigest()

def generate_code() -> str:
    return secrets.token_hex(3).upper()

def send_email_async(email: str, code: str):
    """Отправляет email в отдельном потоке, не блокируя API"""
    try:
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")

        if not smtp_host or not smtp_user:
            print(f"[SKV] SMTP not configured. Code for {email}: {code}")
            return

        msg = MIMEText(f"Your SKV confirmation code: {code}")
        msg["Subject"] = "SKV Network - Email Confirmation"
        msg["From"] = smtp_user
        msg["To"] = email

        server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"[SKV] Email sent to {email}")
    except Exception as e:
        print(f"[SKV] Email error for {email}: {e}")

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

        # Отправляем email в фоне, не блокируем ответ
        threading.Thread(target=send_email_async, args=(email, confirmation_code), daemon=True).start()

        return {
            "status": "ok",
            "message": "Check your email for confirmation code"
        }
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

        token = secrets.token_hex(16)
        await conn.close()
        return {"status": "ok", "token": token}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
