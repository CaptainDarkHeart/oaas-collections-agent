"""Instantly.ai integration for outbound email delivery.

Handles:
- Sending emails via Instantly's campaign/transactional API
- Sender account rotation (managed by Instantly)
- Tracking delivery and open status
- The "reply to sent" follow-up pattern (threading)

Instantly API docs: https://developer.instantly.ai/
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from src.config import settings


INSTANTLY_BASE_URL = "https://api.instantly.ai/api/v2"


@dataclass
class EmailResult:
    """Result of an email send attempt."""

    success: bool
    message_id: str | None = None
    error: str | None = None


class InstantlyClient:
    """Client for the Instantly.ai email sending API."""

    def __init__(self) -> None:
        self.api_key = settings.instantly_api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def send_email(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body: str,
        from_email: str | None = None,
        from_name: str | None = None,
        reply_to_message_id: str | None = None,
    ) -> EmailResult:
        """Send an email via Instantly.

        Args:
            to_email: Recipient email address.
            to_name: Recipient name.
            subject: Email subject line.
            body: Plain text email body.
            from_email: Sender email (Instantly handles rotation if None).
            from_name: Sender display name.
            reply_to_message_id: If set, thread this as a reply to the given message ID.

        Returns:
            EmailResult with success status and message ID.
        """
        payload: dict = {
            "to": to_email,
            "to_name": to_name,
            "subject": subject,
            "body": body,
        }

        if from_email:
            payload["from"] = from_email
        if from_name:
            payload["from_name"] = from_name
        if reply_to_message_id:
            payload["in_reply_to"] = reply_to_message_id

        try:
            resp = self.session.post(
                f"{INSTANTLY_BASE_URL}/emails/send",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return EmailResult(
                success=True,
                message_id=data.get("message_id"),
            )
        except requests.exceptions.RequestException as e:
            return EmailResult(success=False, error=str(e))

    def get_email_status(self, message_id: str) -> dict | None:
        """Check delivery/open status of a sent email."""
        try:
            resp = self.session.get(
                f"{INSTANTLY_BASE_URL}/emails/{message_id}",
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            return None

    def list_sending_accounts(self) -> list[dict]:
        """List available sending accounts for rotation visibility."""
        try:
            resp = self.session.get(
                f"{INSTANTLY_BASE_URL}/accounts",
            )
            resp.raise_for_status()
            return resp.json().get("accounts", [])
        except requests.exceptions.RequestException:
            return []


def send_collection_email(
    client: InstantlyClient,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    agent_name: str,
    agent_email: str | None = None,
    previous_message_id: str | None = None,
) -> EmailResult:
    """High-level function to send a collection email.

    Wraps InstantlyClient.send_email with agent defaults.
    """
    return client.send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
        from_email=agent_email or settings.agent_default_email,
        from_name=agent_name,
        reply_to_message_id=previous_message_id,
    )
