from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_bot_token: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # Deployment settings
    webhook_base_url: str = ""          # e.g. https://mini-elip.onrender.com (empty = no webhook)
    telegram_webhook_secret: str = ""   # random string; Telegram sends it back on every update
    rerank_enabled: bool = True         # set false if the host runs out of memory
    model_cache_dir: str = "/models"


settings = Settings()