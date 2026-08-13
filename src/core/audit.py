"""Writes audit_log rows. Deliberately minimal - a string event_type and
free-text detail, not a JSON blob - this is an access trail, not a
generic event bus."""

from sqlalchemy.orm import Session as DbSession

from core.models_db import AuditLogEntry


def log_event(db: DbSession, user_id: int, event_type: str, detail: str | None = None) -> None:
    db.add(AuditLogEntry(user_id=user_id, event_type=event_type, detail=detail))
    db.commit()
