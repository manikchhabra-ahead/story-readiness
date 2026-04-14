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


CRITERION_LABELS = {
    "user_story_clarity": "User Story Clarity",
    "acceptance_criteria_quality": "Acceptance Criteria",
    "technical_clarity": "Technical Clarity",
    "dependencies": "Dependencies",
    "sizing": "Sizing",
}


def _safe(value: object) -> str:
    if value is None:
        return "Not provided"
    if isinstance(value, str) and not value.strip():
        return "Not provided"
    return str(value)


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _build_jira_comment(
    category: str,
    rounded_score: int,
    timestamp: str,
    evaluation: dict,
    remediations: list[dict],
    blocker_summary: str,
) -> str:
    breakdown = "\n".join(
        f"- {CRITERION_LABELS[key]}: {evaluation[key]['score']}/5 — {evaluation[key]['reasoning']}"
        for key in CRITERION_LABELS
    )

    if category == "READY":
        return (
            "✅ Story Readiness Analysis\n"
            f"Score: {rounded_score}/5 — READY FOR DEV\n"
            f"Analyzed: {timestamp}\n\n"
            "Criteria breakdown:\n"
            f"{breakdown}\n\n"
            "No blockers found. Story is cleared for development."
        )

    blockers = [r for r in remediations if evaluation[r["criterion"]]["score"] <= 2]
    improvements = [r for r in remediations if evaluation[r["criterion"]]["score"] == 3]

    sections = [
        "🚫 Story Readiness Analysis",
        f"Score: {rounded_score}/5 — NOT READY FOR DEV",
        f"Analyzed: {timestamp}",
        "",
    ]

    if blocker_summary:
        sections += ["Why this story isn't ready:", blocker_summary, ""]

    if blockers:
        sections.append("Must fix before re-submitting:")
        sections += [
            f"- [{CRITERION_LABELS.get(b['criterion'], b['criterion'])}] {b['suggestion']}"
            for b in blockers
        ]
        sections.append("")

    if improvements:
        sections.append("Should improve:")
        sections += [
            f"- [{CRITERION_LABELS.get(i['criterion'], i['criterion'])}] {i['suggestion']}"
            for i in improvements
        ]
        sections.append("")

    sections += [
        "Full criteria breakdown:",
        breakdown,
        "",
        'Please address the "Must fix" items and transition back to Dev Ready.',
    ]

    return "\n".join(sections)


async def evaluate_story(state: StoryState, config: RunnableConfig) -> dict:
    issue_key = state["issue_key"]
    langfuse: Langfuse = config["configurable"]["langfuse"]
    gateway: LLMGateway = config["configurable"]["gateway"]
    story = state["story_data"]

    logger.info("[%s] Node: evaluate_story — starting LLM evaluation", issue_key)

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

    # Deterministic floors: override the LLM when a required source field is
    # actually empty. Prevents the model from inferring evidence from adjacent
    # fields (e.g. reading "acceptance criteria" out of the description).
    if _is_blank(story.get("acceptance_criteria")):
        evaluation["acceptance_criteria_quality"] = {
            "score": 1,
            "reasoning": "Acceptance Criteria field is empty.",
        }
    if _is_blank(story.get("summary")):
        evaluation["user_story_clarity"] = {
            "score": 1,
            "reasoning": "Summary is empty.",
        }
    if _is_blank(story.get("description")):
        evaluation["technical_clarity"] = {
            "score": 1,
            "reasoning": "Description is empty.",
        }

    scores = {k: v["score"] for k, v in evaluation.items()}
    logger.info("[%s] Node: evaluate_story — scores: %s", issue_key, scores)

    return {"evaluation": evaluation}


async def generate_output(state: StoryState, config: RunnableConfig) -> dict:
    issue_key = state["issue_key"]
    langfuse: Langfuse = config["configurable"]["langfuse"]
    gateway: LLMGateway = config["configurable"]["gateway"]
    evaluation = state["evaluation"]

    scores = {k: v["score"] for k, v in evaluation.items()}
    min_score = min(scores.values())
    blocker_criteria = [k for k, s in scores.items() if s <= 2]
    computed_final = sum(scores.values()) / len(scores)
    computed_rounded = round(computed_final)
    category_preview = "READY" if computed_rounded >= 4 and min_score >= 3 else "NOT READY"

    logger.info(
        "[%s] Node: generate_output — min_score=%d blockers=%s category_preview=%s",
        issue_key,
        min_score,
        blocker_criteria,
        category_preview,
    )

    with langfuse.start_as_current_observation(
        name="generate_output",
        as_type="span",
        input={
            "evaluation": evaluation,
            "min_score": min_score,
            "blocker_criteria": blocker_criteria,
        },
    ):
        system_prompt = get_prompt("generate_output", "system")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        user_prompt = get_prompt(
            "generate_output",
            "user",
            evaluation=str(evaluation),
            final_score=f"{computed_final:.2f}",
            rounded_score=computed_rounded,
            min_score=min_score,
            blocker_criteria=str(blocker_criteria),
            timestamp=timestamp,
        )

        result = await gateway.call(
            response_model=GenerateOutputResponse,
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            langfuse=langfuse,
        )

    remediations = [
        {"criterion": s.criterion, "suggestion": s.suggestion}
        for s in result.remediation_suggestions
    ]

    jira_comment = _build_jira_comment(
        category=category_preview,
        rounded_score=result.rounded_score,
        timestamp=timestamp,
        evaluation=evaluation,
        remediations=remediations,
        blocker_summary=result.blocker_summary,
    )

    logger.info(
        "[%s] Node: generate_output — final_score=%.1f rounded_score=%d min_score=%d remediations=%d",
        issue_key,
        result.final_score,
        result.rounded_score,
        min_score,
        len(remediations),
    )

    return {
        "final_score": result.final_score,
        "rounded_score": result.rounded_score,
        "min_score": min_score,
        "remediation_suggestions": remediations,
        "blocker_summary": result.blocker_summary,
        "jira_comment": jira_comment,
    }


async def determine_category(state: StoryState, config: RunnableConfig) -> dict:
    issue_key = state["issue_key"]
    langfuse: Langfuse = config["configurable"]["langfuse"]
    rounded_score = state["rounded_score"]
    min_score = state["min_score"]

    with langfuse.start_as_current_observation(
        name="determine_category",
        as_type="span",
        input={"rounded_score": rounded_score, "min_score": min_score},
    ):
        # Require both a strong average AND no single catastrophic criterion.
        # A story with any criterion ≤ 2 cannot be READY, even if the average rounds to 4+.
        category = "READY" if rounded_score >= 4 and min_score >= 3 else "NOT READY"
        langfuse.update_current_span(
            output={"category": category, "rounded_score": rounded_score, "min_score": min_score}
        )

    logger.info(
        "[%s] Node: determine_category — rounded=%d min=%d → %s",
        issue_key,
        rounded_score,
        min_score,
        category,
    )

    return {"category": category}


async def jira_write(state: StoryState, config: RunnableConfig) -> dict:
    langfuse: Langfuse = config["configurable"]["langfuse"]
    jira_client: JiraClient = config["configurable"]["jira_client"]

    issue_key = state["issue_key"]
    category = state["category"]
    jira_comment = state["jira_comment"]

    logger.info("[%s] Node: jira_write — posting comment, category=%s", issue_key, category)

    with langfuse.start_as_current_observation(
        name="jira_write", as_type="span", input={"issue_key": issue_key, "category": category}
    ):
        try:
            await jira_client.add_comment(issue_key, jira_comment)
            logger.info("[%s] Node: jira_write — comment posted", issue_key)

            if category == "NOT READY":
                await jira_client.transition_issue(issue_key, "Not Dev Ready")
                logger.info("[%s] Node: jira_write — transitioned to Not Dev Ready", issue_key)

            langfuse.update_current_span(output={"status": "success"})
            return {"jira_write_status": "success"}

        except Exception as e:
            logger.exception("[%s] Node: jira_write — failed: %s", issue_key, e)
            langfuse.update_current_span(output={"status": "failed", "error": str(e)})
            return {"jira_write_status": f"failed: {e}"}
