from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class UserCreate(BaseModel):
    name: str
    date_of_birth: str  # YYYY-MM-DD
    time_of_birth: str  # HH:MM
    time_of_birth_known: bool = True
    language: str = "en"
    city_of_birth: str
    latitude: float | None = None
    longitude: float | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    date_of_birth: str | None = None  # YYYY-MM-DD
    time_of_birth: str | None = None  # HH:MM
    city_of_birth: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    language: str | None = None


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None
    date_of_birth: str
    time_of_birth: str
    time_of_birth_known: bool
    language: str
    city_of_birth: str
    zodiac_sign: str | None
    moon_sign: str | None
    ascendant: str | None
    birth_chart: dict | None = None
    is_admin: bool = False
    is_premium: bool
    has_subscribed_before: bool = False
    subscription_plan: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
