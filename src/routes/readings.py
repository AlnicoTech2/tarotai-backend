from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.middleware.auth import get_current_user
from src.models.reading import Reading
from src.models.user import User
from src.schemas.reading import ReadingRequest, ReadingResponse, ReadingHistoryItem
from src.services.card_service import draw_cards, SPREAD_POSITIONS
from src.services.reading_service import generate_reading

router = APIRouter(prefix="/readings", tags=["readings"])

FREE_MONTHLY_LIMIT = 3  # Free users get 3 readings/month. Admins/premium = unlimited.


@router.post("/", response_model=ReadingResponse, status_code=status.HTTP_201_CREATED)
async def create_reading(
    body: ReadingRequest,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Draw cards and generate an AI reading."""
    if body.spread_type not in SPREAD_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Invalid spread type. Options: {list(SPREAD_POSITIONS.keys())}")

    # Get user
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Auto-downgrade: if subscription expired, revoke premium
    if user.is_premium and not user.is_admin and user.subscription_expires_at:
        if user.subscription_expires_at < datetime.now(timezone.utc):
            user.is_premium = False
            user.subscription_plan = None

    # Admin/premium users — unlimited readings
    if not user.is_premium and not user.is_admin:
        now = datetime.now(timezone.utc)

        # Reset counter if new month
        if user.free_readings_reset_at is None or user.free_readings_reset_at.month != now.month:
            user.free_readings_used = 0
            user.free_readings_reset_at = now

        if user.free_readings_used >= FREE_MONTHLY_LIMIT:
            raise HTTPException(
                status_code=403,
                detail="Free reading limit reached. Upgrade to premium for unlimited readings.",
            )

        user.free_readings_used += 1

    # Draw cards
    cards = await draw_cards(db, body.spread_type)

    # Generate AI reading
    import logging
    logger = logging.getLogger(__name__)
    try:
        reading = await generate_reading(
            db=db,
            user=user,
            cards=cards,
            question=body.question,
            spread_type=body.spread_type,
        )
        return reading
    except Exception as e:
        logger.error(f"Reading generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=list[ReadingHistoryItem])
async def get_reading_history(
    limit: int = 20,
    offset: int = 0,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's reading history."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(Reading)
        .where(Reading.user_id == user.id)
        .order_by(Reading.created_at.desc())
        .limit(min(limit, 50))
        .offset(offset)
    )
    readings = result.scalars().all()
    return readings


@router.get("/today-single", response_model=ReadingResponse)
async def get_today_single_reading(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get today's single card reading if it exists."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    today = datetime.now(timezone.utc).date()
    result = await db.execute(
        select(Reading)
        .where(
            Reading.user_id == user.id,
            Reading.spread_type == "single",
            func.date(Reading.created_at) == today,
        )
        .order_by(Reading.created_at.desc())
        .limit(1)
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="No daily reading yet")

    return reading


@router.get("/today-three-card", response_model=ReadingResponse)
async def get_today_three_card_reading(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get today's three-card reading if it exists."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    today = datetime.now(timezone.utc).date()
    result = await db.execute(
        select(Reading)
        .where(
            Reading.user_id == user.id,
            Reading.spread_type == "three_card",
            func.date(Reading.created_at) == today,
        )
        .order_by(Reading.created_at.desc())
        .limit(1)
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="No three-card reading today")

    return reading


class FollowUpRequest(BaseModel):
    question: str


class FollowUpResponse(BaseModel):
    reading_text: str


@router.post("/{reading_id}/followup", response_model=FollowUpResponse)
async def followup_reading(
    reading_id: UUID,
    body: FollowUpRequest,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask a follow-up question about an existing reading, using the same cards."""
    from src.services.reading_service import (
        build_reading_prompt,
        build_system_prompt,
        llm_followup,
        get_past_reading_context,
    )
    from langchain_core.messages import SystemMessage, HumanMessage

    # Get user
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get original reading
    result = await db.execute(
        select(Reading).where(Reading.id == reading_id, Reading.user_id == user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Reading not found")

    # Build prompt with original cards + new question
    past_context = await get_past_reading_context(db, user.id)

    # Reconstruct cards with keywords (not stored in DB, but card name is enough)
    cards_for_prompt = [
        {
            "position": c["position"],
            "card": c["card"],
            "reversed": c.get("reversed", False),
            "keywords_upright": [],
            "keywords_reversed": [],
        }
        for c in original.cards
    ]

    user_prompt = build_reading_prompt(
        user, cards_for_prompt, body.question, original.spread_type, past_context
    )
    # Add original reading context
    user_prompt += f"\n\nPrevious reading for these cards:\n{original.reading_text}\n\nNow answer the follow-up question: {body.question}"

    user_language = getattr(user, "language", None) or "en"
    system_prompt = build_system_prompt(user_language)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    response = await llm_followup.ainvoke(messages)

    return FollowUpResponse(reading_text=response.content)


@router.get("/{reading_id}", response_model=ReadingResponse)
async def get_reading(
    reading_id: UUID,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific reading by ID."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(Reading).where(Reading.id == reading_id, Reading.user_id == user.id)
    )
    reading = result.scalar_one_or_none()
    if not reading:
        raise HTTPException(status_code=404, detail="Reading not found")

    return reading
