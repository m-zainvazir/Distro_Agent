from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    # Multi-provider LLM failover (Blueprint Layer 18). When a fallback key or
    # model is set, LLM calls fail over to it on rate-limit / 5xx / connection
    # errors. Empty (default) → single-provider behaviour, no failover.
    groq_api_key_fallback: str = ""
    groq_model_fallback: str = ""
    etsy_api_key: str = ""
    database_url: str = "postgresql+asyncpg://localhost/distroagent"
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    langsmith_api_key: str = ""
    langsmith_project: str = "distroagent"
    google_maps_api_key: str = ""
    vision_score_threshold: float = 8.0
    secret_key: str = "change-me-in-production"
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_founder_phone: str = ""
    sendgrid_api_key: str = ""
    gmail_oauth_client_id: str = ""
    gmail_oauth_client_secret: str = ""
    gmail_oauth_refresh_token: str = ""
    google_calendar_oauth_client_id: str = ""
    google_calendar_oauth_client_secret: str = ""
    google_calendar_oauth_refresh_token: str = ""
    cors_origins: str = "*"  # production: "https://beauty.distroagent.ai"
    # Used to construct approve/reject links sent to admin
    base_url: str = "http://localhost:8000"
    # Admin phone for governance approvals (defaults to founder phone if unset)
    admin_phone: str = ""
    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Per-lead token/cost budget (Blueprint Layers 14 & 16)
    max_tokens_per_lead: int = 4000
    max_cost_per_lead_usd: float = 0.05
    # Automated domain provisioning (Layer 20)
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    sendgrid_domain_auth_uid: str = ""
    # Comma-separated templates; {brand} is replaced with the slugified brand name
    domain_name_templates: str = "try{brand}.com,{brand}wholesale.com,shop{brand}.com,{brand}outreach.com"


settings = Settings()  # type: ignore[call-arg]
