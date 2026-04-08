from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class CardDraw(BaseModel):
    position: str  # "past", "present", "future", "single", etc.
    card: str  # "The Tower"
    reversed: bool


class ReadingRequest(BaseModel):
    spread_type: str  # "single", "three_card", "celtic_cross", "yes_no", "love", "career"
    question: str | None = None


class ReadingResponse(BaseModel):
    id: UUID
    spread_type: str
    question: str | None
    cards: list[CardDraw]
    reading_text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingHistoryItem(BaseModel):
    id: UUID
    spread_type: str
    question: str | None
    cards: list[dict]
    reading_text: str
    created_at: datetime

    model_config = {"from_attributes": True}
