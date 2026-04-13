import logging
import time
from typing import TypeVar

import anthropic
from langfuse import Langfuse
from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-6"

    async def call(
        self,
        response_model: type[T],
        messages: list[dict],
        system: str,
        langfuse: Langfuse,
    ) -> T:
        start = time.time()

        response = await self.client.messages.parse(
            model=self.model,
            max_tokens=1024,
            system=system,
            messages=messages,
            output_format=response_model,
        )

        latency_ms = (time.time() - start) * 1000
        result: T = response.parsed_output

        logger.info(
            "LLM call completed: model=%s input_tokens=%d output_tokens=%d latency_ms=%.0f",
            self.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            latency_ms,
        )

        langfuse.update_current_span(
            output=result.model_dump(),
            metadata={
                "model": self.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "latency_ms": round(latency_ms),
            },
        )

        return result
