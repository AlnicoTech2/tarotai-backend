import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # "reading" (linked to a reading), "persona" (direct chat), "yes_no"
    session_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # For reading sessions: the reading ID. For persona sessions: persona_id string.
    reference_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # Summarized context from older messages (after 20-message cap)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    message_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False, index=True)

    # "user" or "ai"
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
