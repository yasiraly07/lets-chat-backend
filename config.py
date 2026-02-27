from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str = "https://bpdsvidojultmujivkfw.supabase.co"
    supabase_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJwZHN2aWRvanVsdG11aml2a2Z3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIxNDQwMjksImV4cCI6MjA4NzcyMDAyOX0.V2-pAvcxepsjlrByZVUqc18y847-aQ4bHoBJTe9Tb04"

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
