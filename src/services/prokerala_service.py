import httpx

from src.core.config import get_settings

settings = get_settings()

TOKEN_URL = "https://api.prokerala.com/token"
BASE_URL = "https://api.prokerala.com/v2/astrology"

_access_token: str | None = None


async def _get_token() -> str:
    """Get OAuth2 access token from Prokerala."""
    global _access_token
    if _access_token:
        return _access_token

    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.prokerala_client_id,
                "client_secret": settings.prokerala_client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()
        _access_token = data["access_token"]
        return _access_token


async def get_birth_chart(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_offset: float,
) -> dict:
    """Fetch birth chart (Kundli) from Prokerala API.

    Args:
        date_of_birth: YYYY-MM-DD
        time_of_birth: HH:MM
        latitude: Birth location latitude
        longitude: Birth location longitude
        timezone_offset: UTC offset in hours (e.g., 5.5 for IST)
    """
    token = await _get_token()
    datetime_str = f"{date_of_birth}T{time_of_birth}:00{_format_tz(timezone_offset)}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/kundli",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "datetime": datetime_str,
                "coordinates": f"{latitude},{longitude}",
                "ayanamsa": 1,  # Lahiri
            },
        )
        response.raise_for_status()
        return response.json()


async def get_planet_positions(
    date_of_birth: str,
    time_of_birth: str,
    latitude: float,
    longitude: float,
    timezone_offset: float,
) -> dict:
    """Fetch planetary positions for birth chart context."""
    token = await _get_token()
    datetime_str = f"{date_of_birth}T{time_of_birth}:00{_format_tz(timezone_offset)}"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/planet-position",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "datetime": datetime_str,
                "coordinates": f"{latitude},{longitude}",
                "ayanamsa": 1,
            },
        )
        response.raise_for_status()
        return response.json()


def _format_tz(offset: float) -> str:
    """Convert numeric timezone offset to ISO format (+05:30)."""
    sign = "+" if offset >= 0 else "-"
    offset = abs(offset)
    hours = int(offset)
    minutes = int((offset - hours) * 60)
    return f"{sign}{hours:02d}:{minutes:02d}"
