import hashlib
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.redis import get_redis
from src.middleware.auth import get_current_user
from src.models.tarot_card import TarotCard
from src.models.user import User

router = APIRouter(prefix="/daily-card", tags=["daily-card"])


def _daily_seed(user_id: str, today: str) -> int:
    """Deterministic seed from user ID + date — same card all day per user."""
    h = hashlib.sha256(f"{user_id}:{today}".encode()).hexdigest()
    return int(h[:8], 16)


@router.get("/")
async def get_daily_card(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get today's card of the day for this user. Deterministic per user per day."""
    today = date.today().isoformat()

    # Get user
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = str(user.id)
    cache_key = f"daily_card:{today}:{user_id}"

    # Try Redis cache first
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            import json
            return json.loads(cached)
    except Exception:
        pass

    # Get total card count and pick deterministically
    count_result = await db.execute(select(func.count()).select_from(TarotCard))
    total = count_result.scalar()

    seed = _daily_seed(user_id, today)
    card_index = seed % total
    reversed_card = (seed // total) % 2 == 1

    # Fetch the card at that index (ordered by name for consistency)
    result = await db.execute(
        select(TarotCard).order_by(TarotCard.name).offset(card_index).limit(1)
    )
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=500, detail="Could not draw daily card")

    response = {
        "date": today,
        "card": {
            "name": card.name,
            "name_short": card.name_short,
            "arcana": card.arcana,
            "suit": card.suit,
            "reversed": reversed_card,
            "meaning": card.meaning_reversed if reversed_card else card.meaning_upright,
            "keywords": card.keywords_reversed if reversed_card else card.keywords_upright,
            "description": card.description,
        },
    }

    # Cache in Redis for the day (expire at midnight)
    try:
        redis = await get_redis()
        import json
        await redis.set(cache_key, json.dumps(response), ex=86400)
    except Exception:
        pass

    return response
