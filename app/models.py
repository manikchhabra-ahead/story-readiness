from typing import Optional

from pydantic import BaseModel, Field


class JiraWebhookPayload(BaseModel):
    issue_key: str
    summary: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    story_points: Optional[int] = None
    labels: Optional[list[str]] = Field(default_factory=list)
    components: Optional[list[str]] = Field(default_factory=list)
    priority: Optional[str] = None
