from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(protected_namespaces=("settings_",))

    database_url: str
    telegram_bot_token: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # Deployment settings
    webhook_base_url: str = ""          # e.g. https://mini-elip.onrender.com (empty = no webhook)
    telegram_webhook_secret: str = ""   # letters, digits, _ and - only
    rerank_enabled: bool = True         # set false if the host runs out of memory
    model_cache_dir: str = "/models"


settings = Settings()