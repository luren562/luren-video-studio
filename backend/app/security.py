from datetime import datetime, timedelta, timezone

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from .config import get_settings


password_hash = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expires},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    settings = get_settings()
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return verify_token(credentials.credentials)


def verify_token(token: str) -> str:
    """校验 JWT 并返回 subject。供无法带 Authorization 头的通道（SSE 用 query token）复用。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if payload.get("sub") != settings.admin_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload["sub"]


def require_admin_flexible(
    request: Request,
    token: str | None = Query(default=None, description="媒体/SSE 等无法带 Authorization 头的通道用 query token"),
) -> str:
    """优先 Authorization: Bearer；否则回退 ?token= —— 供 <video>/<img>/<a> 直链复用。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return verify_token(auth[7:].strip())
    if token:
        return verify_token(token)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def encrypt_string(value: str) -> str:
    return Fernet(get_settings().effective_fernet_key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_string(token: str) -> str:
    try:
        return Fernet(get_settings().effective_fernet_key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt protected value") from exc
