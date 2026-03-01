from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase (required — set via .env or environment variables)
    supabase_url: str
    supabase_key: str

    # Room settings
    max_users_per_room: int = 50
    message_history_limit: int = 50       # messages sent to new joiners
    message_history_store_limit: int = 500 # in-memory cap before trimming

    # Rate limiting (per user)
    rate_limit_messages: int = 10         # max messages ...
    rate_limit_window_seconds: int = 5    # ... per this many seconds

    # CORS
    cors_origins: list[str] = ["*"]


settings = Settings()
