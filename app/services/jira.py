import logging
from base64 import b64encode

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.JIRA_BASE_URL.rstrip("/")
        credentials = b64encode(
            f"{settings.JIRA_USER_EMAIL}:{settings.JIRA_API_TOKEN}".encode()
        ).decode()
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def add_comment(self, issue_key: str, body: str) -> dict:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}/comment"
        payload = {"body": body}
        logger.info("Posting comment to %s", issue_key)
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        logger.info("Comment posted successfully to %s", issue_key)
        return result

    async def transition_issue(self, issue_key: str, transition_name: str) -> dict:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}/transitions"

        logger.info("Fetching transitions for %s", issue_key)
        response = await self.client.get(url)
        response.raise_for_status()
        transitions = response.json().get("transitions", [])

        transition_id = None
        for t in transitions:
            if t["name"] == transition_name:
                transition_id = t["id"]
                break

        if transition_id is None:
            logger.error(
                "Transition '%s' not found for %s. Available: %s",
                transition_name,
                issue_key,
                [t["name"] for t in transitions],
            )
            return {"error": f"Transition '{transition_name}' not found"}

        payload = {"transition": {"id": transition_id}}
        logger.info("Transitioning %s to '%s' (id=%s)", issue_key, transition_name, transition_id)
        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        logger.info("Transition successful for %s", issue_key)
        return {"status": "transitioned", "transition_id": transition_id}

    async def close(self) -> None:
        await self.client.aclose()
