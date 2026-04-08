import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.schemas.user import UserCreate, UserUpdate, UserResponse
from src.services.prokerala_service import get_birth_chart, get_planet_positions

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new user after Firebase auth. Fetches birth chart from Prokerala."""
    firebase_uid = firebase_user["uid"]

    # Check if user already exists
    existing = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already registered")

    # Use client-provided coordinates or geocode as fallback
    latitude = body.latitude or 19.076
    longitude = body.longitude or 72.8777
    timezone_offset = 5.5  # IST default

    if not body.latitude or not body.longitude:
        try:
            async with httpx.AsyncClient() as client:
                geo_resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": body.city_of_birth, "format": "json", "limit": 1},
                    headers={"User-Agent": "TarotAI/1.0"},
                )
                geo_data = geo_resp.json()
                if geo_data:
                    latitude = float(geo_data[0]["lat"])
                    longitude = float(geo_data[0]["lon"])
        except Exception:
            pass

    # Fetch birth chart from Prokerala
    birth_chart = {}
    zodiac_sign = None
    moon_sign = None
    ascendant = None

    try:
        planet_data = await get_planet_positions(
            body.date_of_birth,
            body.time_of_birth,
            latitude,
            longitude,
            timezone_offset,
        )
        birth_chart = planet_data

        # Vedic rasi name → Western zodiac name mapping
        vedic_to_western = {
            "Mesha": "Aries", "Vrishabha": "Taurus", "Mithuna": "Gemini",
            "Karka": "Cancer", "Simha": "Leo", "Kanya": "Virgo",
            "Tula": "Libra", "Vrischika": "Scorpio", "Dhanu": "Sagittarius",
            "Makara": "Capricorn", "Kumbha": "Aquarius", "Meena": "Pisces",
        }

        # Extract key signs from planet positions
        planets = planet_data.get("data", {}).get("planet_position", [])
        planet_map = {}
        for planet in planets:
            rasi_name = planet.get("rasi", {}).get("name", "")
            western_name = vedic_to_western.get(rasi_name, rasi_name)
            planet_map[planet["name"]] = western_name
            if planet.get("name") == "Sun":
                zodiac_sign = western_name
            elif planet.get("name") == "Moon":
                moon_sign = western_name

        # Store useful planet placements in birth_chart
        birth_chart = {"planets": planet_map, "raw": planet_data.get("data")}

        # Get Kundli data for ascendant, nakshatra, dosha
        try:
            chart_data = await get_birth_chart(
                body.date_of_birth,
                body.time_of_birth,
                latitude,
                longitude,
                timezone_offset,
            )
            nakshatra = chart_data.get("data", {}).get("nakshatra_details", {})
            zodiac = nakshatra.get("zodiac", {}).get("name")
            if zodiac:
                ascendant = zodiac  # Western zodiac name from Kundli
            birth_chart["nakshatra"] = nakshatra.get("nakshatra", {}).get("name")
            birth_chart["mangal_dosha"] = chart_data.get("data", {}).get("mangal_dosha", {}).get("has_dosha")
        except Exception:
            pass
    except Exception:
        pass  # Non-blocking — user can still register without astrology data

    user = User(
        firebase_uid=firebase_uid,
        name=body.name,
        email=firebase_user.get("email"),
        phone=firebase_user.get("phone_number"),
        date_of_birth=body.date_of_birth,
        time_of_birth=body.time_of_birth,
        city_of_birth=body.city_of_birth,
        latitude=latitude,
        longitude=longitude,
        timezone_offset=timezone_offset,
        birth_chart=birth_chart,
        zodiac_sign=zodiac_sign,
        moon_sign=moon_sign,
        ascendant=ascendant,
    )

    db.add(user)
    await db.flush()

    return user


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    body: UserUpdate,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user profile fields. Only provided fields are updated."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.name is not None:
        user.name = body.name
    if body.date_of_birth is not None:
        user.date_of_birth = body.date_of_birth
    if body.time_of_birth is not None:
        user.time_of_birth = body.time_of_birth
    if body.city_of_birth is not None:
        user.city_of_birth = body.city_of_birth
    if body.latitude is not None:
        user.latitude = body.latitude
    if body.longitude is not None:
        user.longitude = body.longitude

    # If birth data changed, re-fetch astrology data
    birth_data_changed = any(
        v is not None for v in [body.date_of_birth, body.time_of_birth, body.city_of_birth, body.latitude, body.longitude]
    )
    if birth_data_changed:
        latitude = user.latitude or 19.076
        longitude = user.longitude or 72.8777
        timezone_offset = 5.5

        # Geocode if city changed but no coordinates provided
        if body.city_of_birth and not body.latitude and not body.longitude:
            try:
                async with httpx.AsyncClient() as client:
                    geo_resp = await client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": body.city_of_birth, "format": "json", "limit": 1},
                        headers={"User-Agent": "TarotAI/1.0"},
                    )
                    geo_data = geo_resp.json()
                    if geo_data:
                        latitude = float(geo_data[0]["lat"])
                        longitude = float(geo_data[0]["lon"])
                        user.latitude = latitude
                        user.longitude = longitude
            except Exception:
                pass

        try:
            from src.services.prokerala_service import get_birth_chart, get_planet_positions

            planet_data = await get_planet_positions(
                user.date_of_birth,
                user.time_of_birth,
                latitude,
                longitude,
                timezone_offset,
            )
            vedic_to_western = {
                "Mesha": "Aries", "Vrishabha": "Taurus", "Mithuna": "Gemini",
                "Karka": "Cancer", "Simha": "Leo", "Kanya": "Virgo",
                "Tula": "Libra", "Vrischika": "Scorpio", "Dhanu": "Sagittarius",
                "Makara": "Capricorn", "Kumbha": "Aquarius", "Meena": "Pisces",
            }
            planets = planet_data.get("data", {}).get("planet_position", [])
            planet_map = {}
            for planet in planets:
                rasi_name = planet.get("rasi", {}).get("name", "")
                western_name = vedic_to_western.get(rasi_name, rasi_name)
                planet_map[planet["name"]] = western_name
                if planet.get("name") == "Sun":
                    user.zodiac_sign = western_name
                elif planet.get("name") == "Moon":
                    user.moon_sign = western_name

            birth_chart = {"planets": planet_map, "raw": planet_data.get("data")}

            try:
                chart_data = await get_birth_chart(
                    user.date_of_birth,
                    user.time_of_birth,
                    latitude,
                    longitude,
                    timezone_offset,
                )
                nakshatra = chart_data.get("data", {}).get("nakshatra_details", {})
                zodiac = nakshatra.get("zodiac", {}).get("name")
                if zodiac:
                    user.ascendant = zodiac
                birth_chart["nakshatra"] = nakshatra.get("nakshatra", {}).get("name")
                birth_chart["mangal_dosha"] = chart_data.get("data", {}).get("mangal_dosha", {}).get("has_dosha")
            except Exception:
                pass

            user.birth_chart = birth_chart
        except Exception:
            pass  # Non-blocking

    await db.flush()
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user profile."""
    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please register first.")
    return user
