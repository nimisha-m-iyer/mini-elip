from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_bot_token: str = ""
    groq_api_key: str = ""
    # Groq changes its model list over time. If you get a "model not found" or
    # "decommissioned" error, pick a current Llama model from console.groq.com/docs/models
    # and set GROQ_MODEL in .env.
    groq_model: str = "llama-3.3-70b-versatile"


settings = Settings()