"""Create the first administrator from deployment-provided credentials.

Existing installations are left untouched: bootstrap settings are only required
when the users table is empty.
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Executed as scripts/bootstrap_admin.py[c] by the container entrypoint.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.auth.jwt import hash_password
from app.database import async_session
from app.models.user import Organization, User


MIN_ADMIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class AdminBootstrapConfig:
    email: str
    password: str
    name: str


def load_admin_bootstrap_config(
    environ: Mapping[str, str] | None = None,
) -> AdminBootstrapConfig:
    """Load and validate first-admin settings without exposing the password."""
    values = environ if environ is not None else os.environ
    email = values.get("ADMIN_EMAIL", "").strip()
    password = values.get("ADMIN_PASSWORD", "")
    name = values.get("ADMIN_NAME", "관리자").strip() or "관리자"
    allow_weak = values.get("ALLOW_WEAK_ADMIN_PASSWORD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    missing = [
        key
        for key, value in (("ADMIN_EMAIL", email), ("ADMIN_PASSWORD", password))
        if not value
    ]
    if missing:
        raise ValueError(
            "First administrator is not configured. Set " + ", ".join(missing) + "."
        )

    if len(email) > 255:
        raise ValueError("ADMIN_EMAIL must be 255 characters or fewer.")
    if len(name) > 100:
        raise ValueError("ADMIN_NAME must be 100 characters or fewer.")
    if not allow_weak:
        if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
            raise ValueError(
                f"ADMIN_PASSWORD must be at least {MIN_ADMIN_PASSWORD_LENGTH} characters."
            )
        normalized_password = password.lower().replace("_", "-")
        insecure_markers = ("change-this", "your-password", "example-password")
        if any(marker in normalized_password for marker in insecure_markers):
            raise ValueError("ADMIN_PASSWORD still contains a placeholder value.")

    return AdminBootstrapConfig(email=email, password=password, name=name)


async def bootstrap_admin() -> bool:
    """Create the first admin and return True, or skip an existing install."""
    async with async_session() as session:
        user_count = await session.scalar(select(func.count()).select_from(User))
        if user_count:
            print(f"    Administrator bootstrap skipped ({user_count} users exist).")
            return False

        config = load_admin_bootstrap_config()

        organization = await session.scalar(select(Organization).limit(1))
        if organization is None:
            organization = Organization(
                name="기본 조직",
                quota_storage_gb=10000,
                quota_projects=1000,
            )
            session.add(organization)
            await session.flush()

        session.add(
            User(
                email=config.email,
                password_hash=hash_password(config.password),
                name=config.name,
                role="admin",
                is_active=True,
                organization_id=organization.id,
            )
        )
        await session.commit()
        print(f"    Initial administrator created: {config.email}")
        return True


if __name__ == "__main__":
    asyncio.run(bootstrap_admin())
