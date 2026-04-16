import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.schemas.user import UserCreate, UserUpdate, UserResponse
from src.services.prokerala_service import get_birth_chart, get_planet_positions

router = APIRouter(prefix="/auth", tags=["auth"])

# Reviewer account — fresh start on every login
REVIEWER_UID = "tJARnw4OcmgB4oufGHi1y7I2h2B2"

# Admin/reviewer email patterns — auto-set is_admin=True + is_premium=True
ADMIN_EMAILS = {"admin@tarotai.com"}
ADMIN_EMAIL_DOMAINS = ("@tarotai-test.com",)


def _is_admin_email(email: str | None) -> bool:
    if not email:
        return False
    e = email.lower().strip()
    if e in ADMIN_EMAILS:
        return True
    return any(e.endswith(d) for d in ADMIN_EMAIL_DOMAINS)


@router.post("/sync", response_model=UserResponse)
async def sync_user(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync Firebase user to DB. Creates stub if new, returns existing if not.

    Called on every app launch after Google Sign-In. Idempotent.
    Stub user has: firebase_uid, email, name (from Google profile).
    Onboarding (POST /register) fills in DOB/TOB/city/etc later.
    """
    uid = firebase_user["uid"]
    email = firebase_user.get("email")
    name = firebase_user.get("name") or firebase_user.get("display_name") or ""

    # Reviewer wipe logic
    if uid == REVIEWER_UID:
        result = await db.execute(select(User).where(User.firebase_uid == uid))
        reviewer = result.scalar_one_or_none()
        if reviewer:
            from src.models.reading import Reading
            from sqlalchemy import delete
            await db.execute(delete(Reading).where(Reading.user_id == reviewer.id))
            await db.delete(reviewer)
            await db.commit()

    # Check if user exists
    result = await db.execute(select(User).where(User.firebase_uid == uid))
    user = result.scalar_one_or_none()

    if user:
        # Re-assert admin/premium for admin emails
        if _is_admin_email(user.email) and (not user.is_admin or not user.is_premium):
            user.is_admin = True
            user.is_premium = True
            await db.commit()
        return user

    # Create stub — minimal record for paywall to work
    is_admin = _is_admin_email(email)
    user = User(
        firebase_uid=uid,
        name=name,
        email=email,
        date_of_birth="1990-01-01",  # placeholder, updated during onboarding
        time_of_birth="12:00",       # placeholder
        city_of_birth="",            # placeholder
        is_admin=is_admin,
        is_premium=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register/complete user profile. Updates stub created by /sync with full birth data."""
    firebase_uid = firebase_user["uid"]

    # Find existing stub (created by /sync) or check for full registration
    existing_result = await db.execute(select(User).where(User.firebase_uid == firebase_uid))
    existing_user = existing_result.scalar_one_or_none()

    # If fully registered (has city_of_birth), reject duplicate
    if existing_user and existing_user.city_of_birth and existing_user.city_of_birth.strip():
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

    # Fetch ALL astrology data from Prokerala
    birth_chart = {}
    zodiac_sign = None
    moon_sign = None
    ascendant = None

    vedic_to_western = {
        "Mesha": "Aries", "Vrishabha": "Taurus", "Mithuna": "Gemini",
        "Karka": "Cancer", "Simha": "Leo", "Kanya": "Virgo",
        "Tula": "Libra", "Vrischika": "Scorpio", "Dhanu": "Sagittarius",
        "Makara": "Capricorn", "Kumbha": "Aquarius", "Meena": "Pisces",
    }

    try:
        # 1. Planet positions — full data with degree, longitude, house, rasi, retrograde
        planet_map = {}
        planet_positions_raw = []
        try:
            planet_data = await get_planet_positions(
                body.date_of_birth, body.time_of_birth, latitude, longitude, timezone_offset,
            )
            planet_positions_raw = planet_data.get("data", {}).get("planet_position", [])
            for planet in planet_positions_raw:
                rasi_name = planet.get("rasi", {}).get("name", "")
                western_name = vedic_to_western.get(rasi_name, rasi_name)
                planet_map[planet["name"]] = western_name
                if planet.get("name") == "Sun":
                    zodiac_sign = western_name
                elif planet.get("name") == "Moon":
                    moon_sign = western_name
        except Exception:
            pass

        # 2. Kundli — nakshatra, dosha, yogas, dasha (advanced)
        try:
            chart_data = await get_birth_chart(
                body.date_of_birth, body.time_of_birth, latitude, longitude, timezone_offset,
            )
            kundli_data = chart_data.get("data", {})
            nd = kundli_data.get("nakshatra_details", {})

            # Ascendant (Western name from Kundli zodiac)
            zodiac = nd.get("zodiac", {}).get("name")
            if zodiac:
                ascendant = zodiac

            # Fallback sun/moon from kundli if planet-position was empty
            if not zodiac_sign:
                soorya = nd.get("soorya_rasi", {}).get("name", "")
                zodiac_sign = vedic_to_western.get(soorya, soorya) or None
            if not moon_sign:
                chandra = nd.get("chandra_rasi", {}).get("name", "")
                moon_sign = vedic_to_western.get(chandra, chandra) or None

            # Build comprehensive birth_chart JSONB
            birth_chart = {
                # Planet positions (for table display)
                "planets": planet_map,
                "planet_position": [
                    {
                        "name": p.get("name"),
                        "longitude": p.get("longitude"),
                        "degree": p.get("degree"),
                        "position": p.get("position"),  # house number
                        "is_retrograde": p.get("is_retrograde", False),
                        "rasi": p.get("rasi", {}).get("name"),
                        "rasi_lord": p.get("rasi", {}).get("lord", {}).get("name"),
                    }
                    for p in planet_positions_raw
                ],
                # Nakshatra details
                "nakshatra": nd.get("nakshatra", {}).get("name"),
                "nakshatra_lord": nd.get("nakshatra", {}).get("lord", {}).get("name"),
                "nakshatra_pada": nd.get("nakshatra", {}).get("pada"),
                # Rasi details with lords
                "soorya_rasi": nd.get("soorya_rasi", {}).get("name"),
                "soorya_rasi_lord": nd.get("soorya_rasi", {}).get("lord", {}).get("name"),
                "chandra_rasi": nd.get("chandra_rasi", {}).get("name"),
                "chandra_rasi_lord": nd.get("chandra_rasi", {}).get("lord", {}).get("name"),
                # Additional info
                "additional_info": nd.get("additional_info", {}),
                # Mangal dosha (full)
                "mangal_dosha": kundli_data.get("mangal_dosha", {}).get("has_dosha"),
                "mangal_dosha_description": kundli_data.get("mangal_dosha", {}).get("description"),
                # Yogas
                "yoga_details": kundli_data.get("yoga_details", []),
            }

            # 3. Advanced kundli — Dasha periods
            try:
                from src.services.prokerala_service import get_kundli_advanced
                adv_data = await get_kundli_advanced(
                    body.date_of_birth, body.time_of_birth, latitude, longitude, timezone_offset,
                )
                adv = adv_data.get("data", {})
                birth_chart["dasha_periods"] = adv.get("dasha_periods", [])
                birth_chart["dasha_balance"] = adv.get("dasha_balance", {})
            except Exception:
                pass

        except Exception:
            # Still save whatever planet data we got
            birth_chart = {"planets": planet_map, "planet_position": []}

    except Exception:
        pass  # Non-blocking — user can still register without astrology data

    email = firebase_user.get("email")
    is_admin = _is_admin_email(email)

    if existing_user:
        # Update stub with full profile data
        user = existing_user
        user.name = body.name
        user.email = email
        user.phone = firebase_user.get("phone_number")
        user.date_of_birth = body.date_of_birth
        user.time_of_birth = body.time_of_birth
        user.time_of_birth_known = body.time_of_birth_known
        user.language = body.language
        user.gender = body.gender
        user.city_of_birth = body.city_of_birth
        user.relationship_status = body.relationship_status
        user.occupation = body.occupation
        user.latitude = latitude
        user.longitude = longitude
        user.timezone_offset = timezone_offset
        user.birth_chart = birth_chart
        user.zodiac_sign = zodiac_sign
        user.moon_sign = moon_sign
        user.ascendant = ascendant
        user.is_admin = is_admin
        if is_admin:
            user.is_premium = True
    else:
        # No stub — create fresh (shouldn't happen if /sync was called)
        user = User(
            firebase_uid=firebase_uid,
            name=body.name,
            email=email,
            phone=firebase_user.get("phone_number"),
            date_of_birth=body.date_of_birth,
            time_of_birth=body.time_of_birth,
            time_of_birth_known=body.time_of_birth_known,
            language=body.language,
            gender=body.gender,
            city_of_birth=body.city_of_birth,
            relationship_status=body.relationship_status,
            occupation=body.occupation,
            latitude=latitude,
            longitude=longitude,
            timezone_offset=timezone_offset,
            birth_chart=birth_chart,
            zodiac_sign=zodiac_sign,
            moon_sign=moon_sign,
            ascendant=ascendant,
            is_admin=is_admin,
            is_premium=is_admin,
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
        user.time_of_birth_known = True
    if body.city_of_birth is not None:
        user.city_of_birth = body.city_of_birth
    if body.latitude is not None:
        user.latitude = body.latitude
    if body.longitude is not None:
        user.longitude = body.longitude
    if body.language is not None:
        user.language = body.language
    if body.gender is not None:
        user.gender = body.gender
    if body.relationship_status is not None:
        user.relationship_status = body.relationship_status
    if body.occupation is not None:
        user.occupation = body.occupation

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
            from src.services.prokerala_service import get_birth_chart, get_planet_positions, get_kundli_advanced

            vedic_to_western = {
                "Mesha": "Aries", "Vrishabha": "Taurus", "Mithuna": "Gemini",
                "Karka": "Cancer", "Simha": "Leo", "Kanya": "Virgo",
                "Tula": "Libra", "Vrischika": "Scorpio", "Dhanu": "Sagittarius",
                "Makara": "Capricorn", "Kumbha": "Aquarius", "Meena": "Pisces",
            }

            # Planet positions
            planet_map = {}
            planet_positions_raw = []
            try:
                planet_data = await get_planet_positions(
                    user.date_of_birth, user.time_of_birth, latitude, longitude, timezone_offset,
                )
                planet_positions_raw = planet_data.get("data", {}).get("planet_position", [])
                for planet in planet_positions_raw:
                    rasi_name = planet.get("rasi", {}).get("name", "")
                    western_name = vedic_to_western.get(rasi_name, rasi_name)
                    planet_map[planet["name"]] = western_name
                    if planet.get("name") == "Sun":
                        user.zodiac_sign = western_name
                    elif planet.get("name") == "Moon":
                        user.moon_sign = western_name
            except Exception:
                pass

            # Kundli — comprehensive
            birth_chart = {"planets": planet_map, "planet_position": []}
            try:
                chart_data = await get_birth_chart(
                    user.date_of_birth, user.time_of_birth, latitude, longitude, timezone_offset,
                )
                kundli_data = chart_data.get("data", {})
                nd = kundli_data.get("nakshatra_details", {})

                zodiac = nd.get("zodiac", {}).get("name")
                if zodiac:
                    user.ascendant = zodiac
                if not user.zodiac_sign:
                    soorya = nd.get("soorya_rasi", {}).get("name", "")
                    user.zodiac_sign = vedic_to_western.get(soorya, soorya) or None
                if not user.moon_sign:
                    chandra = nd.get("chandra_rasi", {}).get("name", "")
                    user.moon_sign = vedic_to_western.get(chandra, chandra) or None

                birth_chart = {
                    "planets": planet_map,
                    "planet_position": [
                        {
                            "name": p.get("name"), "longitude": p.get("longitude"),
                            "degree": p.get("degree"), "position": p.get("position"),
                            "is_retrograde": p.get("is_retrograde", False),
                            "rasi": p.get("rasi", {}).get("name"),
                            "rasi_lord": p.get("rasi", {}).get("lord", {}).get("name"),
                        }
                        for p in planet_positions_raw
                    ],
                    "nakshatra": nd.get("nakshatra", {}).get("name"),
                    "nakshatra_lord": nd.get("nakshatra", {}).get("lord", {}).get("name"),
                    "nakshatra_pada": nd.get("nakshatra", {}).get("pada"),
                    "soorya_rasi": nd.get("soorya_rasi", {}).get("name"),
                    "soorya_rasi_lord": nd.get("soorya_rasi", {}).get("lord", {}).get("name"),
                    "chandra_rasi": nd.get("chandra_rasi", {}).get("name"),
                    "chandra_rasi_lord": nd.get("chandra_rasi", {}).get("lord", {}).get("name"),
                    "additional_info": nd.get("additional_info", {}),
                    "mangal_dosha": kundli_data.get("mangal_dosha", {}).get("has_dosha"),
                    "mangal_dosha_description": kundli_data.get("mangal_dosha", {}).get("description"),
                    "yoga_details": kundli_data.get("yoga_details", []),
                }

                # Dasha periods from advanced endpoint
                try:
                    adv_data = await get_kundli_advanced(
                        user.date_of_birth, user.time_of_birth, latitude, longitude, timezone_offset,
                    )
                    adv = adv_data.get("data", {})
                    birth_chart["dasha_periods"] = adv.get("dasha_periods", [])
                    birth_chart["dasha_balance"] = adv.get("dasha_balance", {})
                except Exception:
                    pass

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
    """Get current user profile. Reviewer account gets wiped on every login."""
    uid = firebase_user["uid"]

    # Reviewer: delete existing data for fresh start every login
    if uid == REVIEWER_UID:
        result = await db.execute(select(User).where(User.firebase_uid == uid))
        reviewer = result.scalar_one_or_none()
        if reviewer:
            from src.models.reading import Reading
            from sqlalchemy import delete
            await db.execute(delete(Reading).where(Reading.user_id == reviewer.id))
            await db.delete(reviewer)
            await db.commit()
        raise HTTPException(status_code=404, detail="User not found. Please register first.")

    result = await db.execute(
        select(User).where(User.firebase_uid == uid)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please register first.")

    # Re-assert admin/premium for admin emails on every fetch (in case flags got reset)
    if _is_admin_email(user.email) and (not user.is_admin or not user.is_premium):
        user.is_admin = True
        user.is_premium = True
        await db.commit()

    return user


@router.post("/fcm-token", status_code=status.HTTP_200_OK)
async def update_fcm_token(
    request: Request,
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store/update the user's FCM push notification token."""
    body = await request.json()
    token = body.get("token", "")

    result = await db.execute(
        select(User).where(User.firebase_uid == firebase_user["uid"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.fcm_token = token
    await db.commit()
    return {"success": True}


@router.delete("/account", status_code=status.HTTP_200_OK)
async def delete_account(
    firebase_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete user account and all associated data.

    DPDP Act 2023 compliance — synchronous hard delete.

    NOTE: This endpoint does NOT cancel autopay/subscriptions. Per project
    policy, subscription cancellation is handled exclusively via support
    email. Users must email support to cancel autopay separately.
    """
    uid = firebase_user["uid"]

    result = await db.execute(select(User).where(User.firebase_uid == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    user_id = user.id

    try:
        # Delete all readings (RAG embeddings + reading text)
        from src.models.reading import Reading
        from sqlalchemy import delete

        await db.execute(delete(Reading).where(Reading.user_id == user_id))

        # Delete user record (point of no return)
        await db.delete(user)
        await db.commit()

        # Delete Firebase auth user (best-effort, non-fatal)
        try:
            from firebase_admin import auth as firebase_admin_auth
            firebase_admin_auth.delete_user(uid)
        except Exception:
            pass  # Firebase deletion is non-fatal — DB cleanup already done

        return {"success": True, "message": "Account deleted permanently."}

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Account deletion failed: {str(e)}",
        )
