import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Birth data
    date_of_birth: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    time_of_birth: Mapped[str] = mapped_column(String(5), nullable=False)  # HH:MM
    city_of_birth: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone_offset: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Astrology data (cached from Prokerala — calculated once at signup)
    birth_chart: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    zodiac_sign: Mapped[str | None] = mapped_column(String(20), nullable=True)
    moon_sign: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ascendant: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Subscription
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subscription_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)  # weekly/monthly/yearly
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Reading stats
    free_readings_used: Mapped[int] = mapped_column(default=0)
    free_readings_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
