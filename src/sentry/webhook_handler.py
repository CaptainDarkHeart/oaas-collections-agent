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
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from src.billing.stripe_billing import StripeBilling
from src.config import settings
from src.db.models import (
    Database,
    FeeStatus,
    InvoicePhase,
    InvoiceStatus,
)
from src.notifications import slack_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Codat webhooks
# ---------------------------------------------------------------------------


@router.post("/codat")
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

    logger.info("Codat webhook: type=%s company=%s", event_type, company_id)

    if event_type in ("invoices.dataSync.completed", "DataSyncCompleted"):
        # A data sync finished — trigger our sync job for this company
        _handle_codat_sync_complete(company_id, payload)
    elif event_type in ("invoices.dataChanged", "DataChanged"):
        _handle_codat_data_changed(company_id, payload)

    return {"received": True}


def _verify_codat_signature(body: bytes, signature: str) -> bool:
    """Verify Codat webhook HMAC signature."""
    expected = hmac.new(
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


@router.post("/stripe")
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

    event_type = event.get("type", "")
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(billing, event)
    elif event_type == "payment_intent.payment_failed":
        _handle_payment_failed(event)

    return {"received": True}


def _handle_checkout_completed(billing: StripeBilling, event: dict) -> None:
    """Process a successful fee payment from an SME."""
    result = billing.handle_checkout_completed(event)
    if not result:
        return  # Not one of our fee payments

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
