from typing import Optional

from pydantic import BaseModel, Field, field_validator


class JiraWebhookPayload(BaseModel):
    issue_key: str
    summary: Optional[str] = None
    description: Optional[str] = None
    acceptance_criteria: Optional[str] = None
    story_points: Optional[int] = None
    labels: Optional[list[str]] = Field(default_factory=list)
    components: Optional[list[str]] = Field(default_factory=list)
    priority: Optional[str] = None

    @field_validator("story_points", mode="before")
    @classmethod
    def parse_story_points(cls, v):
        return None if v == "" else v

    @field_validator("labels", "components", mode="before")
    @classmethod
    def parse_list_fields(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v
