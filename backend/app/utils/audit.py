"""Structured audit logging helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

audit_logger = logging.getLogger("app.audit")


def _to_serializable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_serializable(v) for v in value]
    return str(value)


def log_audit_event(
    event_type: str,
    *,
    actor: Any = None,
    details: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
    }

    if actor is not None:
        actor_id = getattr(actor, "id", None)
        actor_org_id = getattr(actor, "organization_id", None)
        payload.update(
            {
                "actor_id": str(actor_id) if actor_id else None,
                "actor_email": getattr(actor, "email", None),
                "actor_role": getattr(actor, "role", None),
                "actor_organization_id": str(actor_org_id) if actor_org_id else None,
            }
        )

    if details:
        payload["details"] = _to_serializable(details)

    audit_logger.info(json.dumps(payload, ensure_ascii=True))
