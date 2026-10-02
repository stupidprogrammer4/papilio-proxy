from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from papilio_proxy.config.database import Base


class BotBrandingModel(Base):
    __tablename__ = "bot_branding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    short_description: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(512))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), onupdate=func.current_timestamp()
    )
