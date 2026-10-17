"""Sesión del panel de administración (HU-046).

Mismo esquema que el panel de finanzas: contraseña con Argon2, token de acceso
JWT de 15 minutos en el encabezado `Authorization` y refresh token aleatorio en
una cookie HttpOnly. De los refresh tokens solo se guarda el hash.
"""

from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AdminSession, AdminUser
from app.db.session import get_db
from app.services.access import hash_token, new_token, utcnow

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
REFRESH_COOKIE = "lazarus_admin_refresh"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False


def bootstrap_admin(db: Session) -> None:
    """Crea el primer administrador desde ADMIN_USERNAME y ADMIN_PASSWORD."""
    if not settings.admin_username or not settings.admin_password:
        return
    if db.scalar(select(AdminUser).limit(1)) is not None:
        return
    db.add(
        AdminUser(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
        )
    )
    db.commit()


def _secret() -> str:
    # HS256 pide una clave de al menos 32 bytes (RFC 7518, sección 3.2).
    if len(settings.admin_jwt_secret) < 32:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Panel sin configurar")
    return settings.admin_jwt_secret


def access_token(admin: AdminUser) -> str:
    now = utcnow()
    payload = {"sub": str(admin.id), "typ": "access", "iat": now, "exp": now + ACCESS_TTL}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def new_refresh(db: Session, admin: AdminUser) -> str:
    token = new_token()
    db.add(
        AdminSession(
            admin_id=admin.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + REFRESH_TTL,
        )
    )
    db.commit()
    return token


def use_refresh(db: Session, token: str | None) -> AdminUser | None:
    """Admin dueño de un refresh token vigente (y lo rota: el viejo se revoca)."""
    if not token:
        return None
    row = db.scalar(select(AdminSession).where(AdminSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at < utcnow():
        return None
    row.revoked_at = utcnow()
    db.add(row)
    db.commit()
    return db.get(AdminUser, row.admin_id)


def revoke_refresh(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(select(AdminSession).where(AdminSession.token_hash == hash_token(token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        db.add(row)
        db.commit()


def current_admin(
    authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> AdminUser:
    """Dependencia de las rutas del panel: exige un token de acceso válido."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token")
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido") from exc
    if payload.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    admin = db.get(AdminUser, int(payload["sub"]))
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido")
    return admin
