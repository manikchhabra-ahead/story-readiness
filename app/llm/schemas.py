from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    score: int = Field(ge=1, le=5, description="Score from 1 (missing/unusable) to 5 (exemplary)")
    reasoning: str = Field(description="One sentence explaining the score")


class StoryEvaluationResponse(BaseModel):
    user_story_clarity: CriterionScore
    acceptance_criteria_quality: CriterionScore
    technical_clarity: CriterionScore
    dependencies: CriterionScore
    sizing: CriterionScore


class RemediationItem(BaseModel):
    criterion: str = Field(description="The criterion name this suggestion addresses")
    suggestion: str = Field(description="Specific, actionable fix for this criterion")


class GenerateOutputResponse(BaseModel):
    final_score: float = Field(description="Average of all 5 criterion scores")
    rounded_score: int = Field(description="final_score rounded to nearest whole number")
    remediation_suggestions: list[RemediationItem] = Field(
        description="Suggestions only for criteria scoring 1-3"
    )
    blocker_summary: str = Field(
        description=(
            "One plain-English sentence naming the blocking criteria (those "
            "scoring 1 or 2) and what the reporter must do. Empty string if "
            "there are no blockers."
        )
    )
