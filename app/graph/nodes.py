import logging
from datetime import datetime, timezone

from langfuse import Langfuse
from langchain_core.runnables import RunnableConfig

from app.graph.state import StoryState
from app.llm.gateway import LLMGateway
from app.llm.schemas import GenerateOutputResponse, StoryEvaluationResponse
from app.prompts.loader import get_prompt
from app.services.jira import JiraClient

logger = logging.getLogger(__name__)


def _safe(value: object) -> str:
    if value is None:
        return "Not provided"
    return str(value)


async def evaluate_story(state: StoryState, config: RunnableConfig) -> dict:
    langfuse: Langfuse = config["configurable"]["langfuse"]
    gateway: LLMGateway = config["configurable"]["gateway"]
    story = state["story_data"]

    with langfuse.start_as_current_observation(name="evaluate_story", as_type="span", input=story):
        system_prompt = get_prompt("evaluate_story", "system")
        user_prompt = get_prompt(
            "evaluate_story",
            "user",
            summary=_safe(story.get("summary")),
            description=_safe(story.get("description")),
            acceptance_criteria=_safe(story.get("acceptance_criteria")),
            story_points=_safe(story.get("story_points")),
            labels=_safe(story.get("labels")),
            components=_safe(story.get("components")),
            priority=_safe(story.get("priority")),
        )

        result = await gateway.call(
            response_model=StoryEvaluationResponse,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            langfuse=langfuse,
        )

        evaluation = {
            "user_story_clarity": {
                "score": result.user_story_clarity.score,
                "reasoning": result.user_story_clarity.reasoning,
            },
            "acceptance_criteria_quality": {
                "score": result.acceptance_criteria_quality.score,
                "reasoning": result.acceptance_criteria_quality.reasoning,
            },
            "technical_clarity": {
                "score": result.technical_clarity.score,
                "reasoning": result.technical_clarity.reasoning,
            },
            "dependencies": {
                "score": result.dependencies.score,
                "reasoning": result.dependencies.reasoning,
            },
            "sizing": {"score": result.sizing.score, "reasoning": result.sizing.reasoning},
        }

    return {"evaluation": evaluation}


async def generate_output(state: StoryState, config: RunnableConfig) -> dict:
    langfuse: Langfuse = config["configurable"]["langfuse"]
    gateway: LLMGateway = config["configurable"]["gateway"]
    evaluation = state["evaluation"]

    with langfuse.start_as_current_observation(
        name="generate_output", as_type="span", input={"evaluation": evaluation}
    ):
        system_prompt = get_prompt("generate_output", "system")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_prompt = get_prompt(
            "generate_output",
            "user",
            evaluation=str(evaluation),
            timestamp=timestamp,
        )

        result = await gateway.call(
            response_model=GenerateOutputResponse,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            langfuse=langfuse,
        )

    return {
        "final_score": result.final_score,
        "rounded_score": result.rounded_score,
        "remediation_suggestions": [
            {"criterion": s.criterion, "suggestion": s.suggestion}
            for s in result.remediation_suggestions
        ],
        "jira_comment": result.jira_comment,
    }


async def determine_category(state: StoryState, config: RunnableConfig) -> dict:
    langfuse: Langfuse = config["configurable"]["langfuse"]
    rounded_score = state["rounded_score"]

    with langfuse.start_as_current_observation(
        name="determine_category", as_type="span", input={"rounded_score": rounded_score}
    ):
        category = "NOT READY" if rounded_score <= 3 else "READY"
        langfuse.update_current_span(output={"category": category})

    return {"category": category}


async def jira_write(state: StoryState, config: RunnableConfig) -> dict:
    langfuse: Langfuse = config["configurable"]["langfuse"]
    jira_client: JiraClient = config["configurable"]["jira_client"]

    issue_key = state["issue_key"]
    category = state["category"]
    jira_comment = state["jira_comment"]

    with langfuse.start_as_current_observation(
        name="jira_write", as_type="span", input={"issue_key": issue_key, "category": category}
    ):
        try:
            await jira_client.add_comment(issue_key, jira_comment)

            if category == "NOT READY":
                await jira_client.transition_issue(issue_key, "Not Dev Ready")

            langfuse.update_current_span(output={"status": "success"})
            return {"jira_write_status": "success"}

        except Exception as e:
            logger.exception("Jira write failed for %s", issue_key)
            langfuse.update_current_span(output={"status": "failed", "error": str(e)})
            return {"jira_write_status": f"failed: {e}"}
