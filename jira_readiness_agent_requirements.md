# Jira Story Readiness Agent — Requirements
# ═══════════════════════════════════════════════════════════════════════════════
# This is the single source of truth for this project.
# Claude Code must read this file in full before generating anything.
# All files listed in the "Files to Generate" sections must be created exactly
# as specified. Do not skip any file.
# ═══════════════════════════════════════════════════════════════════════════════

---

## 1. Project Overview

An AI-powered workflow that evaluates Jira stories for development readiness.
When a story is transitioned to "Dev Ready" in Jira, a webhook fires to this
FastAPI app, which runs a LangGraph workflow to score the story against a
readiness rubric, posts a structured comment back to Jira, and reverts the
status to "Not Dev Ready" if the story fails the threshold.

---

## 2. Tech Stack

| Component | Choice | Notes |
|---|---|---|
| API framework | FastAPI | Entry point for Jira webhook |
| Workflow | LangGraph | 4-node deterministic pipeline |
| LLM | Claude Sonnet (`claude-sonnet-4-6`) | Via Anthropic Python SDK |
| LLM Gateway | Custom wrapper | See Section 8 |
| Observability | Langfuse (self-hosted) | One trace per Jira ticket |
| Logging | Python `logging` | Non-LLM operations only |
| Package manager | `uv` | Exclusively — no pip, no poetry |
| Containerisation | Docker + docker-compose | Full stack including Langfuse |
| Notebook | Jupyter | Graph visualisation only |

---

## 3. Package Management

- Use `uv` exclusively for all dependency management
- `pyproject.toml` is the single source of truth for dependencies
- `uv.lock` must be committed
- Commands:
```bash
uv venv
uv sync          # install dependencies
uv add <pkg>     # add a dependency
uv run <cmd>     # run any command in the venv
```

---

## 4. Project Structure

Claude Code must generate the following file and directory structure exactly:

```
jira-readiness-agent/
├── app/
│   ├── main.py                   # FastAPI app, webhook endpoint, auth middleware
│   ├── config.py                 # pydantic-settings Settings class
│   ├── models.py                 # Pydantic models for inbound Jira webhook payload
│   ├── llm/
│   │   ├── gateway.py            # Only place Anthropic SDK is called
│   │   └── schemas.py            # Pydantic response models for all LLM outputs
│   ├── graph/
│   │   ├── state.py              # StoryState TypedDict and all nested types
│   │   ├── nodes.py              # All 4 node functions
│   │   └── graph.py              # LangGraph graph definition and compilation
│   ├── prompts/
│   │   ├── prompts.yaml          # All prompt templates
│   │   └── loader.py             # YAML loader and variable substitution
│   ├── services/
│   │   └── jira.py               # Jira REST API client
│   └── observability/
│       └── langfuse.py           # Langfuse client and span helpers
├── notebook/
│   └── visualize_graph.ipynb     # Graph visualisation notebook
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── uv.lock
├── .env.example                  # MUST be generated — see Section 14
├── CLAUDE.md                     # MUST be generated — see Section 15
└── README.md
```

---

## 5. Authentication

- Jira calls FastAPI with a shared API key in header: `X-API-Key`
- FastAPI validates via `fastapi.security.APIKeyHeader`
- Invalid key returns HTTP 403
- All secrets loaded from `.env` via `pydantic-settings` — no hardcoded values anywhere

---

## 6. Pydantic Settings (`app/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_KEY: str
    JIRA_BASE_URL: str
    JIRA_API_TOKEN: str
    JIRA_USER_EMAIL: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_SECRET_KEY: str
    LANGFUSE_HOST: str
    ANTHROPIC_API_KEY: str

    class Config:
        env_file = ".env"
```

Any new environment variable must be added to both `Settings` and `.env.example`.

---

## 7. Jira Webhook Payload (`app/models.py`)

Sent by Jira Automation "Send web request" on transition to "Dev Ready":

```json
{
  "issue_key": "{{issue.key}}",
  "summary": "{{issue.summary}}",
  "description": "{{issue.description}}",
  "acceptance_criteria": "{{issue.customfield_10039}}",
  "story_points": "{{issue.story_points}}",
  "labels": "{{issue.labels}}",
  "components": "{{issue.components}}",
  "priority": "{{issue.priority.name}}"
}
```

- `issue_key` is the only required field
- All other fields are optional — the LLM must handle `None` values gracefully
- `acceptance_criteria` custom field ID is `customfield_10039`
- Missing `acceptance_criteria` must be flagged as a gap in the evaluation, not cause a crash

Pydantic model:
```python
class JiraWebhookPayload(BaseModel):
    issue_key: str
    summary: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    story_points: Optional[int] = None
    labels: Optional[list[str]] = []
    components: Optional[list[str]] = []
    priority: Optional[str] = None
```

---

## 8. LLM Gateway (`app/llm/gateway.py`)

A simple custom wrapper around the Anthropic SDK. Not LiteLLM.

Responsibilities:
- Centralise all Anthropic SDK calls — no node, service, or utility may import `anthropic` directly
- Enforce structured outputs on every call via `client.messages.parse()`
- Attach output to the Langfuse span passed in
- Log model name, token usage, and latency via Python `logging`

```python
class LLMGateway:
    def __init__(self, settings: Settings):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-6"

    def call(
        self,
        response_model: type[BaseModel],
        messages: list[dict],
        system: str,
        langfuse_span: StatefulSpanClient,
    ) -> BaseModel:
        # Use client.messages.parse() — enforces structured output natively
        # Log token usage and latency
        # Attach result to langfuse_span
        ...
```

---

## 9. Structured Outputs — CRITICAL CONSTRAINT

**Every LLM call must use `client.messages.parse()` with a Pydantic `response_format`.**

The following are strictly forbidden — Claude Code must not use any of these:
- Prompting the model to return JSON (e.g. "respond only in JSON", "return a JSON object")
- `json.loads()` on raw LLM text responses
- String parsing or regex on LLM output
- Any manual validation of LLM output shape

### Required pattern

```python
from anthropic import Anthropic
from pydantic import BaseModel

response = client.messages.parse(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=system_prompt,
    messages=messages,
    response_format=ResponseModel,  # Pydantic model — SDK enforces schema
)

result: ResponseModel = response.parsed  # Guaranteed valid — no further parsing needed
```

All Pydantic response models live in `app/llm/schemas.py`.

---

## 10. LangGraph State (`app/graph/state.py`)

```python
from typing import Optional
from typing_extensions import TypedDict

class CriterionEvaluation(TypedDict):
    score: int          # 1–5
    reasoning: str      # One sentence explaining the score

class StoryEvaluation(TypedDict):
    user_story_clarity: CriterionEvaluation
    acceptance_criteria_quality: CriterionEvaluation
    technical_clarity: CriterionEvaluation
    dependencies: CriterionEvaluation
    sizing: CriterionEvaluation

class RemediationSuggestion(TypedDict):
    criterion: str      # e.g. "acceptance_criteria_quality"
    suggestion: str     # Actionable fix tied to this criterion

class StoryState(TypedDict):
    # Input
    issue_key: str
    story_data: dict

    # Node 1 output
    evaluation: Optional[StoryEvaluation]

    # Node 2 output
    final_score: Optional[float]
    rounded_score: Optional[int]
    remediation_suggestions: Optional[list[RemediationSuggestion]]
    jira_comment: Optional[str]

    # Node 3 output
    category: Optional[str]        # "READY" or "NOT READY"

    # Node 4 output
    jira_write_status: Optional[str]
```

---

## 11. LangGraph Nodes (`app/graph/nodes.py`)

The workflow is a deterministic pipeline — not an agent. No dynamic tool selection.

### Node 1: `evaluate_story` [LLM]
- Input: `story_data` from state
- Loads `evaluate_story` prompt from `prompts.yaml`
- Calls LLM via gateway with `StoryEvaluationResponse` as response model
- Scores each of 5 criteria 1–5 with one-sentence reasoning per criterion
- Output: writes `evaluation` to state
- Langfuse: LLM span with full input/output

### Node 2: `generate_output` [LLM]
- Input: `evaluation` from state
- Loads `generate_output` prompt from `prompts.yaml`
- Calls LLM via gateway with `GenerateOutputResponse` as response model
- Calculates `final_score` (average of 5 scores) and `rounded_score`
- Generates `remediation_suggestions` only for criteria scoring 1–3, each tied to criterion name
- Generates `jira_comment` string formatted and ready to post
- Output: writes `final_score`, `rounded_score`, `remediation_suggestions`, `jira_comment` to state
- Langfuse: LLM span with full input/output

### Node 3: `determine_category` [pure logic — no LLM]
- Input: `rounded_score` from state
- Logic: `if rounded_score <= 3 → "NOT READY" else → "READY"`
- Output: writes `category` to state
- Langfuse: manual span with input score and output decision

### Node 4: `jira_write` [Jira REST API]
- Input: `issue_key`, `category`, `jira_comment` from state
- Posts `jira_comment` as a comment on the Jira issue (always — both READY and NOT READY)
- If `NOT READY`: also transitions issue status to "Not Dev Ready"
- If `READY`: no status change
- Output: writes `jira_write_status` to state
- Langfuse: manual span with payload sent and API response
- Python logging: log Jira request and response

---

## 12. Prompts (`app/prompts/prompts.yaml`)

All prompt text lives in this YAML file. Never hardcode prompt strings in Python.

```yaml
evaluate_story:
  system: |
    You are a senior engineering manager evaluating Jira stories for development readiness.
    Score the story against 5 criteria. For each criterion provide a score from 1 to 5
    and a single sentence of reasoning explaining the score.

    Scoring guide:
    5 - Exemplary. No gaps.
    4 - Good. Minor gaps that do not block development.
    3 - Adequate but has gaps that may slow development.
    2 - Significant gaps that would block or confuse a developer.
    1 - Missing or unusable.

    If a field is missing or empty, score it 1 and state that it is absent in your reasoning.

    Criteria:
    - user_story_clarity: Is there a clear who/what/why? Is the scope unambiguous?
    - acceptance_criteria_quality: Are the criteria testable, specific, and verifiable — not just present?
    - technical_clarity: Is there enough detail for a developer to start without asking questions?
    - dependencies: Does the story acknowledge external dependencies or blockers?
    - sizing: Is the story small enough to complete within a single sprint?

  user: |
    Evaluate the following Jira story:

    Summary: {summary}
    Description: {description}
    Acceptance Criteria: {acceptance_criteria}
    Story Points: {story_points}
    Labels: {labels}
    Components: {components}
    Priority: {priority}

generate_output:
  system: |
    You are generating a structured development readiness report from a story evaluation.
    You will receive scores and reasoning for 5 criteria.
    Your job is to:
    1. Calculate the final score as the average of all 5 criterion scores, rounded to the nearest whole number.
    2. Generate remediation suggestions only for criteria that scored 1, 2, or 3.
       Each suggestion must explicitly name the criterion it addresses and provide a specific, actionable fix.
    3. Generate a jira_comment string ready to post directly to Jira.
       Use the READY format if rounded_score >= 4, NOT READY format if rounded_score <= 3.

    READY comment format:
    ✅ Story Readiness Analysis
    Score: {rounded_score}/5 — READY FOR DEV
    Analyzed: {timestamp}

    Criteria breakdown:
    - User Story Clarity: {score}/5 — {reasoning}
    - Acceptance Criteria: {score}/5 — {reasoning}
    - Technical Clarity: {score}/5 — {reasoning}
    - Dependencies: {score}/5 — {reasoning}
    - Sizing: {score}/5 — {reasoning}

    No blockers found. Story is cleared for development.

    NOT READY comment format:
    🚫 Story Readiness Analysis
    Score: {rounded_score}/5 — NOT READY FOR DEV
    Analyzed: {timestamp}

    Criteria breakdown:
    - User Story Clarity: {score}/5 — {reasoning}
    - Acceptance Criteria: {score}/5 — {reasoning}
    - Technical Clarity: {score}/5 — {reasoning}
    - Dependencies: {score}/5 — {reasoning}
    - Sizing: {score}/5 — {reasoning}

    Gaps identified:
    - [{criterion}] {suggestion}

    Please address the above and transition back to Dev Ready.

  user: |
    Here is the evaluation result:
    {evaluation}

    Current timestamp: {timestamp}
    Generate the full output now.
```

Prompt loader (`app/prompts/loader.py`):
```python
import yaml
from pathlib import Path

def load_prompts() -> dict:
    path = Path(__file__).parent / "prompts.yaml"
    with open(path) as f:
        return yaml.safe_load(f)
```

Variable substitution uses Python `.format()` on the user prompt string.
Prompts are loaded once at startup.

---

## 13. Observability (`app/observability/langfuse.py`)

- One Langfuse trace per Jira ticket — trace name = `issue_key`
- All 4 nodes appear as spans under the same trace
- `issue_key` is passed through every node as the trace identifier
- LLM spans (Nodes 1, 2): full input, output, token usage attached
- Non-LLM spans (Nodes 3, 4): input values and output decision/API response attached

```
Trace: SDX-1
├── Span: evaluate_story      [LLM span]
├── Span: generate_output     [LLM span]
├── Span: determine_category  [manual span]
└── Span: jira_write          [manual span]
```

Langfuse runs locally as a Docker service. `LANGFUSE_HOST=http://localhost:3000`

---

## 14. File to Generate: `.env.example`

Claude Code must generate this file at the project root with the following exact content:

```
# ── Jira Readiness Agent — Environment Variables ──────────────────────────────
# Copy this file to .env and fill in all values before running the application.
# Never commit .env to version control.

# ── API Auth ───────────────────────────────────────────────────────────────────
# Shared secret used by Jira Automation to authenticate webhook calls.
# Set this value in Jira Automation > Send web request > Headers > X-API-Key
API_KEY=

# ── Jira ──────────────────────────────────────────────────────────────────────
# Base URL of your Jira Cloud instance — no trailing slash
JIRA_BASE_URL=https://your-domain.atlassian.net

# Jira user email associated with the API token below
JIRA_USER_EMAIL=

# Jira API token — generate at: https://id.atlassian.com/manage-profile/security/api-tokens
JIRA_API_TOKEN=

# ── Anthropic ─────────────────────────────────────────────────────────────────
# Anthropic API key — generate at: https://console.anthropic.com
ANTHROPIC_API_KEY=

# ── Langfuse (self-hosted via Docker) ─────────────────────────────────────────
# Langfuse server URL — matches docker-compose service port
LANGFUSE_HOST=http://localhost:3000

# Generate with: openssl rand -hex 32
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# Required by Langfuse auth — generate with: openssl rand -hex 32
LANGFUSE_NEXTAUTH_SECRET=

# Required by Langfuse for password hashing — generate with: openssl rand -hex 32
LANGFUSE_SALT=

# ── Postgres (Langfuse dependency) ────────────────────────────────────────────
POSTGRES_USER=langfuse
POSTGRES_PASSWORD=langfuse
POSTGRES_DB=langfuse
```

---

## 15. File to Generate: `CLAUDE.md`

Claude Code must generate this file at the project root. It is the reference file
for all future Claude Code sessions on this project.

Content to generate:

```markdown
# CLAUDE.md — Jira Story Readiness Agent

Read this file fully before making any changes to this project.

---

## Commands

# Install dependencies
uv sync

# Run locally
uv run uvicorn app.main:app --reload --port 8000

# Run full stack (app + Langfuse + Postgres + Redis)
docker-compose up

# Run graph visualisation
jupyter notebook notebook/visualize_graph.ipynb

# Services
# App:      http://localhost:8000
# Langfuse: http://localhost:3000

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
```

---

## 16. Docker Setup

### `docker-compose.yml`

```yaml
version: "3.8"

services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - langfuse

  langfuse:
    image: langfuse/langfuse:latest
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@langfuse-db:5432/${POSTGRES_DB}
      - REDIS_URL=redis://langfuse-redis:6379
      - NEXTAUTH_SECRET=${LANGFUSE_NEXTAUTH_SECRET}
      - SALT=${LANGFUSE_SALT}
      - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
    depends_on:
      - langfuse-db
      - langfuse-redis

  langfuse-db:
    image: postgres:15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - langfuse-db-data:/var/lib/postgresql/data

  langfuse-redis:
    image: redis:7
    volumes:
      - langfuse-redis-data:/data

volumes:
  langfuse-db-data:
  langfuse-redis-data:
```

### `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
COPY uv.lock .

RUN uv sync --frozen

COPY . .

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 17. Dependencies (`pyproject.toml`)

```toml
[project]
name = "jira-readiness-agent"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "langgraph",
    "langchain",
    "langchain-anthropic",
    "anthropic",
    "langfuse",
    "httpx",
    "python-dotenv",
    "pyyaml",
    "jupyter",
]
```

---

## 18. Graph Visualisation (`notebook/visualize_graph.ipynb`)

Two cells only. Do not add anything else.

```python
# Cell 1
from app.graph.graph import build_graph
app = build_graph()

# Cell 2
from IPython.display import Image, display
display(Image(app.get_graph().draw_mermaid_png()))
```

---

## 19. Key Constraints Summary

- FastAPI returns HTTP 200 immediately — LangGraph workflow runs async
- `acceptance_criteria` is optional — missing value is a scoring gap, not a crash
- All Jira payload fields except `issue_key` are optional
- Loop prevention: Jira automation must be configured with "Exclude if transition performed by automation"
- Structured outputs via `client.messages.parse()` on every LLM call — no exceptions
- No direct `anthropic` imports outside `app/llm/gateway.py`
- No prompt strings in Python files — all prompts in `prompts.yaml`
- No hardcoded secrets — all from `.env` via `Settings`
- `uv` only for package management
