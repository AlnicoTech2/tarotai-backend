from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    app_secret_key: str = "change-this-in-production"
    debug: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/tarotai"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str = ""

    # Firebase
    firebase_credentials_path: str = "./firebase-credentials.json"

    # Prokerala
    prokerala_client_id: str = ""
    prokerala_client_secret: str = ""

    # Razorpay
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # AWS
    aws_region: str = "ap-south-1"
    aws_s3_bucket: str = "tarotai-assets"
    aws_sqs_queue_url: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
