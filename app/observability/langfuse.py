from langfuse import Langfuse

from app.config import Settings


def create_langfuse_client(settings: Settings) -> Langfuse:
    return Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
