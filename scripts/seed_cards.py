"""Seed all 78 tarot cards from tarotapi.dev into the database."""
import asyncio
import httpx
from sqlalchemy import select

from src.core.database import async_session
from src.models.tarot_card import TarotCard

TAROT_API_URL = "https://tarotapi.dev/api/v1/cards"


async def fetch_cards() -> list[dict]:
    """Fetch all 78 cards from tarotapi.dev."""
    async with httpx.AsyncClient() as client:
        response = await client.get(TAROT_API_URL)
        response.raise_for_status()
        data = response.json()
        return data["cards"]


def parse_card(card: dict) -> dict:
    """Transform tarotapi.dev card format into our model."""
    return {
        "name": card["name"],
        "name_short": card["name_short"],
        "number": int(card.get("value_int", 0)),
        "arcana": "major" if card.get("type") == "major" else "minor",
        "suit": card.get("suit") if card.get("type") != "major" else None,
        "meaning_upright": card.get("meaning_up", ""),
        "meaning_reversed": card.get("meaning_rev", ""),
        "keywords_upright": [kw.strip() for kw in card.get("meaning_up", "").split(",")[:5]],
        "keywords_reversed": [kw.strip() for kw in card.get("meaning_rev", "").split(",")[:5]],
        "description": card.get("desc", ""),
        "image_url": None,  # Will be set when we upload Rider-Waite images to S3
    }


async def seed():
    print("Fetching cards from tarotapi.dev...")
    cards = await fetch_cards()
    print(f"Fetched {len(cards)} cards")

    async with async_session() as db:
        # Check if already seeded
        result = await db.execute(select(TarotCard).limit(1))
        if result.scalar_one_or_none():
            print("Cards already seeded. Skipping.")
            return

        for card_data in cards:
            parsed = parse_card(card_data)
            card = TarotCard(**parsed)
            db.add(card)

        await db.commit()
        print(f"Seeded {len(cards)} tarot cards successfully.")


if __name__ == "__main__":
    asyncio.run(seed())
