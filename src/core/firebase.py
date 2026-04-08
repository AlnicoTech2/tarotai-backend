import firebase_admin
from firebase_admin import auth, credentials

from src.core.config import get_settings

settings = get_settings()

_app = None


def init_firebase():
    global _app
    if _app is None:
        cred = credentials.Certificate(settings.firebase_credentials_path)
        _app = firebase_admin.initialize_app(cred)
    return _app


def verify_firebase_token(id_token: str) -> dict:
    """Verify Firebase ID token and return decoded claims."""
    decoded = auth.verify_id_token(id_token)
    return decoded
