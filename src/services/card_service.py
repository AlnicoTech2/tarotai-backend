import random
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.tarot_card import TarotCard


SPREAD_POSITIONS = {
    "single": ["single"],
    "three_card": ["past", "present", "future"],
    "yes_no": ["answer"],
    "love": ["you", "partner", "relationship"],
    "career": ["situation", "challenge", "outcome"],
    "celtic_cross": [
        "present", "challenge", "past", "future",
        "above", "below", "advice", "environment",
        "hopes", "outcome",
    ],
}


async def draw_cards(db: AsyncSession, spread_type: str) -> list[dict]:
    """Draw random cards for a spread using Fisher-Yates shuffle."""
    positions = SPREAD_POSITIONS.get(spread_type, ["single"])
    count = len(positions)

    result = await db.execute(select(TarotCard))
    all_cards = result.scalars().all()

    # Fisher-Yates shuffle
    deck = list(all_cards)
    for i in range(len(deck) - 1, 0, -1):
        j = random.randint(0, i)
        deck[i], deck[j] = deck[j], deck[i]

    drawn = deck[:count]

    return [
        {
            "position": positions[i],
            "card": drawn[i].name,
            "reversed": random.random() > 0.5,
            "image_url": drawn[i].image_url,
            "meaning_upright": drawn[i].meaning_upright,
            "meaning_reversed": drawn[i].meaning_reversed,
            "keywords_upright": drawn[i].keywords_upright,
            "keywords_reversed": drawn[i].keywords_reversed,
        }
        for i in range(count)
    ]
