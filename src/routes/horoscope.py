from fastapi import APIRouter, Depends

from src.core.redis import get_redis

router = APIRouter(prefix="/horoscope", tags=["horoscope"])

ZODIAC_SIGNS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
]


@router.get("/{sign}")
async def get_daily_horoscope(sign: str):
    """Get today's horoscope for a zodiac sign. Pre-computed by nightly cron."""
    sign = sign.lower()
    if sign not in ZODIAC_SIGNS:
        return {"error": f"Invalid sign. Options: {ZODIAC_SIGNS}"}

    from datetime import date
    today = date.today().isoformat()

    try:
        redis = await get_redis()
        cache_key = f"horoscope:{today}:{sign}"
        horoscope = await redis.get(cache_key)
        if horoscope:
            return {"sign": sign, "date": today, "horoscope": horoscope}
    except Exception:
        pass

    return {"sign": sign, "date": today, "horoscope": "Horoscope not yet generated for today. Check back soon."}


@router.get("/")
async def get_all_horoscopes():
    """Get today's horoscopes for all zodiac signs."""
    from datetime import date
    today = date.today().isoformat()

    result = {}
    try:
        redis = await get_redis()
        for sign in ZODIAC_SIGNS:
            cache_key = f"horoscope:{today}:{sign}"
            horoscope = await redis.get(cache_key)
            result[sign] = horoscope or "Not yet generated"
    except Exception:
        result = {sign: "Not yet generated" for sign in ZODIAC_SIGNS}

    return {"date": today, "horoscopes": result}
