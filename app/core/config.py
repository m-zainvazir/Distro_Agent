from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    etsy_api_key: str = ""
    database_url: str = "postgresql+asyncpg://localhost/distroagent"
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    langsmith_api_key: str = ""
    langsmith_project: str = "distroagent"
    google_maps_api_key: str = ""
    vision_score_threshold: float = 8.0


settings = Settings()  # type: ignore[call-arg]
