from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    API_KEY: str
    JIRA_BASE_URL: str
    JIRA_API_TOKEN: str
    JIRA_USER_EMAIL: str
    ANTHROPIC_API_KEY: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_HOST: str

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
