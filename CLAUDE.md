# CLAUDE.md — Jira Story Readiness Agent

Read this file fully before making any changes to this project.

---

## Commands

# Install dependencies
uv sync

# Run locally
uv run uvicorn app.main:app --reload --port 8000

# Run app in Docker
docker-compose up

# Run graph visualisation
jupyter notebook notebook/visualize_graph.ipynb

# Services
# App:      http://localhost:8000
# Langfuse: https://cloud.langfuse.com (cloud — see .env)

---

## Architecture

4-node deterministic LangGraph pipeline — not an agent:
1. evaluate_story      [LLM]         — scores 5 criteria 1–5 with reasoning
2. generate_output     [LLM]         — calculates score, builds comment, generates remediations
3. determine_category  [pure logic]  — READY (>=4) or NOT READY (<=3)
4. jira_write          [Jira API]    — posts comment, conditionally reverts status

---

## Critical Rules

### Structured Outputs
Every LLM call uses client.messages.parse() with a Pydantic response_format.
Never use prompt-based JSON enforcement, json.loads(), string parsing, or regex on LLM output.

### LLM Gateway
All Anthropic SDK calls go through app/llm/gateway.py only.
No file outside gateway.py may import anthropic directly.

### Prompts
All prompt text lives in app/prompts/prompts.yaml.
Never hardcode prompt strings in Python files.

### Secrets
All secrets come from .env via pydantic-settings Settings in app/config.py.
No hardcoded values anywhere. New env vars must be added to both Settings and .env.example.

### State
StoryState TypedDict is the single state object. Every node reads the full state
and writes only to its own fields. issue_key flows through every node as the Langfuse trace name.

### Package Management
Use uv exclusively. No pip. No poetry.

---

## Jira Details

- Webhook endpoint: POST /webhook/story-ready
- Auth header: X-API-Key
- Acceptance criteria field ID: customfield_10039
- Dev Ready status name: Dev Ready
- Not dev ready status name: Not Dev Ready
- FastAPI must return HTTP 200 immediately — processing is async
- Jira automation timeout: ~10 seconds

---

## Observability

One Langfuse trace per Jira ticket. Trace name = issue_key.
All 4 nodes appear as spans. LLM spans include token usage and full I/O.
Non-LLM spans include decision inputs and outputs.
