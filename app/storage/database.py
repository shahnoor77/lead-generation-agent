"""
Async database engine — PostgreSQL via asyncpg.
Connection URL is read from settings.database_url.
All tables are created on startup via init_db().
"""

from __future__ import annotations

from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # drop stale connections before use
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Tables carrying user_id FK — (table_name, user_id_is_primary_key)
_USER_ID_TABLES: list[tuple[str, bool]] = [
    ("user_settings", True),
    ("user_lead_configs", False),
    ("sender_email_accounts", False),
    ("outreach_sent", False),
    ("outreach_replies", False),
    ("meeting_handoffs", False),
    ("sandbox_test_inboxes", False),
    ("sandbox_lead_recipient_map", False),
    ("outreach_jobs", False),
    ("pipeline_runs", False),
]


async def _column_data_type(conn, table: str, column: str) -> str | None:
    result = await conn.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    row = result.first()
    return row[0] if row else None


async def _table_exists(conn, table: str) -> bool:
    result = await conn.execute(
        text("SELECT to_regclass(:name)"),
        {"name": f"public.{table}"},
    )
    return result.scalar() is not None


async def _migrate_users_to_uuid(conn) -> None:
    """One-time migration: integer users.id + user_id FKs → UUID strings."""
    users_id_type = await _column_data_type(conn, "users", "id")
    if users_id_type is None:
        return
    if users_id_type not in ("integer", "bigint", "smallint"):
        return

    logger.info("db.migrate_users_to_uuid.start")

    await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS id_uuid VARCHAR(36)"))
    await conn.execute(
        text("UPDATE users SET id_uuid = gen_random_uuid()::text WHERE id_uuid IS NULL")
    )

    for table, is_pk in _USER_ID_TABLES:
        if not await _table_exists(conn, table):
            continue
        col_type = await _column_data_type(conn, table, "user_id")
        if col_type is None:
            continue
        if col_type not in ("integer", "bigint", "smallint"):
            continue

        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id_uuid VARCHAR(36)"))
        await conn.execute(
            text(
                f"""
                UPDATE {table} AS t
                SET user_id_uuid = u.id_uuid
                FROM users AS u
                WHERE t.user_id IS NOT NULL AND t.user_id = u.id AND t.user_id_uuid IS NULL
                """
            )
        )
        if is_pk:
            await conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
        await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN user_id"))
        await conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN user_id_uuid TO user_id"))
        if is_pk:
            await conn.execute(text(f"ALTER TABLE {table} ADD PRIMARY KEY (user_id)"))
        else:
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table} (user_id)"))

    await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_pkey"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS hashed_password"))
    await conn.execute(text("ALTER TABLE users DROP COLUMN id"))
    await conn.execute(text("ALTER TABLE users RENAME COLUMN id_uuid TO id"))
    await conn.execute(text("ALTER TABLE users ADD PRIMARY KEY (id)"))

    # Restore uniqueness expected by models (dropped with old integer columns).
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_outreach_jobs_user_id "
            "ON outreach_jobs (user_id) WHERE user_id IS NOT NULL"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sandbox_inbox_user_email "
            "ON sandbox_test_inboxes (user_id, email)"
        )
    )
    await conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sandbox_map_user_lead "
            "ON sandbox_lead_recipient_map (user_id, lead_id)"
        )
    )

    logger.info("db.migrate_users_to_uuid.done")


async def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    import app.storage.models  # noqa: F401 — register SQLModel table metadata before create_all

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Lightweight forward-compatible migrations for outreach follow-up agent.
        await conn.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS outreach_followup_enabled BOOLEAN DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS outreach_reply_check_enabled BOOLEAN DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS outreach_followup_max_attempts INTEGER DEFAULT 4"))
        await conn.execute(text("ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS outreach_followup_interval_hours INTEGER DEFAULT 48"))
        await conn.execute(text("ALTER TABLE sender_email_accounts ADD COLUMN IF NOT EXISTS imap_host VARCHAR"))
        await conn.execute(text("ALTER TABLE sender_email_accounts ADD COLUMN IF NOT EXISTS imap_port INTEGER DEFAULT 993"))
        await conn.execute(text("ALTER TABLE sender_email_accounts ADD COLUMN IF NOT EXISTS imap_username VARCHAR"))
        await conn.execute(text("ALTER TABLE sender_email_accounts ADD COLUMN IF NOT EXISTS imap_password_encrypted VARCHAR"))
        await conn.execute(text("ALTER TABLE sender_email_accounts ADD COLUMN IF NOT EXISTS imap_use_ssl BOOLEAN DEFAULT TRUE"))
        await conn.execute(text("ALTER TABLE outreach_sent ADD COLUMN IF NOT EXISTS campaign_stage VARCHAR DEFAULT 'initial'"))
        await conn.execute(text("ALTER TABLE outreach_sent ADD COLUMN IF NOT EXISTS outbound_message_id VARCHAR"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_outreach_sent_outbound_message_id ON outreach_sent (outbound_message_id)"))
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS meeting_handoffs ("
            "id SERIAL PRIMARY KEY, user_id VARCHAR(36), lead_id VARCHAR, receiver_email VARCHAR, "
            "contact_name VARCHAR, contact_role VARCHAR, meeting_date VARCHAR, meeting_time VARCHAR, "
            "timezone VARCHAR, notes VARCHAR, raw_response VARCHAR, status VARCHAR DEFAULT 'pending_info', "
            "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        await conn.execute(text("ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS sandbox_outreach BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key_hash VARCHAR"))
        await conn.execute(text("ALTER TABLE users ALTER COLUMN email DROP NOT NULL"))
        await _migrate_users_to_uuid(conn)

