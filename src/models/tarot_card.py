import uuid

from sqlalchemy import String, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class TarotCard(Base):
    __tablename__ = "tarot_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name_short: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # e.g., "ar01" for The Magician
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    arcana: Mapped[str] = mapped_column(String(10), nullable=False)  # major / minor
    suit: Mapped[str | None] = mapped_column(String(20), nullable=True)  # wands, cups, swords, pentacles (null for major)

    # Meanings
    meaning_upright: Mapped[str] = mapped_column(Text, nullable=False)
    meaning_reversed: Mapped[str] = mapped_column(Text, nullable=False)
    keywords_upright: Mapped[list] = mapped_column(JSONB, nullable=False)  # ["freedom", "faith"]
    keywords_reversed: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Description and imagery
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Image
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # S3 + CloudFront URL
