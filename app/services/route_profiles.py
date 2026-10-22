"""Perfiles de ruta curados (HU-022): se guardan y se leen de la base de datos."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RouteProfileRow
from app.schemas.route_profile import RouteProfile
from app.services import access


def all_profiles(db: Session) -> list[RouteProfile]:
    rows = db.scalars(select(RouteProfileRow).order_by(RouteProfileRow.slug))
    return [RouteProfile.model_validate_json(row.data) for row in rows]


def save(db: Session, profile: RouteProfile) -> None:
    """Crea o reemplaza el perfil con ese slug."""
    row = db.get(RouteProfileRow, profile.slug) or RouteProfileRow(slug=profile.slug)
    row.data = profile.model_dump_json()
    row.updated_at = access.utcnow()
    db.add(row)
    db.commit()


def delete(db: Session, slug: str) -> bool:
    row = db.get(RouteProfileRow, slug)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
