"""Cron endpoints — called by EventBridge Scheduler.

Protected by X-Cron-Secret header (not Firebase auth).
These run on a schedule, not triggered by users.
"""

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.core.config import get_settings
from src.core.database import get_db
from src.models.horoscope import Horoscope
from src.models.user import User

log = logging.getLogger("cron")
settings = get_settings()

router = APIRouter(prefix="/cron", tags=["cron"])

CRON_SECRET = settings.app_secret_key  # Reuse app secret for cron auth

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

HOROSCOPE_PROMPT = """You are an expert Vedic astrologer. Generate today's daily horoscope for {sign} ({vedic_name}).

Rules:
- Use Vedic (sidereal) astrology, NOT Western tropical
- Reference current planetary transits naturally
- Be specific, positive but honest — not generic fluff
- Include 1 practical tip or action for the day
- STRICT LIMIT: 60-80 words, 2-3 short paragraphs
- Conversational tone, like texting a friend
- {language_instruction}
"""

VEDIC_NAMES = {
    "Aries": "Mesha", "Taurus": "Vrishabha", "Gemini": "Mithuna",
    "Cancer": "Karka", "Leo": "Simha", "Virgo": "Kanya",
    "Libra": "Tula", "Scorpio": "Vrischika", "Sagittarius": "Dhanu",
    "Capricorn": "Makara", "Aquarius": "Kumbha", "Pisces": "Meena",
}


def _verify_cron_secret(request: Request):
    """Verify the cron secret header."""
    secret = request.headers.get("x-cron-secret", "")
    if secret != CRON_SECRET:
        raise HTTPException(status_code=403, detail="Invalid cron secret")


# ─────────────────────────────────────────────────────
# HOROSCOPE GENERATION
# ─────────────────────────────────────────────────────


@router.post("/generate-horoscopes", status_code=status.HTTP_200_OK)
async def generate_horoscopes(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate daily horoscopes for all 12 zodiac signs.

    Called by EventBridge Scheduler at midnight IST.
    Deletes old horoscopes for today (idempotent) then generates fresh ones.
    """
    _verify_cron_secret(request)

    today = date.today()
    log.info(f"Generating horoscopes for {today}")

    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0.85,
        max_tokens=200,
        api_key=settings.openai_api_key,
    )

    # Delete existing horoscopes for today (idempotent re-run)
    await db.execute(delete(Horoscope).where(Horoscope.date == today))

    generated = []
    for sign in ZODIAC_SIGNS:
        try:
            prompt = HOROSCOPE_PROMPT.format(
                sign=sign,
                vedic_name=VEDIC_NAMES[sign],
                language_instruction="Respond in English.",
            )
            response = await llm.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=f"Generate today's horoscope for {sign} for {today.strftime('%B %d, %Y')}."),
            ])

            horoscope = Horoscope(
                sign=sign,
                date=today,
                horoscope_text=response.content,
                language="en",
            )
            db.add(horoscope)
            generated.append(sign)
            log.info(f"Generated horoscope for {sign}")

        except Exception as e:
            log.error(f"Failed to generate horoscope for {sign}: {e}")

    await db.commit()
    log.info(f"Generated {len(generated)}/12 horoscopes for {today}")

    return {
        "date": str(today),
        "generated": len(generated),
        "signs": generated,
    }


# ─────────────────────────────────────────────────────
# FCM PUSH NOTIFICATION
# ─────────────────────────────────────────────────────


# ─── Push message templates by time slot (peak-hour hooks for India audience) ───
PUSH_TEMPLATES = {
    "morning": {  # 8 AM IST — fired by tarotai-push-8am
        "title": "Your daily tarot reading is ready",
        "body_default": "{name}, the stars have a message for you today.",
        "body_zodiac": "{name}, today's {zodiac} horoscope is here.",
        "type": "daily_reminder",
    },
    "lunch": {  # 11:30 AM IST — peak signup hour
        "title": "Quick lunchtime reading? 🍱",
        "body_default": "{name}, take a 30-second break and pull a card.",
        "body_zodiac": "{name}, your {zodiac} energy at midday — peek inside.",
        "type": "lunch_reminder",
    },
    "evening": {  # 6:30 PM IST — second peak (post-work)
        "title": "Evening reflection ✨",
        "body_default": "{name}, what does today's energy say? Pull your evening card.",
        "body_zodiac": "{name}, end your day with a {zodiac} insight.",
        "type": "evening_reminder",
    },
}


async def _send_push_to_all_users(
    db: AsyncSession,
    slot: str,
) -> dict:
    """Internal helper used by all 3 push slots. Iterates all FCM-registered users
    and sends a slot-specific message. Returns counts.
    """
    template = PUSH_TEMPLATES.get(slot, PUSH_TEMPLATES["morning"])

    result = await db.execute(
        select(User.fcm_token, User.name, User.zodiac_sign)
        .where(User.fcm_token.isnot(None))
        .where(User.fcm_token != "")
    )
    users = result.all()

    if not users:
        log.info(f"[push:{slot}] no users with FCM tokens — skipping")
        return {"slot": slot, "sent": 0, "total": 0}

    from firebase_admin import messaging

    sent_count = 0
    failed_count = 0

    for fcm_token, name, zodiac_sign in users:
        try:
            first_name = (name or "").split(" ")[0] or "Seeker"
            if zodiac_sign:
                body = template["body_zodiac"].format(name=first_name, zodiac=zodiac_sign)
            else:
                body = template["body_default"].format(name=first_name)

            message = messaging.Message(
                notification=messaging.Notification(
                    title=template["title"],
                    body=body,
                ),
                token=fcm_token,
                data={
                    "type": template["type"],
                    "click_action": "OPEN_APP",
                    "slot": slot,
                },
            )
            messaging.send(message)
            sent_count += 1
        except messaging.UnregisteredError:
            log.info(f"[push:{slot}] FCM token expired: {fcm_token[:20]}...")
        except Exception as e:
            failed_count += 1
            log.error(f"[push:{slot}] FCM send failed: {e}")

    log.info(f"[push:{slot}] sent={sent_count}/{len(users)} failed={failed_count}")
    return {"slot": slot, "sent": sent_count, "total": len(users), "failed": failed_count}


@router.post("/send-daily-push", status_code=status.HTTP_200_OK)
async def send_daily_push(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """8 AM IST — primary daily push (horoscope ready)."""
    _verify_cron_secret(request)
    return await _send_push_to_all_users(db, slot="morning")


@router.post("/send-lunch-push", status_code=status.HTTP_200_OK)
async def send_lunch_push(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """11:30 AM IST — peak signup hour, midday hook."""
    _verify_cron_secret(request)
    return await _send_push_to_all_users(db, slot="lunch")


@router.post("/send-evening-push", status_code=status.HTTP_200_OK)
async def send_evening_push(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """6:30 PM IST — post-work peak, evening reflection hook."""
    _verify_cron_secret(request)
    return await _send_push_to_all_users(db, slot="evening")


# ─────────────────────────────────────────────────────
# CLEANUP OLD CHAT SESSIONS (30 days)
# ─────────────────────────────────────────────────────


@router.post("/cleanup-old-chats", status_code=status.HTTP_200_OK)
async def cleanup_old_chats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Delete chat sessions and messages older than 30 days."""
    _verify_cron_secret(request)

    from datetime import timedelta
    from sqlalchemy import delete
    from src.models.chat import ChatSession, ChatMessage

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    # Get old session IDs
    result = await db.execute(
        select(ChatSession.id).where(ChatSession.updated_at < cutoff)
    )
    old_ids = [r[0] for r in result.all()]

    if old_ids:
        # Messages cascade-deleted via FK, but explicit delete is safer
        await db.execute(
            delete(ChatMessage).where(ChatMessage.session_id.in_(old_ids))
        )
        await db.execute(
            delete(ChatSession).where(ChatSession.id.in_(old_ids))
        )
        await db.commit()
        log.info(f"Cleaned up {len(old_ids)} old chat sessions")

    return {"deleted_sessions": len(old_ids)}
