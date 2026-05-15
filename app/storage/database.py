"""
Async database engine — PostgreSQL via asyncpg.
Connection URL is read from settings.database_url.
All tables are created on startup via init_db().
"""

from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings

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
        await conn.execute(text("CREATE TABLE IF NOT EXISTS meeting_handoffs (id SERIAL PRIMARY KEY, user_id INTEGER, lead_id VARCHAR, receiver_email VARCHAR, contact_name VARCHAR, contact_role VARCHAR, meeting_date VARCHAR, meeting_time VARCHAR, timezone VARCHAR, notes VARCHAR, raw_response VARCHAR, status VARCHAR DEFAULT 'pending_info', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        await conn.execute(text("ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS sandbox_outreach BOOLEAN DEFAULT FALSE"))
