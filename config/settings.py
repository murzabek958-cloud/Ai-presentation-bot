from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")

    # --- Gemini ---
    gemini_api_key: str = Field(..., alias="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-2.0-flash", alias="GEMINI_MODEL")

    # --- App ---
    debug: bool = Field(False, alias="DEBUG")
    max_slides: int = Field(12, alias="MAX_SLIDES")
    min_slides: int = Field(5, alias="MIN_SLIDES")
    output_dir: str = Field("cache/output", alias="OUTPUT_DIR")


settings = Settings()
