"""Webhook handlers for Codat and Stripe events.

Provides FastAPI router endpoints for:
- Codat push notifications (invoice paid, data sync complete)
- Stripe checkout.session.completed (SME fee payment confirmed)

Mount this router on the main FastAPI app.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from src.billing.stripe_billing import StripeBilling
from src.config import settings
from src.db.models import (
    Database,
    Fee,
    FeeType,
    InvoicePhase,
    InvoiceStatus,
)
from src.notifications import slack_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Codat webhooks
# ---------------------------------------------------------------------------


@router.post("/codat", dependencies=[])
async def codat_webhook(
    request: Request,
    x_codat_signature: str | None = Header(None),
) -> dict:
    """Handle Codat push notification webhooks.

    Codat sends events when data syncs complete or when specific
    data changes are detected (e.g., invoice status changes).
    """
    body = await request.body()

    if settings.codat_webhook_secret and x_codat_signature:
        if not _verify_codat_signature(body, x_codat_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("AlertType", payload.get("type", ""))
    company_id = payload.get("CompanyId", payload.get("companyId", ""))

    # Deduplicate: use AlertId if present, otherwise combine CompanyId + AlertType
    event_id = payload.get("AlertId") or f"{company_id}:{event_type}"

    # Check idempotency if DB is available
    if settings.supabase_url:
        db = Database()
        if db.has_processed_event(event_id):
            logger.info("Codat webhook duplicate ignored: %s", event_id)
            return {"received": True, "duplicate": True}

    logger.info("Codat webhook: type=%s company=%s", event_type, company_id)

    if event_type in ("invoices.dataSync.completed", "DataSyncCompleted"):
        # A data sync finished — trigger our sync job for this company
        _handle_codat_sync_complete(company_id, payload)
    elif event_type in ("invoices.dataChanged", "DataChanged"):
        _handle_codat_data_changed(company_id, payload)

    if settings.supabase_url:
        db.mark_event_processed(event_id, "codat", event_type)

    return {"received": True}


def _verify_codat_signature(body: bytes, signature: str) -> bool:
    """Verify Codat webhook HMAC signature."""
    expected = hmac.HMAC(
        settings.codat_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _handle_codat_sync_complete(company_id: str, payload: dict) -> None:
    """Handle a Codat data sync completion event."""
    data_type = payload.get("DataType", payload.get("dataType", ""))
    logger.info("Codat sync complete for company %s, data type: %s", company_id, data_type)

    if data_type == "invoices":
        # Run targeted sync for just this company
        from src.sentry.invoice_sync import run_invoice_sync

        run_invoice_sync()


def _handle_codat_data_changed(company_id: str, payload: dict) -> None:
    """Handle a Codat data-changed event (e.g., invoice marked paid)."""
    logger.info("Codat data changed for company %s: %s", company_id, payload)
    # The daily sync will pick up changes; this is just for logging


# ---------------------------------------------------------------------------
# Stripe webhooks
# ---------------------------------------------------------------------------


@router.post("/stripe", dependencies=[])
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
) -> dict:
    """Handle Stripe webhook events.

    Processes:
    - checkout.session.completed: SME paid their recovery fee
    - payment_intent.payment_failed: Fee payment failed
    """
    body = await request.body()
    billing = StripeBilling()

    try:
        event = billing.verify_webhook_signature(body, stripe_signature)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    # Check idempotency if DB is available
    if settings.supabase_url and event_id:
        db = Database()
        if db.has_processed_event(event_id):
            logger.info("Stripe webhook duplicate ignored: %s", event_id)
            return {"received": True, "duplicate": True}

    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(billing, event)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event)

    if settings.supabase_url and event_id:
        db.mark_event_processed(event_id, "stripe", event_type)

    return {"received": True}


def _handle_checkout_completed(billing: StripeBilling, event: dict) -> None:
    """Process a successful fee payment from an SME, or a debtor payment."""
    result = billing.handle_checkout_completed(event)
    if not result:
        # Not a fee payment — check if it's a debtor payment
        session = event.get("data", {}).get("object", {})
        metadata = session.get("metadata", {})
        if metadata.get("payment_type") == "debtor_payment":
            _handle_debtor_payment(event)
        return

    db = Database()
    invoice_id = result.get("invoice_id")
    payment_intent_id = result.get("payment_intent_id")
    invoice_number = result.get("invoice_number", "?")

    if invoice_id:
        db.update_invoice(
            UUID(invoice_id),
            {
                "fee_charged": True,
                "fee_amount": result.get("amount_total", 0) / 100,
            },
        )

    logger.info(
        "Fee payment confirmed for invoice %s (PI: %s)",
        invoice_number,
        payment_intent_id,
    )

    slack_webhook.send_alert(
        title="Fee Payment Received",
        message=f"SME paid recovery fee for invoice {invoice_number}",
        invoice_number=invoice_number,
        severity="info",
    )


def _handle_debtor_payment(event: dict) -> None:
    """Process a successful debtor payment via Stripe payment link.

    Marks the invoice as PAID/RESOLVED, calculates our fee, creates a Fee
    record, sends a Slack notification, and attempts to write back the
    payment to the connected accounting software.
    """
    session = event.get("data", {}).get("object", {})
    metadata = session.get("metadata", {})
    invoice_id_str = metadata.get("invoice_id")
    invoice_number = metadata.get("invoice_number", "?")
    debtor_company = metadata.get("debtor_company", "?")

    if not invoice_id_str:
        logger.warning("Debtor payment webhook missing invoice_id in metadata")
        return

    invoice_id = UUID(invoice_id_str)

    # Amount from Stripe is in minor units (pence/cents)
    amount_total = session.get("amount_total", 0)
    amount = Decimal(amount_total) / 100

    demo_mode = not os.environ.get("SUPABASE_URL")
    if demo_mode:
        logger.info(
            "DEMO MODE: Would mark invoice %s as paid (amount=%s)", invoice_number, amount
        )
        return

    db = Database()

    now = datetime.now(tz=UTC).replace(tzinfo=None)

    # Mark invoice as paid and resolved
    db.update_invoice(
        invoice_id,
        {
            "status": InvoiceStatus.PAID,
            "current_phase": InvoicePhase.RESOLVED,
            "resolved_at": now,
        },
    )

    # Calculate fee: 10% for invoices over threshold, else flat fee
    if amount > Decimal(str(settings.fee_percentage_threshold)):
        fee_amount = amount * Decimal(str(settings.fee_percentage)) / 100
        fee_type = FeeType.PERCENTAGE
    else:
        fee_amount = Decimal(str(settings.fee_flat_amount))
        fee_type = FeeType.FLAT

    # Get invoice to find sme_id
    invoice_data = db.get_invoice(invoice_id)
    sme_id = UUID(invoice_data["sme_id"]) if invoice_data else None

    if sme_id:
        fee = Fee(
            invoice_id=invoice_id,
            sme_id=sme_id,
            fee_type=fee_type,
            fee_amount=fee_amount,
            invoice_amount_recovered=amount,
        )
        db.create_fee(fee)

    logger.info(
        "Debtor payment confirmed for invoice %s (%s): amount=%s, fee=%s (%s)",
        invoice_number,
        debtor_company,
        amount,
        fee_amount,
        fee_type.value,
    )

    slack_webhook.send_alert(
        title="Debtor Payment Received",
        message=(
            f"Debtor {debtor_company} paid invoice {invoice_number} "
            f"({settings.default_currency} {amount:.2f}). "
            f"Fee: {settings.default_currency} {fee_amount:.2f} ({fee_type.value})."
        ),
        invoice_number=invoice_number,
        severity="info",
    )

    # Attempt write-back to accounting software
    try:
        from src.sentry.write_back import write_back_payment

        write_back_payment(db, invoice_id)
    except Exception:
        logger.warning(
            "Write-back failed for invoice %s — will retry on next sync",
            invoice_number,
            exc_info=True,
        )


def _handle_payment_failed(event: dict) -> None:
    """Log a failed fee payment attempt."""
    session = event.get("data", {}).get("object", {})
    metadata = session.get("metadata", {})
    invoice_number = metadata.get("invoice_number", "?")

    logger.warning("Fee payment FAILED for invoice %s", invoice_number)

    slack_webhook.send_alert(
        title="Fee Payment Failed",
        message=f"SME fee payment failed for invoice {invoice_number}. Will retry.",
        invoice_number=invoice_number,
        severity="warning",
    )
