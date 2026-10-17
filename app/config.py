"""Application settings. Every secret comes from the environment (or a local .env), never from source."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./patients.db"

    # Shared secret Vapi sends in the `x-vapi-secret` header on every webhook call.
    vapi_secret: str = ""
    # Only used by scripts in vapi/ to create/update the assistant and phone number.
    vapi_api_key: str = ""
    vapi_assistant_id: str = ""
    public_base_url: str = ""

    seed_data: bool = True
    log_level: str = "INFO"
    log_to_file: bool = False


settings = Settings()
