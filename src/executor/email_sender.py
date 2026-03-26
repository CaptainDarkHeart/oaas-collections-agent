"""Resend integration for outbound email delivery.

Handles:
- Sending emails via Resend's transactional API
- The "reply to sent" follow-up pattern (threading)
"""

from __future__ import annotations

from dataclasses import dataclass

import resend

from src.config import settings


@dataclass
class EmailResult:
    """Result of an email send attempt."""

    success: bool
    message_id: str | None = None
    error: str | None = None


class ResendClient:
    """Client for the Resend email sending API."""

    def __init__(self) -> None:
        resend.api_key = settings.resend_api_key

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
        """Send an email via Resend."""
        sender_email = from_email or settings.agent_default_email
        sender_name = from_name or settings.agent_default_name
        from_field = f"{sender_name} <{sender_email}>" if sender_name else sender_email

        params: resend.Emails.SendParams = {
            "from": from_field,
            "to": [to_email],
            "subject": subject,
            "text": body,
        }

        try:
            result = resend.Emails.send(params)
            return EmailResult(success=True, message_id=result.get("id"))
        except Exception as e:
            return EmailResult(success=False, error=str(e))

    def get_email_status(self, message_id: str) -> dict | None:
        """Check status of a sent email."""
        try:
            return resend.Emails.get(message_id)
        except Exception:
            return None


def send_collection_email(
    client: ResendClient,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    agent_name: str,
    agent_email: str | None = None,
    previous_message_id: str | None = None,
) -> EmailResult:
    """High-level function to send a collection email."""
    return client.send_email(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        body=body,
        from_email=agent_email or settings.agent_default_email,
        from_name=agent_name,
        reply_to_message_id=previous_message_id,
    )
