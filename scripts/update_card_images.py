"""Update tarot_cards table with Rider-Waite-Smith image URLs."""
import asyncio
from sqlalchemy import select, update
from src.core.database import engine, async_session
from src.models.tarot_card import TarotCard

# Mapping from our name_short prefix to totl.net prefix
PREFIX_MAP = {"ar": "m", "cu": "c", "pe": "p", "sw": "s", "wa": "w"}

# Court card mapping: our suffixes → totl.net numbers
COURT_MAP = {"ac": "01", "pa": "11", "kn": "12", "qu": "13", "ki": "14"}


def name_short_to_image_url(name_short: str) -> str:
    prefix = name_short[:2]
    suffix = name_short[2:]
    totl_prefix = PREFIX_MAP.get(prefix, prefix)

    # Convert court/ace suffixes to numbers
    if suffix in COURT_MAP:
        num = COURT_MAP[suffix]
    else:
        num = suffix  # already numeric like "02", "10"

    return f"https://data.totl.net/tarot-rwcs-images/{totl_prefix}{num}.jpg"


async def main():
    async with async_session() as db:
        result = await db.execute(select(TarotCard))
        cards = result.scalars().all()

        updated = 0
        for card in cards:
            url = name_short_to_image_url(card.name_short)
            card.image_url = url
            updated += 1
            print(f"  {card.name_short:6s} → {url}")

        await db.commit()
        print(f"\nUpdated {updated} cards with image URLs.")


if __name__ == "__main__":
    asyncio.run(main())
