from typing import Optional
from typing_extensions import TypedDict


class CriterionEvaluation(TypedDict):
    score: int  # 1–5
    reasoning: str  # One sentence explaining the score


class StoryEvaluation(TypedDict):
    user_story_clarity: CriterionEvaluation
    acceptance_criteria_quality: CriterionEvaluation
    technical_clarity: CriterionEvaluation
    dependencies: CriterionEvaluation
    sizing: CriterionEvaluation


class RemediationSuggestion(TypedDict):
    criterion: str  # e.g. "acceptance_criteria_quality"
    suggestion: str  # Actionable fix tied to this criterion


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
    category: Optional[str]  # "READY" or "NOT READY"

    # Node 4 output
    jira_write_status: Optional[str]
