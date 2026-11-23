from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    telegram_bot_token: str = ""
    groq_api_key: str = ""


settings = Settings()