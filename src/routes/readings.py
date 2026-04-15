from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
