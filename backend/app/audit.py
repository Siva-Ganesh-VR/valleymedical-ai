"""Append-only, hash-chained audit logger.

Each event stores the hash of the previous event, so any edit or deletion of an earlier row
breaks the chain and is detected by verify_chain(). Details hold references and counts,
never clinical free text.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, utcnow_iso
from app.security import Actor

GENESIS_HASH = "0" * 64
_HASHED_FIELDS = (
    "ts", "actor", "actor_role", "action", "entity_type", "entity_id",
    "patient_ref", "purpose", "detail", "model", "prompt_version", "prev_hash",
)


def _digest(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AuditLogger:
    def __init__(self, session: Session):
        self._session = session

    def record(
        self,
        *,
        actor: Actor,
        action: str,
        entity_type: str,
        entity_id: str,
        patient_ref: str | None = None,
        purpose: str | None = None,
        detail: dict | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> AuditEvent:
        last = self._session.scalars(
            select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)
        ).first()
        fields = {
            "ts": utcnow_iso(),
            "actor": actor.username,
            "actor_role": actor.role.value,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "patient_ref": patient_ref,
            "purpose": purpose,
            "detail": detail or {},
            "model": model,
            "prompt_version": prompt_version,
            "prev_hash": last.hash if last else GENESIS_HASH,
        }
        event = AuditEvent(**fields, hash=_digest(fields))
        self._session.add(event)
        self._session.flush()
        return event


@dataclass
class ChainVerification:
    ok: bool
    checked: int
    first_invalid_id: int | None = None


def verify_chain(session: Session) -> ChainVerification:
    prev = GENESIS_HASH
    checked = 0
    for event in session.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        fields = {name: getattr(event, name) for name in _HASHED_FIELDS}
        if event.prev_hash != prev or _digest(fields) != event.hash:
            return ChainVerification(ok=False, checked=checked, first_invalid_id=event.id)
        prev = event.hash
        checked += 1
    return ChainVerification(ok=True, checked=checked)
