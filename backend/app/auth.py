"""Authentication & roles (demo-mode local login).

Two roles: "admin" (full platform) and "user" (bound to a team —
decide, deploy within the team's guardrails, integrate with own keys).
Role checks are enforced at the API, not just hidden in the UI.

Identity is deliberately swappable: sessions are issued here from a
local user table for demo installs; production replaces login with
Keycloak/OIDC while keeping the same session layer and role model.

Demo credentials (override via env): admin / ADMIN_PASSWORD
(default "modelect-admin"); one user per team, username = team id,
password USER_PASSWORD (default "modelect-user").
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import insert, select

from .db import DATA_DIR, engine, users_t

SESSION_TTL = 12 * 3600
COOKIE_NAME = "modelect_session"

_TEAM_USERS = ["support-bot", "doc-pipeline", "research-agents", "intern-sandbox"]


def _secret() -> bytes:
    """Signing key persisted in the data dir (PVC) so sessions survive
    restarts; regenerated only if missing."""
    path = os.path.join(DATA_DIR, "secret.key")
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        with open(path, "wb") as f:
            f.write(key)
        return key


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def seed():
    with engine.begin() as conn:
        existing = {r.username for r in conn.execute(select(users_t.c.username))}
        rows = []
        if "admin" not in existing:
            salt = secrets.token_hex(16)
            rows.append({"username": "admin", "salt": salt,
                         "password_hash": _hash(os.environ.get("ADMIN_PASSWORD", "modelect-admin"), salt),
                         "role": "admin", "team_id": None})
        for team in _TEAM_USERS:
            if team not in existing:
                salt = secrets.token_hex(16)
                rows.append({"username": team, "salt": salt,
                             "password_hash": _hash(os.environ.get("USER_PASSWORD", "modelect-user"), salt),
                             "role": "user", "team_id": team})
        if rows:
            conn.execute(insert(users_t), rows)


def login(username: str, password: str) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(users_t)
                           .where(users_t.c.username == username)).mappings().first()
    if row is None:
        return None
    if not hmac.compare_digest(row["password_hash"], _hash(password, row["salt"])):
        return None
    return {"username": row["username"], "role": row["role"], "team_id": row["team_id"]}


def issue_token(user: dict) -> str:
    payload = {"u": user["username"], "r": user["role"], "t": user["team_id"],
               "exp": int(time.time()) + SESSION_TTL}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return {"username": payload["u"], "role": payload["r"], "team_id": payload["t"]}


def session_user(request: Request) -> dict | None:
    return verify_token(request.cookies.get(COOKIE_NAME))


# (method, path-prefix) pairs only admins may call
ADMIN_RULES = [
    ("PUT", "/api/config"),
    ("PUT", "/api/teams/"),
    ("POST", "/api/registry/sync"),
    ("GET", "/api/tokenomics"),
    ("DELETE", "/api/deployments/"),
]


def authorize(request: Request) -> dict:
    """Session + role gate for portal APIs. Raises 401/403."""
    user = session_user(request)
    if user is None:
        raise HTTPException(401, "not authenticated")
    if user["role"] != "admin":
        for method, prefix in ADMIN_RULES:
            if request.method == method and request.url.path.startswith(prefix):
                raise HTTPException(403, "admin access required")
    return user


seed()
