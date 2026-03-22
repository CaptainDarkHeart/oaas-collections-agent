"""Email alerts to SME business owners.

Sends notification emails when the agent needs human attention:
disputes, hostile responses, phase 4 exhaustion, promise-to-pay confirmations.

Uses Instantly.ai (same sender infrastructure) for alert delivery.
"""

from __future__ import annotations

from src.executor.email_sender import EmailResult, InstantlyClient


def send_owner_alert(
    client: InstantlyClient,
    owner_email: str,
    owner_name: str,
    subject: str,
    body: str,
) -> EmailResult:
    """Send an alert email to the SME business owner."""
    return client.send_email(
        to_email=owner_email,
        to_name=owner_name,
        subject=subject,
        body=body,
        from_name="OaaS Collections Agent",
    )


def alert_dispute(
    client: InstantlyClient,
    owner_email: str,
    owner_name: str,
    invoice_number: str,
    debtor_company: str,
    reply_excerpt: str,
) -> EmailResult:
    """Alert the SME owner that an invoice has been disputed."""
    return send_owner_alert(
        client=client,
        owner_email=owner_email,
        owner_name=owner_name,
        subject=f"Action required: Invoice #{invoice_number} disputed by {debtor_company}",
        body=(
            f"Hi {owner_name},\n\n"
            f"Your debtor {debtor_company} has disputed Invoice #{invoice_number}. "
            f"Our agent has paused all automated outreach on this invoice.\n\n"
            f"Their reply:\n\"{reply_excerpt[:500]}\"\n\n"
            f"Please review and let us know how to proceed. You can clear the "
            f"dispute flag in your dashboard to re-enable the agent, or handle "
            f"this one directly.\n\n"
            f"— OaaS Collections Agent"
        ),
    )


def alert_hostile(
    client: InstantlyClient,
    owner_email: str,
    owner_name: str,
    invoice_number: str,
    debtor_company: str,
    reply_excerpt: str,
) -> EmailResult:
    """Alert the SME owner of a hostile response."""
    return send_owner_alert(
        client=client,
        owner_email=owner_email,
        owner_name=owner_name,
        subject=f"Attention: Hostile response on Invoice #{invoice_number}",
        body=(
            f"Hi {owner_name},\n\n"
            f"We received a hostile response from {debtor_company} regarding "
            f"Invoice #{invoice_number}. Our agent has stopped all contact "
            f"and will not send any further messages.\n\n"
            f"Their reply:\n\"{reply_excerpt[:500]}\"\n\n"
            f"This requires your personal review. Please check the dashboard "
            f"for full details.\n\n"
            f"— OaaS Collections Agent"
        ),
    )


def alert_human_review(
    client: InstantlyClient,
    owner_email: str,
    owner_name: str,
    invoice_number: str,
    debtor_company: str,
    reason: str,
) -> EmailResult:
    """Alert the SME owner that an invoice needs human review."""
    return send_owner_alert(
        client=client,
        owner_email=owner_email,
        owner_name=owner_name,
        subject=f"Review needed: Invoice #{invoice_number} — {debtor_company}",
        body=(
            f"Hi {owner_name},\n\n"
            f"Invoice #{invoice_number} ({debtor_company}) has been flagged "
            f"for your review.\n\n"
            f"Reason: {reason}\n\n"
            f"The agent has paused automated outreach. Please check the "
            f"dashboard and decide on next steps.\n\n"
            f"— OaaS Collections Agent"
        ),
    )


def alert_promise_to_pay(
    client: InstantlyClient,
    owner_email: str,
    owner_name: str,
    invoice_number: str,
    debtor_company: str,
    details: str,
) -> EmailResult:
    """Notify the SME owner of a promise to pay."""
    return send_owner_alert(
        client=client,
        owner_email=owner_email,
        owner_name=owner_name,
        subject=f"Good news: {debtor_company} committed to pay Invoice #{invoice_number}",
        body=(
            f"Hi {owner_name},\n\n"
            f"{debtor_company} has committed to paying Invoice #{invoice_number}.\n\n"
            f"Details: {details}\n\n"
            f"We'll monitor this and follow up if payment doesn't arrive on "
            f"the promised date.\n\n"
            f"— OaaS Collections Agent"
        ),
    )
