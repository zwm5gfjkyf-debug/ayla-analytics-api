import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql://ayla:ayla@localhost:5432/ayla_analytics"
    BILLZ_SECRET_KEY: str = ""
    BILLZ_PLATFORM_ID: str = ""
    BILLZ_BASE_URL: str = "https://api-admin.billz.ai"
    TASSVISION_API_KEY: str = ""
    TASSVISION_BASE_URL: str = "https://api.tassvision.ai"
    AYLA_VITRAC_BRANCH_KEY: str = "BPEYBGHV"
    CORS_ORIGINS: str = ""


settings = (
    Settings(_env_file=None)
    if os.environ.get("AYLA_SKIP_ENV_FILE") == "1"
    else Settings()
)
