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


# ─────────────────────────────────────────────────────
# DAILY YES/NO QUESTIONS
# ─────────────────────────────────────────────────────

QUESTIONS = {
    "en": [
        "Will today bring good news?",
        "Is spicy food good for me today?",
        "Should I travel today?",
        "Will I meet an old friend today?",
        "Will money come today?",
        "Should I start something new today?",
        "Will something happen in love life today?",
        "Should I focus on health today?",
        "Is shopping a good idea today?",
        "Will I get a surprise today?",
        "Is today a good day for investments?",
        "Will I get a compliment today?",
        "Should I take a risk today?",
        "Will today be stressful?",
        "Is today lucky for interviews?",
        "Will I learn something new today?",
        "Should I forgive someone today?",
        "Will someone help me today?",
        "Is today good for a new relationship?",
        "Will I sleep well tonight?",
    ],
    "hinglish": [
        "Kya aaj achhi khabar milegi?",
        "Kya aaj spicy food suit karega?",
        "Kya aaj travel karna sahi rahega?",
        "Kya aaj koi purana dost milega?",
        "Kya aaj paisa aayega?",
        "Kya aaj naya kaam shuru karna chahiye?",
        "Kya aaj love life mein kuch hoga?",
        "Kya aaj health ka dhyan rakhna chahiye?",
        "Kya aaj shopping karna sahi hai?",
        "Kya aaj koi surprise milega?",
        "Kya aaj investment ke liye achha din hai?",
        "Kya aaj koi tareef karega?",
        "Kya aaj risk lena chahiye?",
        "Kya aaj stressful hoga?",
        "Kya aaj interview ke liye lucky hai?",
        "Kya aaj kuch naya seekhne ko milega?",
        "Kya aaj kisi ko maaf karna chahiye?",
        "Kya aaj koi madad karega?",
        "Kya aaj naye rishte ke liye achha hai?",
        "Kya aaj achhi neend aayegi?",
    ],
    "hi": [
        "क्या आज अच्छी खबर मिलेगी?",
        "क्या आज तीखा खाना सही रहेगा?",
        "क्या आज यात्रा करना सही होगा?",
        "क्या आज कोई पुराना दोस्त मिलेगा?",
        "क्या आज पैसा आएगा?",
        "क्या आज नया काम शुरू करना चाहिए?",
        "क्या आज प्यार में कुछ होगा?",
        "क्या आज स्वास्थ्य का ध्यान रखना चाहिए?",
        "क्या आज शॉपिंग करना सही है?",
        "क्या आज कोई सरप्राइज मिलेगा?",
        "क्या आज निवेश के लिए अच्छा दिन है?",
        "क्या आज कोई तारीफ करेगा?",
        "क्या आज रिस्क लेना चाहिए?",
        "क्या आज तनावपूर्ण होगा?",
        "क्या आज इंटरव्यू के लिए शुभ है?",
        "क्या आज कुछ नया सीखने को मिलेगा?",
        "क्या आज किसी को माफ करना चाहिए?",
        "क्या आज कोई मदद करेगा?",
        "क्या आज नए रिश्ते के लिए अच्छा है?",
        "क्या आज अच्छी नींद आएगी?",
    ],
}


@router.get("/questions")
async def get_daily_questions(
    lang: str = "en",
):
    """Get 5 daily Yes/No questions rotated by day."""
    today = date.today()
    seed = int(today.strftime("%Y%m%d"))

    questions = QUESTIONS.get(lang, QUESTIONS["en"])
    total = len(questions)

    # Pick 5 questions based on day (deterministic rotation)
    indices = [(seed + i * 7) % total for i in range(5)]
    selected = [questions[i] for i in indices]

    return {"questions": selected, "date": today.isoformat(), "lang": lang}
