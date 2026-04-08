import json
from uuid import UUID

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.models.reading import Reading
from src.models.user import User

settings = get_settings()

llm = ChatOpenAI(
    model="gpt-4o",
    api_key=settings.openai_api_key,
    temperature=0.85,
    max_tokens=800,
    streaming=True,
)

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=settings.openai_api_key,
)

SYSTEM_PROMPT = """You are an experienced, insightful tarot reader with deep knowledge of both Western tarot traditions and Vedic astrology. You speak with warmth, clarity, and honesty — never generic, never fluffy.

Rules:
- Address the user by name in the opening line
- Read all cards TOGETHER as a connected narrative, not one by one
- Reference card positions (past/present/future etc.) to tell a coherent story
- If birth chart data is provided, weave in 1-2 astrological references naturally — don't force it
- If past reading themes are provided, briefly reference their journey (1-2 sentences max)
- Be emotionally intelligent — name what the user might be feeling
- Be specific and grounded, not vague or generic
- For reversed cards, interpret as blocked, delayed, or inverted energy
- STRICT LIMIT: 250-350 words. No more. Be concise and impactful.
- Never sign off with a name, signature, "warm regards", or "[Your Name]"
- Never add disclaimers about tarot being "for entertainment only"
- End with a single actionable insight or reflective question — not a farewell
"""


async def get_past_reading_context(db: AsyncSession, user_id: UUID, limit: int = 5) -> str:
    """Fetch recent readings for context injection."""
    result = await db.execute(
        select(Reading)
        .where(Reading.user_id == user_id)
        .order_by(Reading.created_at.desc())
        .limit(limit)
    )
    past_readings = result.scalars().all()

    if not past_readings:
        return ""

    context_parts = []
    for r in past_readings:
        cards_str = ", ".join(
            f"{c['card']} ({'reversed' if c.get('reversed') else 'upright'}) in {c['position']}"
            for c in r.cards
        )
        context_parts.append(
            f"- {r.created_at.strftime('%B %d')}: Asked '{r.question or 'no question'}', drew {cards_str}"
        )

    return "Recent reading history:\n" + "\n".join(context_parts)


def build_reading_prompt(
    user: User,
    cards: list[dict],
    question: str | None,
    spread_type: str,
    past_context: str,
) -> str:
    """Build the full user prompt with all context for the LLM."""
    parts = [f"User: {user.name}"]

    # Birth chart context
    if user.zodiac_sign:
        parts.append(f"Sun sign: {user.zodiac_sign}")
    if user.moon_sign:
        parts.append(f"Moon sign: {user.moon_sign}")
    if user.ascendant:
        parts.append(f"Ascendant: {user.ascendant}")
    if user.birth_chart:
        planets = user.birth_chart.get("planets", {})
        if planets:
            planet_str = ", ".join(f"{k}: {v}" for k, v in planets.items())
            parts.append(f"Key placements: {planet_str}")

    # Past readings context (RAG memory)
    if past_context:
        parts.append(f"\n{past_context}")

    # Current reading
    parts.append(f"\nSpread type: {spread_type}")
    if question:
        parts.append(f"Question: {question}")

    parts.append("\nCards drawn:")
    for card in cards:
        orientation = "REVERSED" if card["reversed"] else "upright"
        keywords = card["keywords_reversed"] if card["reversed"] else card["keywords_upright"]
        parts.append(
            f"- {card['position'].title()}: {card['card']} ({orientation}) — keywords: {', '.join(keywords)}"
        )

    parts.append("\nPlease give a personal, emotionally intelligent reading that connects all cards to the question and birth chart.")

    return "\n".join(parts)


async def generate_reading(
    db: AsyncSession,
    user: User,
    cards: list[dict],
    question: str | None,
    spread_type: str,
) -> Reading:
    """Generate an AI reading and save it with embedding."""
    past_context = await get_past_reading_context(db, user.id)

    user_prompt = build_reading_prompt(user, cards, question, spread_type, past_context)

    # Generate reading via LLM
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    response = await llm.ainvoke(messages)
    reading_text = response.content

    # Generate embedding for RAG memory
    embedding_vector = await embeddings.aembed_query(
        f"{question or ''} {reading_text[:500]}"
    )

    # Save to database
    cards_for_db = [
        {"position": c["position"], "card": c["card"], "reversed": c["reversed"], "image_url": c.get("image_url")}
        for c in cards
    ]

    reading = Reading(
        user_id=user.id,
        spread_type=spread_type,
        question=question,
        cards=cards_for_db,
        reading_text=reading_text,
        embedding=embedding_vector,
        prompt_context={"user_prompt": user_prompt},
        tokens_used=response.usage_metadata.get("total_tokens") if response.usage_metadata else None,
        model_used="gpt-4o",
    )

    db.add(reading)
    await db.flush()

    return reading
