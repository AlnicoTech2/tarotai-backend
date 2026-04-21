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

# First reading — GPT-4o (premium quality, first impression)
llm_primary = ChatOpenAI(
    model="gpt-4o",
    api_key=settings.openai_api_key,
    temperature=0.85,
    max_tokens=300,
    streaming=True,
    max_retries=3,
    timeout=30.0,
)

# Follow-up chat — GPT-4o-mini (3x faster, good enough for conversation)
llm_followup = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=settings.openai_api_key,
    temperature=0.85,
    max_tokens=300,
    streaming=True,
    max_retries=3,
    timeout=30.0,
)

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=settings.openai_api_key,
)

LANGUAGE_INSTRUCTIONS = {
    "en": "Respond in English.",
    "hinglish": "Respond in Hinglish — Latin script with Hindi words mixed in naturally (e.g., 'Aapki kundli', 'Mangal dosha', 'Yeh card batata hai...'). Use everyday casual conversational tone.",
    "hi": "Respond in Hindi (हिंदी) using Devanagari script.",
    "ta": "Respond in Tamil (தமிழ்).",
    "te": "Respond in Telugu (తెలుగు).",
    "kn": "Respond in Kannada (ಕನ್ನಡ).",
    "mr": "Respond in Marathi (मराठी).",
    "bn": "Respond in Bengali (বাংলা).",
    "gu": "Respond in Gujarati (ગુજરાતી).",
}


def build_system_prompt(language: str = "en") -> str:
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])
    return f"""You are an experienced Vedic astrologer and tarot reader, deeply knowledgeable in Indian astrology (Vedic/sidereal system, NOT Western tropical). You speak with warmth, clarity, and honesty — never generic, never fluffy.

LANGUAGE: {lang_instruction}

ASTROLOGICAL SYSTEM: Always use Vedic (sidereal) astrology, not Western tropical. When you reference signs, you mean the Vedic rashi (e.g., "Tula" = Libra in Vedic ≠ Western Libra). Use Vedic concepts: nakshatras, dashas, planetary lords (rashi adhipati), doshas (mangal, kaal sarp), yogas (raj, gajakesari).

Rules:
- Address the user by name in the opening line
- Read all cards TOGETHER as a connected narrative, not one by one
- Reference card positions (past/present/future etc.) to tell a coherent story
- If birth chart data is provided, weave in 1-2 Vedic astrological references naturally (rashi, nakshatra, current dasha, dosha) — don't force it
- If past reading themes are provided, briefly reference their journey (1-2 sentences max)
- Be emotionally intelligent — name what the user might be feeling
- Be specific and grounded, not vague or generic
- For reversed cards, interpret as blocked, delayed, or inverted energy
- STRICT FORMAT: Write exactly 3 short paragraphs separated by blank lines. Each paragraph must be 1-2 sentences only (max 25 words per sentence). This is displayed as chat bubbles — keep it punchy and conversational, like texting.
- STRICT LIMIT: 60-80 words total. No more.
- Never sign off with a name, signature, "warm regards", or "[Your Name]"
- Never add disclaimers about tarot being "for entertainment only"
- End with a single actionable insight or reflective question — not a farewell
"""


SYSTEM_PROMPT = build_system_prompt("en")  # default fallback


def build_yes_no_prompt(language: str = "en") -> str:
    """System prompt specifically for Yes/No readings."""
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])
    return f"""You are an experienced Vedic astrologer and tarot reader giving a Yes/No reading.

LANGUAGE: {lang_instruction}

STRICT FORMAT — Follow this EXACTLY:
1. First paragraph: Start with "YES" or "NO" in bold/caps on its own, followed by a brief 1-sentence reason based on the card drawn.
2. Second paragraph: 2-3 sentences expanding on why, referencing the card and the user's birth chart if available. Be specific, not vague.
3. Third paragraph: End with a hook — an engaging question or intriguing insight that makes the user want to ask more. Make them curious.

Rules:
- Address the user by name
- Be direct — commit to YES or NO, don't hedge
- For reversed cards, lean toward NO or "not yet"
- Keep it conversational, like texting a wise friend
- STRICT LIMIT: 60-80 words total. No more.
- Never sign off with a name or signature
- Never add disclaimers
"""


# ── Persona definitions ──
PERSONA_PROMPTS = {
    "aarohi": "Your name is Tarot Aarohi. You are a warm, intuitive, all-purpose tarot reader. You handle any topic — love, career, health, spirituality.",
    "akshat": "Your name is Tarot Akshat. You specialize in love and relationships. You are empathetic, caring, and speak like a trusted friend about matters of the heart.",
    "karmesh": "Your name is Tarot Karmesh. You specialize in career, finance, and professional growth. You give direct, practical advice about work and money.",
    "vihani": "Your name is Tarot Vihani. You specialize in spiritual growth and inner peace. You are calm, philosophical, and guide people toward self-awareness.",
    "meera": "Your name is Premacharya Meera. You are a Vedic astrologer specializing in love, marriage, and romantic compatibility. You analyze kundli yogas for relationships.",
    "gyannath": "Your name is Pandit Gyannath. You are a Vedic astrologer specializing in career, wealth, and financial success. You analyze dasha periods and planetary transits for professional guidance.",
    "rudraksh": "Your name is Tantrik Rudraksh. You are a Vedic astrologer specializing in protection, remedies, and removing obstacles. You suggest mantras, gemstones, and tantric remedies.",
    "vedant": "Your name is Acharya Vedant. You are a Vedic astrologer specializing in spiritual guidance and life purpose. You help people find their dharma through kundli analysis.",
    "rashmi": "Your name is Matrivi Rashmi. You are a Vedic astrologer specializing in family matters, children, and domestic harmony. You analyze the 4th and 5th house for family guidance.",
    "tej": "Your name is Samadhan Guru Tej. You are a Vedic astrologer specializing in problem-solving. You analyze planetary positions to find practical solutions to life's challenges.",
}


def build_persona_chat_prompt(language: str = "en", persona_id: str = "aarohi") -> str:
    """Build system prompt for direct chat with a persona (no card reading)."""
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])
    persona_intro = PERSONA_PROMPTS.get(persona_id, PERSONA_PROMPTS["aarohi"])
    return f"""{persona_intro}

You are deeply knowledgeable in Indian astrology (Vedic/sidereal system, NOT Western tropical). You speak with warmth, clarity, and honesty — never generic, never fluffy.

LANGUAGE: {lang_instruction}

ASTROLOGICAL SYSTEM: Always use Vedic (sidereal) astrology, not Western tropical. Use Vedic concepts: nakshatras, dashas, planetary lords, doshas, yogas.

Rules:
- Address the user by name in the opening line
- If birth chart data is provided, weave in Vedic astrological references naturally
- Be emotionally intelligent — name what the user might be feeling
- Be specific and grounded, not vague or generic
- STRICT FORMAT: Write exactly 2-3 short paragraphs. Each paragraph 1-2 sentences (max 25 words per sentence). Chat bubble style — punchy and conversational.
- STRICT LIMIT: 60-80 words total. No more.
- Never sign off with a name or signature
- Never add disclaimers about being "for entertainment only"
- End with an actionable insight or reflective question
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

    # Personal context
    if user.gender:
        parts.append(f"Gender: {user.gender}")
    if user.relationship_status and user.relationship_status != "prefer_not_to_say":
        parts.append(f"Relationship: {user.relationship_status}")
    if user.occupation and user.occupation != "prefer_not_to_say":
        parts.append(f"Occupation: {user.occupation}")

    # Birth chart context
    if user.zodiac_sign:
        parts.append(f"Sun sign: {user.zodiac_sign}")
    if user.moon_sign:
        parts.append(f"Moon sign: {user.moon_sign}")
    if not user.time_of_birth_known:
        parts.append("Note: Birth time is approximate (unknown). Focus on sun and moon sign. Do NOT emphasize ascendant or house placements as they may be inaccurate.")
    elif user.ascendant:
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

    # Build system prompt in user's language
    user_language = getattr(user, "language", None) or "en"
    if spread_type == "yes_no":
        system_prompt = build_yes_no_prompt(user_language)
    else:
        system_prompt = build_system_prompt(user_language)

    # Pick model: first reading (no question) = GPT-4o, follow-up (has question) = GPT-4o-mini
    llm = llm_followup if question else llm_primary

    # Generate reading via LLM
    messages = [
        SystemMessage(content=system_prompt),
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
