import asyncio
import json
import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from pydantic import ValidationError

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


async def run_pipeline(
    payload: JiraWebhookPayload, raw_payload: dict, trace_name: str, settings: Settings
) -> None:
    gateway = LLMGateway(settings)
    jira_client = JiraClient(settings)
    langfuse = create_langfuse_client(settings)

    try:
        logger.info("[%s] Starting pipeline", trace_name)

        initial_state = {
            "issue_key": payload.issue_key,
            "story_data": payload.model_dump(),
        }

        with langfuse.start_as_current_observation(name=trace_name, input=raw_payload):
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
            langfuse.update_current_span(
                output={
                    "rounded_score": result.get("rounded_score"),
                    "category": result.get("category"),
                }
            )

        logger.info(
            "[%s] Pipeline completed — score=%s category=%s",
            trace_name,
            result.get("rounded_score"),
            result.get("category"),
        )

    except Exception:
        logger.exception("[%s] Pipeline failed", trace_name)

    finally:
        langfuse.flush()
        await jira_client.close()


def _format_validation_errors(exc: ValidationError) -> list[dict]:
    return [
        {
            "field": ".".join(str(p) for p in err["loc"]) or "<root>",
            "issue": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]


@app.post("/webhook/story-ready")
async def webhook_story_ready(
    request: Request,
    _api_key: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
) -> dict:
    raw_body = await request.body()

    # Parse JSON leniently — Jira automation occasionally emits unescaped
    # control characters inside string values (newlines, tabs in descriptions).
    try:
        raw_payload = json.loads(raw_body, strict=False)
    except json.JSONDecodeError as e:
        trace_name = f"invalid-json-{uuid.uuid4().hex[:8]}"
        body_preview = raw_body.decode("utf-8", errors="replace")
        logger.warning("[%s] Webhook rejected — invalid JSON: %s", trace_name, e)

        langfuse = create_langfuse_client(settings)
        try:
            with langfuse.start_as_current_observation(
                name=trace_name, input={"raw_body": body_preview}
            ):
                langfuse.update_current_span(
                    output={
                        "status": "rejected",
                        "reason": "invalid_json",
                        "error": f"{e.msg} at position {e.pos}",
                    }
                )
        finally:
            langfuse.flush()

        raise HTTPException(
            status_code=400,
            detail={
                "message": "Webhook payload is not valid JSON.",
                "error": e.msg,
                "position": e.pos,
                "hint": "Check the Jira automation for unescaped control characters (newlines, tabs) inside string fields.",
                "trace_name": trace_name,
            },
        )

    if not isinstance(raw_payload, dict):
        trace_name = f"invalid-shape-{uuid.uuid4().hex[:8]}"
        logger.warning("[%s] Webhook rejected — payload is not a JSON object", trace_name)
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Webhook payload must be a JSON object.",
                "received_type": type(raw_payload).__name__,
                "trace_name": trace_name,
            },
        )

    # Validate against expected schema. On failure, still log the raw payload
    # to Langfuse so we can see exactly what Jira sent.
    try:
        payload = JiraWebhookPayload.model_validate(raw_payload)
    except ValidationError as e:
        issue_key = raw_payload.get("issue_key")
        trace_name = issue_key or f"invalid-payload-{uuid.uuid4().hex[:8]}"
        errors = _format_validation_errors(e)
        logger.warning("[%s] Webhook rejected — schema mismatch: %s", trace_name, errors)

        langfuse = create_langfuse_client(settings)
        try:
            with langfuse.start_as_current_observation(name=trace_name, input=raw_payload):
                langfuse.update_current_span(
                    output={
                        "status": "rejected",
                        "reason": "schema_validation_failed",
                        "errors": errors,
                    }
                )
        finally:
            langfuse.flush()

        raise HTTPException(
            status_code=422,
            detail={
                "message": "Webhook payload does not match the expected schema.",
                "errors": errors,
                "trace_name": trace_name,
            },
        )

    trace_name = payload.issue_key or f"missing-key-{uuid.uuid4().hex[:8]}"
    logger.info("[%s] Webhook received — launching async pipeline", trace_name)
    asyncio.create_task(run_pipeline(payload, raw_payload, trace_name, settings))
    return {"status": "accepted", "issue_key": payload.issue_key, "trace_name": trace_name}


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
