from fastapi import APIRouter, Request, HTTPException
import asyncpg
import os
import secrets
import uuid
import requests

from app.security import (
    get_database_url,
    get_resend_api_key,
    hash_password,
    verify_password,
    needs_rehash,
    generate_confirmation_code,
    generate_api_token,
    constant_time_equals,
)

router = APIRouter()

DATABASE_URL = get_database_url()


async def get_db():
    url = get_database_url()
    if not url:
        raise HTTPException(status_code=503, detail="Database not configured")
    return await asyncpg.connect(url)


def send_email(email: str, code: str) -> bool:
    resend_key = get_resend_api_key()
    if not resend_key:
        # Never log full code in production if possible; log only that email was queued.
        print(f"[SKV] RESEND_API_KEY not set — confirmation email not sent for {email}")
        return False
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
                "User-Agent": "SKV-Network/2.0",
            },
            json={
                "from": "SKV Network <noreply@skv.network>",
                "to": email,
                "subject": "SKV Network - Email Confirmation",
                "text": f"Your SKV confirmation code: {code}",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"[SKV] Email sent to {email}: {resp.json().get('id', 'ok')}")
            return True
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

    if not email or "@" not in email or len(email) > 254:
        raise HTTPException(status_code=400, detail="Valid email required")
    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if len(password) > 256:
        raise HTTPException(status_code=400, detail="Password too long")

    password_hash = hash_password(password)
    confirmation_code = generate_confirmation_code(3)
    api_token = generate_api_token()

    conn = None
    try:
        conn = await get_db()
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        await conn.execute(
            "INSERT INTO users (email, password_hash, confirmation_code) VALUES ($1, $2, $3)",
            email, password_hash, confirmation_code,
        )
        await conn.execute(
            "INSERT INTO user_api_keys (user_id, api_key) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
            email, api_token,
        )

        # Do not return API key before email confirmation.
        emailed = send_email(email, confirmation_code)
        return {
            "status": "ok",
            "message": "Confirmation code sent to email" if emailed else "Registered. Check email for confirmation code.",
            "email_sent": emailed,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration error: {str(e)[:200]}")
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass


@router.post("/api/auth/confirm")
async def confirm(request: Request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip().upper()

    if not email or not code:
        raise HTTPException(status_code=400, detail="Email and code required")

    conn = None
    try:
        conn = await get_db()
        user = await conn.fetchrow(
            "SELECT id, confirmation_code, confirmed FROM users WHERE email = $1", email
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user["confirmed"]:
            return {"status": "ok", "message": "Already confirmed"}
        if not user["confirmation_code"] or not constant_time_equals(
            str(user["confirmation_code"]).upper(), code
        ):
            raise HTTPException(status_code=400, detail="Invalid confirmation code")

        await conn.execute(
            "UPDATE users SET confirmed = TRUE, confirmation_code = NULL WHERE id = $1",
            user["id"],
        )
        row = await conn.fetchrow(
            "SELECT api_key FROM user_api_keys WHERE user_id = $1", email
        )
        api_key = row["api_key"] if row else None
        if not api_key:
            api_key = generate_api_token()
            await conn.execute(
                "INSERT INTO user_api_keys (user_id, api_key) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET api_key = $2",
                email, api_key,
            )
        return {"status": "ok", "message": "Email confirmed", "api_key": api_key}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass


@router.post("/api/auth/login")
async def login(request: Request):
    data = await request.json()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    conn = None
    try:
        conn = await get_db()
        user = await conn.fetchrow(
            "SELECT id, confirmed, password_hash FROM users WHERE email = $1",
            email,
        )
        if not user or not verify_password(password, user["password_hash"] or ""):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user["confirmed"]:
            raise HTTPException(status_code=403, detail="Email not confirmed")

        # Upgrade legacy weak hashes on successful login
        if needs_rehash(user["password_hash"] or ""):
            try:
                await conn.execute(
                    "UPDATE users SET password_hash = $1 WHERE id = $2",
                    hash_password(password),
                    user["id"],
                )
            except Exception as e:
                print(f"[SKV] password rehash failed: {e}")

        api_token = generate_api_token()
        await conn.execute(
            "INSERT INTO user_api_keys (user_id, api_key) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET api_key = $2",
            email, api_token,
        )

        return {"status": "ok", "api_token": api_token, "email": email}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:200])
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass
