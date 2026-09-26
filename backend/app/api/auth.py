from datetime import UTC, datetime, timedelta
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.database import connection
from app.security import hash_password, new_token, session_expiry, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["authentication"])


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class Signup(Credentials):
    name: str = Field(min_length=2, max_length=80)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=80)


class PasswordUpdate(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def user_payload(row: sqlite3.Row) -> dict[str, object]:
    return {"id": row["id"], "name": row["name"], "email": row["email"], "created_at": row["created_at"]}


def get_current_user(request: Request) -> dict[str, object]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    with connection() as db:
        row = db.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                          WHERE s.token_hash=? AND s.expires_at>?""", (token_hash(header[7:]), datetime.now(UTC).isoformat())).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Your session has expired. Please log in again.")
    return user_payload(row)


def account_payload(user: dict[str, object]) -> dict[str, object]:
    with connection() as db:
        sub = db.execute("""SELECT p.name, s.status, s.trial_ends_at FROM subscriptions s
                            JOIN plans p ON p.id=s.plan_id WHERE s.user_id=?""", (user["id"],)).fetchone()
    return {**user, "subscription": dict(sub) if sub else None}


def issue_session(user: dict[str, object]) -> dict[str, object]:
    token = new_token()
    with connection() as db:
        db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)", (token_hash(token), user["id"], session_expiry()))
    return {"token": token, "user": account_payload(user)}


@router.get("/plans")
def list_plans() -> dict[str, object]:
    """Expose the real plan catalogue without claiming that billing is active."""
    with connection() as db:
        rows = db.execute(
            "SELECT id, name, description, monthly_price_cents FROM plans ORDER BY id"
        ).fetchall()
    return {"plans": [dict(row) for row in rows]}


@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(data: Signup) -> dict[str, object]:
    if "@" not in data.email:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    with connection() as db:
        try:
            cursor = db.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)", (data.name.strip(), data.email.lower(), hash_password(data.password)))
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="An account with this email already exists.") from error
        user = {"id": cursor.lastrowid, "name": data.name.strip(), "email": data.email.lower(), "created_at": datetime.now(UTC).isoformat()}
        trial_end = (datetime.now(UTC) + timedelta(days=14)).isoformat()
        db.execute("INSERT INTO subscriptions (user_id, plan_id, status, trial_ends_at) VALUES (?, 1, 'trial', ?)", (user["id"], trial_end))
    return issue_session(user)


@router.post("/login")
def login(data: Credentials) -> dict[str, object]:
    with connection() as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (data.email.lower(),)).fetchone()
    if not row or not verify_password(data.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return issue_session(user_payload(row))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: dict[str, object] = Depends(get_current_user)) -> None:
    token = request.headers.get("Authorization", "")[7:]
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))


@router.get("/me")
def me(user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    return account_payload(user)


@router.put("/profile")
def update_profile(data: ProfileUpdate, user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    with connection() as db:
        db.execute("UPDATE users SET name=? WHERE id=?", (data.name.strip(), user["id"]))
    return account_payload({**user, "name": data.name.strip()})


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def update_password(data: PasswordUpdate, user: dict[str, object] = Depends(get_current_user)) -> None:
    with connection() as db:
        row = db.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row or not verify_password(data.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(data.new_password), user["id"]))
