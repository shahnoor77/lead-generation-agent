#!/usr/bin/env python3
"""
Provision an API user (UUID). Run from repo root:

  set PYTHONPATH=.
  python scripts/create_api_user.py --email you@company.com

Uses OPERATOR_API_KEY from .env for authentication (shared across all users).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import settings
from app.storage.database import init_db
from app.services.auth import provision_user


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Create operator UUID (shared OPERATOR_API_KEY from .env)")
    parser.add_argument("--email", type=str, default=None, help="Optional label email for this user")
    args = parser.parse_args()

    await init_db()
    user = await provision_user(email=args.email)
    print("User provisioned successfully.")
    print(f"  user_id (UUID): {user.id}")
    if user.email:
        print(f"  email:          {user.email}")
    print()
    print("Use these HTTP headers on every API request:")
    print(f"  X-User-Id: {user.id}")
    print("  X-Api-Key: <OPERATOR_API_KEY from your .env>")


def main() -> None:
    if not (settings.operator_api_key or "").strip():
        print("Error: set OPERATOR_API_KEY in .env before provisioning users.", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
