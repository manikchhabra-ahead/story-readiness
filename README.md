# Jira Story Readiness Agent

AI-powered workflow that evaluates Jira stories for development readiness. When a story is transitioned to "Dev Ready" in Jira, a webhook fires to this FastAPI app, which runs a LangGraph pipeline to score the story against a readiness rubric, posts a structured comment back to Jira, and reverts the status if the story fails the threshold.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker and Docker Compose (optional, for containerised app)

## Quickstart

```bash
# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.example .env

# Run locally
uv run uvicorn app.main:app --reload --port 8000

# Run app in Docker (optional)
docker-compose up
```

## Architecture

4-node deterministic LangGraph pipeline:

1. **evaluate_story** — LLM scores 5 criteria (1–5) with reasoning
2. **generate_output** — LLM calculates final score, builds Jira comment, generates remediations
3. **determine_category** — Pure logic: READY (>=4) or NOT READY (<=3)
4. **jira_write** — Posts comment to Jira, conditionally reverts status

## Services

| Service  | URL                          |
|----------|------------------------------|
| App      | http://localhost:8000         |
| Langfuse | https://cloud.langfuse.com   |
