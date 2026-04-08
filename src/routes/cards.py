from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.models.tarot_card import TarotCard

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("/")
async def get_all_cards(db: AsyncSession = Depends(get_db)):
    """Get all 78 tarot cards."""
    result = await db.execute(select(TarotCard).order_by(TarotCard.arcana, TarotCard.number))
    cards = result.scalars().all()
    return cards


@router.get("/{name_short}")
async def get_card(name_short: str, db: AsyncSession = Depends(get_db)):
    """Get a single card by short name (e.g., 'ar01' for The Magician)."""
    result = await db.execute(
        select(TarotCard).where(TarotCard.name_short == name_short)
    )
    card = result.scalar_one_or_none()
    if not card:
        return {"error": "Card not found"}
    return card
