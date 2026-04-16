from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.models.horoscope import Horoscope

router = APIRouter(prefix="/horoscope", tags=["horoscope"])

ZODIAC_SIGNS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
]


@router.get("/{sign}")
async def get_daily_horoscope(sign: str, db: AsyncSession = Depends(get_db)):
    """Get today's horoscope for a zodiac sign. Pre-computed by nightly cron."""
    sign_lower = sign.lower()
    sign_title = sign_lower.capitalize()

    if sign_lower not in ZODIAC_SIGNS:
        return {"error": f"Invalid sign. Options: {ZODIAC_SIGNS}"}

    today = date.today()

    result = await db.execute(
        select(Horoscope)
        .where(Horoscope.sign == sign_title)
        .where(Horoscope.date == today)
        .limit(1)
    )
    horoscope = result.scalar_one_or_none()

    if horoscope:
        return {
            "sign": sign_title,
            "date": str(today),
            "horoscope": horoscope.horoscope_text,
        }

    return {
        "sign": sign_title,
        "date": str(today),
        "horoscope": "Horoscope not yet generated for today. Check back soon.",
    }


@router.get("/")
async def get_all_horoscopes(db: AsyncSession = Depends(get_db)):
    """Get today's horoscopes for all zodiac signs."""
    today = date.today()

    result = await db.execute(
        select(Horoscope).where(Horoscope.date == today)
    )
    horoscopes = result.scalars().all()

    horoscope_map = {h.sign.lower(): h.horoscope_text for h in horoscopes}

    return {
        "date": str(today),
        "horoscopes": {
            sign: horoscope_map.get(sign, "Not yet generated")
            for sign in ZODIAC_SIGNS
        },
    }
