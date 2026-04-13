import asyncio
import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader

from app.config import get_settings, Settings
from app.graph.graph import build_graph
from app.llm.gateway import LLMGateway
from app.models import JiraWebhookPayload
from app.observability.langfuse import create_langfuse_client
from app.services.jira import JiraClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Jira Story Readiness Agent")
compiled_graph = build_graph()

api_key_header = APIKeyHeader(name="X-API-Key")


def verify_api_key(
    api_key: str = Depends(api_key_header),
    settings: Settings = Depends(get_settings),
) -> str:
    if api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


async def run_pipeline(payload: JiraWebhookPayload, settings: Settings) -> None:
    gateway = LLMGateway(settings)
    jira_client = JiraClient(settings)
    langfuse = create_langfuse_client(settings)

    try:
        logger.info("[%s] Starting pipeline", payload.issue_key)

        initial_state = {
            "issue_key": payload.issue_key,
            "story_data": payload.model_dump(),
        }

        with langfuse.start_as_current_observation(name=payload.issue_key):
            result = await compiled_graph.ainvoke(
                initial_state,
                config={
                    "configurable": {
                        "langfuse": langfuse,
                        "gateway": gateway,
                        "jira_client": jira_client,
                    }
                },
            )

        logger.info(
            "[%s] Pipeline completed — score=%s category=%s",
            payload.issue_key,
            result.get("rounded_score"),
            result.get("category"),
        )

    except Exception:
        logger.exception("[%s] Pipeline failed", payload.issue_key)

    finally:
        langfuse.flush()
        await jira_client.close()


@app.post("/webhook/story-ready")
async def webhook_story_ready(
    payload: JiraWebhookPayload,
    _api_key: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> dict:
    logger.info("[%s] Webhook received — launching async pipeline", payload.issue_key)
    asyncio.create_task(run_pipeline(payload, settings))
    return {"status": "accepted", "issue_key": payload.issue_key}


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return """<!DOCTYPE html>
<html>
<head><title>Jira Story Readiness Agent</title></head>
<body style="font-family: sans-serif; max-width: 600px; margin: 80px auto;">
  <h1>Jira Story Readiness Agent</h1>
  <p>Status: <strong>Running</strong></p>
  <ul>
    <li><a href="/health">Health Check (JSON)</a></li>
    <li><a href="/docs">API Documentation</a></li>
  </ul>
</body>
</html>"""


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
