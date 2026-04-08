import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class Reading(Base):
    __tablename__ = "readings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # Reading type
    spread_type: Mapped[str] = mapped_column(String(30), nullable=False)  # single, three_card, celtic_cross, yes_no, love, career
    question: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cards drawn (JSON array with position, card name, reversed flag)
    # Example: [{"position": "past", "card": "The Tower", "reversed": false}]
    cards: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # AI-generated reading narrative
    reading_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Vector embedding of the reading (for RAG memory — 1536 dim for OpenAI embeddings)
    embedding: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)

    # Context used for generation (for debugging / improving prompts)
    prompt_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Metadata
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
