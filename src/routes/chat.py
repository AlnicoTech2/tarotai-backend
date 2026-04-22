"""Chat persistence — sessions, messages, summarization.

Sessions are linked to readings (reading_id) or personas (persona_id).
Messages are capped at 20 per session — after 20, older messages are
summarized into session.summary_text and deleted.
Sessions older than 30 days are auto-deleted via cron.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from src.core.limiter import limiter
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.models.chat import ChatSession, ChatMessage

log = logging.getLogger("chat")

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_MESSAGES_PER_SESSION = 20


# ─── Schemas ───

class SendMessageRequest(BaseModel):
    session_type: str  # "reading", "persona", "yes_no"
    reference_id: str  # reading UUID or persona ID
    message: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: str
    session_type: str
    reference_id: str
    summary_text: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    session: SessionOut
    messages: list[MessageOut]


# ─── Get or create session ───

async def _get_or_create_session(
    db: AsyncSession, user_id: UUID, session_type: str, reference_id: str
) -> ChatSession:
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.session_type == session_type,
            ChatSession.reference_id == reference_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        session = ChatSession(
            user_id=user_id,
            session_type=session_type,
            reference_id=reference_id,
            message_count=0,
        )
        db.add(session)
        await db.flush()
    return session


# ─── Summarize old messages ───

async def _summarize_and_trim(db: AsyncSession, session: ChatSession):
    """When messages exceed cap, summarize older ones and delete them."""
    if session.message_count < MAX_MESSAGES_PER_SESSION:
        return

    # Get all messages ordered by time
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()

    if len(messages) <= MAX_MESSAGES_PER_SESSION:
        return

    # Keep last 5, summarize the rest
    to_summarize = messages[:-5]
    to_keep = messages[-5:]

    # Build summary text from old messages
    summary_parts = []
    if session.summary_text:
        summary_parts.append(f"Previous context: {session.summary_text}")
    for msg in to_summarize:
        prefix = "User asked" if msg.role == "user" else "AI answered"
        # Only store first 100 chars of each message for summary
        summary_parts.append(f"{prefix}: {msg.content[:100]}")

    session.summary_text = " | ".join(summary_parts)[-1000:]  # Cap summary at 1000 chars
    session.message_count = len(to_keep)

    # Delete old messages
    old_ids = [m.id for m in to_summarize]
    await db.execute(
        delete(ChatMessage).where(ChatMessage.id.in_(old_ids))
    )
    await db.flush()
    log.info(f"Summarized {len(to_summarize)} messages for session {session.id}")


# ─── Save initial reading messages ───

@limiter.limit("30/minute")
@router.post("/save-reading")
async def save_reading_messages(
    request: Request,
    body: dict,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the initial reading + AI response as chat messages."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session_type = body.get("session_type", "reading")
    reference_id = body.get("reference_id", "")
    messages = body.get("messages", [])

    session = await _get_or_create_session(db, user.id, session_type, reference_id)

    for msg in messages:
        chat_msg = ChatMessage(
            session_id=session.id,
            role=msg.get("role", "user"),
            content=msg.get("content", ""),
        )
        db.add(chat_msg)
        session.message_count += 1

    await db.commit()
    return {"session_id": str(session.id), "message_count": session.message_count}


# ─── Send message in session ───

@limiter.limit("30/minute")
@router.post("/send")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a user message, get AI response, save both to session."""
    from src.services.reading_service import (
        build_persona_chat_prompt,
        build_system_prompt,
        llm_followup,
        get_past_reading_context,
        PERSONA_PROMPTS,
    )
    from src.models.reading import Reading
    from langchain_core.messages import SystemMessage, HumanMessage

    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session = await _get_or_create_session(
        db, user.id, body.session_type, body.reference_id
    )

    # Save user message
    user_msg = ChatMessage(
        session_id=session.id, role="user", content=body.message
    )
    db.add(user_msg)
    session.message_count += 1

    # Build context
    user_language = getattr(user, "language", None) or "en"

    # Get conversation history for context
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
    )
    recent_msgs = list(reversed(result.scalars().all()))

    # Build conversation context
    context_parts = [f"User: {user.name}"]
    if user.zodiac_sign:
        context_parts.append(f"Sun sign: {user.zodiac_sign}")
    if user.moon_sign:
        context_parts.append(f"Moon sign: {user.moon_sign}")

    # Add summary if exists
    if session.summary_text:
        context_parts.append(f"\nConversation summary: {session.summary_text}")

    # Add reading context if it's a reading session
    if body.session_type == "reading":
        try:
            reading_result = await db.execute(
                select(Reading).where(Reading.id == UUID(body.reference_id))
            )
            reading = reading_result.scalar_one_or_none()
            if reading:
                cards_str = ", ".join(
                    f"{c['card']} ({'reversed' if c.get('reversed') else 'upright'}) in {c['position']}"
                    for c in reading.cards
                )
                context_parts.append(f"\nOriginal reading cards: {cards_str}")
                context_parts.append(f"Original reading: {reading.reading_text[:300]}")
        except Exception:
            pass

    # Add recent messages
    context_parts.append("\nRecent conversation:")
    for msg in recent_msgs[-8:]:  # Last 8 messages for context
        prefix = "User" if msg.role == "user" else "AI"
        context_parts.append(f"{prefix}: {msg.content[:200]}")

    context_parts.append(f"\nNew question: {body.message}")

    # Pick system prompt based on session type
    if body.session_type == "persona" and body.reference_id in PERSONA_PROMPTS:
        system_prompt = build_persona_chat_prompt(user_language, body.reference_id)
    else:
        system_prompt = build_system_prompt(user_language)

    # Generate response
    messages_for_llm = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n".join(context_parts)),
    ]
    response = await llm_followup.ainvoke(messages_for_llm)
    ai_text = response.content

    # Save AI response
    ai_msg = ChatMessage(
        session_id=session.id, role="ai", content=ai_text
    )
    db.add(ai_msg)
    session.message_count += 1

    # Check if we need to summarize
    await _summarize_and_trim(db, session)

    await db.commit()

    return {
        "response": ai_text,
        "session_id": str(session.id),
        "message_count": session.message_count,
    }


# ─── Get chat history ───

@router.get("/history/{session_type}/{reference_id}")
async def get_chat_history(
    session_type: str,
    reference_id: str,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get chat history for a session."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(ChatSession).where(
            ChatSession.user_id == user.id,
            ChatSession.session_type == session_type,
            ChatSession.reference_id == reference_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"session": None, "messages": []}

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()

    return {
        "session": {
            "id": str(session.id),
            "session_type": session.session_type,
            "reference_id": session.reference_id,
            "summary_text": session.summary_text,
            "message_count": session.message_count,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        },
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


# ─── List user sessions ───

@router.get("/sessions")
async def list_sessions(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all active chat sessions for the user."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    )
    sessions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "session_type": s.session_type,
            "reference_id": s.reference_id,
            "message_count": s.message_count,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]
