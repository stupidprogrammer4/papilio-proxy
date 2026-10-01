from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.infra.db.models import Base


class WebAdminAccountModel(Base):
    """A salted password verifier, never a reversible admin password."""

    __tablename__ = "web_admin_accounts"

    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    password_salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )


class WebAdminSessionModel(Base):
    """Revocable server-side session; only a digest of the cookie is stored."""

    __tablename__ = "web_admin_sessions"

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(64), ForeignKey("web_admin_accounts.username", ondelete="CASCADE")
    )
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())
