"""OaaS Collections Agent — main orchestrator and scheduler.

Runs the daily processing loop:
1. Scan all active invoices
2. For each invoice, check cadence and decide next action
3. Generate and send messages via the appropriate channel
4. Process any inbound replies and classify them
5. Handle state transitions and notifications

Can be run as a one-shot daily job (cron) or as a long-running scheduler.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from uuid import UUID

import anthropic

from src.config import settings
from src.db.models import (
    Channel,
    Classification,
    Database,
    Direction,
    Interaction,
    InvoicePhase,
    MessageType,
)
from src.executor.cadence import can_contact_today, is_within_daily_limit, schedule_next_send
from src.executor.email_sender import ResendClient, send_collection_email
from src.executor.payment_link import StripePaymentLinks
from src.notifications import email_alerts, slack_webhook
from src.strategist.message_generator import MessageContext, generate_message
from src.strategist.response_classifier import classify_response
from src.strategist.state_machine import (
    handle_classification,
    should_escalate,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_daily_cycle(
    db: Database | None = None,
    email_client: ResendClient | None = None,
    payment_links: StripePaymentLinks | None = None,
) -> None:
    """Run the full daily processing cycle for all active invoices."""
    db = db or Database()
    email_client = email_client or ResendClient()
    payment_links = payment_links or StripePaymentLinks()
    emails_sent_today = 0

    logger.info("Starting daily cycle at %s", datetime.now(tz=UTC).replace(tzinfo=None).isoformat())

    for sme in db.list_active_smes():
        sme_id = sme["id"]
        sme_name = sme["company_name"]
        logger.info("Processing SME: %s (%s)", sme_name, sme_id)

        for invoice in db.list_active_invoices(sme_id=UUID(sme_id)):
            if not is_within_daily_limit(emails_sent_today):
                logger.warning("Daily email limit reached (%d). Stopping.", emails_sent_today)
                return

            sent = _process_invoice(db, email_client, payment_links, sme, invoice)
            if sent:
                emails_sent_today += 1

    logger.info("Daily cycle complete. Emails sent: %d", emails_sent_today)


def _process_invoice(
    db: Database,
    email_client: ResendClient,
    payment_links: StripePaymentLinks,
    sme: dict,
    invoice: dict,
) -> bool:
    """Process a single invoice: check state, generate message, send.

    Returns True if an email was sent.
    """
    invoice_id = UUID(invoice["id"])
    current_phase = InvoicePhase(invoice["current_phase"])

    # Skip non-actionable phases
    if current_phase in (InvoicePhase.HUMAN_REVIEW, InvoicePhase.RESOLVED, InvoicePhase.DISPUTED):
        return False

    contact = db.get_primary_contact(invoice_id)
    if not contact:
        logger.warning("No primary contact for invoice %s — skipping", invoice["invoice_number"])
        return False

    # Check last outbound interaction
    last_outbound = db.get_latest_outbound(invoice_id)
    last_outbound_at = datetime.fromisoformat(last_outbound["sent_at"]) if last_outbound else None

    # Enforce minimum contact gap
    if not can_contact_today(last_outbound_at):
        return False

    # Count interactions in current phase
    interactions = db.list_interactions(invoice_id)
    interactions_in_phase = sum(
        1
        for i in interactions
        if i["direction"] == Direction.OUTBOUND.value and str(i["phase"]) == current_phase.value
    )

    # Check if we should escalate to the next phase
    if interactions_in_phase > 0 and should_escalate(current_phase, last_outbound_at):
        result = handle_classification(Classification.NO_RESPONSE, current_phase, invoice_id, db)
        logger.info("Invoice %s: %s", invoice["invoice_number"], result.message)

        if result.action in ("pause", "human_review"):
            _send_notifications(db, email_client, sme, invoice, result.message)
            return False

        # Refresh phase after escalation
        updated = db.get_invoice(invoice_id)
        if updated:
            current_phase = InvoicePhase(updated["current_phase"])
            interactions_in_phase = 0

    # Calculate due date info
    due_date = date.fromisoformat(invoice["due_date"])
    days_overdue = (date.today() - due_date).days

    # Check cadence schedule
    phase_start = _get_phase_start_date(interactions, current_phase, invoice)
    next_send = schedule_next_send(
        phase=current_phase,
        phase_start_date=phase_start,
        interactions_in_phase=interactions_in_phase,
        last_contact_at=last_outbound_at,
    )

    if next_send is None:
        return False  # All follow-ups exhausted for this phase

    if next_send.date() > date.today():
        return False  # Not time yet

    # Generate a payment link for this invoice (if Stripe is configured)
    payment_link_url = None
    if settings.stripe_secret_key:
        # Reuse cached payment link if available
        cached_url = invoice.get("payment_link_url")
        if cached_url:
            payment_link_url = cached_url
        else:
            from decimal import Decimal as _Decimal

            link_result = payment_links.create_invoice_payment_link(
                invoice_id=invoice_id,
                invoice_number=invoice["invoice_number"],
                debtor_company=invoice["debtor_company"],
                amount=_Decimal(str(invoice["amount"])),
                currency=invoice.get("currency", "GBP"),
                sme_id=UUID(sme["id"]),
            )
            if link_result.success:
                payment_link_url = link_result.url
                db.update_invoice(
                    invoice_id,
                    {
                        "payment_link_url": link_result.url,
                        "payment_link_id": link_result.payment_link_id,
                    },
                )

    # Build context and generate message
    previous_messages = [
        i["content"] for i in interactions if i["direction"] == Direction.OUTBOUND.value
    ][-3:]

    ctx = MessageContext(
        agent_name=settings.agent_default_name,
        sme_name=sme["company_name"],
        invoice_number=invoice["invoice_number"],
        debtor_company=invoice["debtor_company"],
        contact_name=contact["name"],
        contact_email=contact["email"],
        amount=str(invoice["amount"]),
        currency=invoice.get("currency", "GBP"),
        days_overdue=days_overdue,
        due_date=invoice["due_date"],
        phase=current_phase,
        interaction_count_in_phase=interactions_in_phase,
        previous_messages=previous_messages,
        discount_authorised=sme.get("discount_authorised", False),
        max_discount_percent=float(sme.get("max_discount_percent", 0)),
        payment_link_url=payment_link_url,
    )

    try:
        msg = generate_message(ctx)
    except (anthropic.APIError, RuntimeError):
        logger.exception("Failed to generate message for invoice %s", invoice["invoice_number"])
        return False

    # Send the email
    previous_message_id = (
        last_outbound.get("metadata", {}).get("message_id") if last_outbound else None
    )

    send_result = send_collection_email(
        client=email_client,
        to_email=contact["email"],
        to_name=contact["name"],
        subject=msg.subject,
        body=msg.body,
        agent_name=settings.agent_default_name,
        previous_message_id=previous_message_id if msg.is_reply_to_sent else None,
    )

    if not send_result.success:
        logger.error(
            "Failed to send email for invoice %s: %s",
            invoice["invoice_number"],
            send_result.error,
        )
        return False

    # Log the interaction
    message_type = MessageType.INITIAL if interactions_in_phase == 0 else MessageType.FOLLOW_UP
    interaction = Interaction(
        invoice_id=invoice_id,
        contact_id=UUID(contact["id"]),
        phase=int(current_phase.value),
        channel=Channel.EMAIL,
        direction=Direction.OUTBOUND,
        message_type=message_type,
        content=f"Subject: {msg.subject}\n\n{msg.body}",
        sent_at=datetime.now(tz=UTC).replace(tzinfo=None),
        delivered=True,
        metadata={"message_id": send_result.message_id, "is_reply_to_sent": msg.is_reply_to_sent},
    )
    db.create_interaction(interaction)

    logger.info(
        "Sent %s email for invoice %s (Phase %s, #%d in phase)",
        message_type.value,
        invoice["invoice_number"],
        current_phase.value,
        interactions_in_phase + 1,
    )
    return True


def process_inbound_reply(
    db: Database,
    email_client: ResendClient,
    invoice_id: UUID,
    contact_id: UUID,
    reply_text: str,
) -> None:
    """Process an inbound email reply: classify, log, transition state, notify."""
    invoice = db.get_invoice(invoice_id)
    if not invoice:
        logger.error("Invoice %s not found", invoice_id)
        return

    current_phase = InvoicePhase(invoice["current_phase"])

    # Classify the reply
    classification, justification = classify_response(reply_text)
    logger.info(
        "Invoice %s reply classified as %s: %s",
        invoice["invoice_number"],
        classification.value,
        justification,
    )

    # Log the inbound interaction
    interaction = Interaction(
        invoice_id=invoice_id,
        contact_id=contact_id,
        phase=int(current_phase.value),
        channel=Channel.EMAIL,
        direction=Direction.INBOUND,
        message_type=MessageType.RESPONSE,
        content=reply_text,
        classification=classification,
        sent_at=datetime.now(tz=UTC).replace(tzinfo=None),
        delivered=True,
        replied=True,
    )
    db.create_interaction(interaction)

    # Handle the classification
    result = handle_classification(classification, current_phase, invoice_id, db)
    logger.info("Invoice %s: %s", invoice["invoice_number"], result.message)

    # Get SME for notifications
    sme = db.get_sme(UUID(invoice["sme_id"]))
    if not sme:
        logger.error("SME %s not found for invoice %s", invoice["sme_id"], invoice_id)
        return

    # Send notifications for pause/review actions
    if result.action == "pause":
        _send_notifications(db, email_client, sme, invoice, result.message)

        if classification == Classification.DISPUTE:
            slack_webhook.notify_dispute(
                invoice["invoice_number"], invoice["debtor_company"], reply_text[:200]
            )
            email_alerts.alert_dispute(
                email_client,
                sme["contact_email"],
                sme["company_name"],
                invoice["invoice_number"],
                invoice["debtor_company"],
                reply_text,
            )
        elif classification == Classification.HOSTILE:
            slack_webhook.notify_hostile(
                invoice["invoice_number"], invoice["debtor_company"], reply_text[:200]
            )
            email_alerts.alert_hostile(
                email_client,
                sme["contact_email"],
                sme["company_name"],
                invoice["invoice_number"],
                invoice["debtor_company"],
                reply_text,
            )

    elif result.action == "redirect":
        # TODO: Parse new contact details from reply and add to sequence
        logger.info(
            "Invoice %s: redirect detected — needs new contact extraction",
            invoice["invoice_number"],
        )

    elif result.action == "monitor" and classification == Classification.PROMISE_TO_PAY:
        email_alerts.alert_promise_to_pay(
            email_client,
            sme["contact_email"],
            sme["company_name"],
            invoice["invoice_number"],
            invoice["debtor_company"],
            justification,
        )


def _send_notifications(
    db: Database,
    email_client: ResendClient,
    sme: dict,
    invoice: dict,
    reason: str,
) -> None:
    """Send Slack + email notifications for human-review events."""
    slack_webhook.notify_human_review(invoice["invoice_number"], invoice["debtor_company"], reason)
    email_alerts.alert_human_review(
        email_client,
        sme["contact_email"],
        sme["company_name"],
        invoice["invoice_number"],
        invoice["debtor_company"],
        reason,
    )


def _get_phase_start_date(
    interactions: list[dict],
    current_phase: InvoicePhase,
    invoice: dict,
) -> date:
    """Determine when the current phase started based on interaction history."""
    for interaction in interactions:
        if (
            str(interaction["phase"]) == current_phase.value
            and interaction["direction"] == Direction.OUTBOUND.value
        ):
            return datetime.fromisoformat(interaction["sent_at"]).date()

    # If no interactions in this phase yet, use the invoice creation date
    return datetime.fromisoformat(invoice["created_at"]).date()


if __name__ == "__main__":
    run_daily_cycle()
