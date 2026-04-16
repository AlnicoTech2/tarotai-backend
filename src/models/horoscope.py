import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, func, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class Horoscope(Base):
    __tablename__ = "horoscopes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sign: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # Aries, Taurus, etc.
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)  # YYYY-MM-DD
    horoscope_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
