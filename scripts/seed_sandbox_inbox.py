#!/usr/bin/env python3
"""
Insert sandbox test inbox address(es) for outreach test mode (SMTP redirects here).

Sandbox rows are per user. By default attaches to the first user in `users`; override with flags.

Examples (from repo root):
  PYTHONPATH=. python scripts/seed_sandbox_inbox.py shahnoorr9955@gmail.com
  PYTHONPATH=. python scripts/seed_sandbox_inbox.py --user-id 2 a@test.com b@test.com
  PYTHONPATH=. python scripts/seed_sandbox_inbox.py --user-email operator@corp.com shahnoorr9955@gmail.com
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Repo root on path for `app.*` imports
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.storage.database import AsyncSessionLocal, init_db
from app.storage.models import SandboxTestInboxRecord, UserRecord


async def _resolve_user_id(session, user_id: int | None, login_email: str | None) -> int:
    if user_id is not None:
        u = await session.get(UserRecord, user_id)
        if not u:
            raise SystemExit(f"No user with id={user_id}")
        return u.id  # type: ignore[return-value]
    if login_email:
        r = await session.execute(select(UserRecord).where(UserRecord.email == login_email.strip().lower()))
        u = r.scalar_one_or_none()
        if not u:
            raise SystemExit(f"No user with email={login_email!r}")
        return u.id  # type: ignore[return-value]
    r = await session.execute(select(UserRecord).order_by(UserRecord.id.asc()).limit(1))
    u = r.scalar_one_or_none()
    if not u:
        raise SystemExit("No users in database — sign up first, then rerun this script.")
    print(f"[seed_sandbox_inbox] Using user id={u.id} email={u.email}")
    return u.id


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Add sandbox recipient inbox(es) for test outreach routing.")
    parser.add_argument(
        "emails",
        nargs="*",
        default=["shahnoorr9955@gmail.com"],
        help="Sandbox inbox emails (normalized to lowercase).",
    )
    parser.add_argument("--user-id", type=int, default=None, help="Target user PK (sandbox rows are per user).")
    parser.add_argument(
        "--user-email",
        type=str,
        default=None,
        help="Target user login email instead of --user-id.",
    )
    args = parser.parse_args()

    await init_db()
    emails = [e.strip().lower() for e in args.emails if e and str(e).strip()]
    if not emails:
        raise SystemExit("No emails provided.")

    async with AsyncSessionLocal() as session:
        uid = await _resolve_user_id(session, args.user_id, args.user_email)
        added = 0
        skipped = 0
        for em in emails:
            existing = (
                await session.execute(
                    select(SandboxTestInboxRecord).where(
                        SandboxTestInboxRecord.user_id == uid,
                        SandboxTestInboxRecord.email == em,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    session.add(existing)
                print(f"[seed_sandbox_inbox] Already present: {em!r}")
                skipped += 1
                continue
            session.add(
                SandboxTestInboxRecord(user_id=uid, email=em, is_active=True),
            )
            try:
                await session.commit()
                print(f"[seed_sandbox_inbox] Added sandbox inbox for user {uid}: {em}")
                added += 1
            except IntegrityError:
                await session.rollback()
                print(f"[seed_sandbox_inbox] Conflict (skipped): {em!r}")
                skipped += 1

    print(f"[seed_sandbox_inbox] done: added={added}, skipped/existing={skipped}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
