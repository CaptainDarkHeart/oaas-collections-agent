"""Daily sync job for pulling overdue invoices from connected accounting platforms.

Orchestrates the Sentry brain's main job:
1. For each active SME with a Codat connection, pull overdue invoices
2. Upsert new invoices into the database
3. Check if any previously-active invoices have been marked as paid externally
4. Report sync results via Slack/email notifications
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.config import settings
from src.db.models import (
    AccountingPlatform,
    Contact,
    ContactSource,
    Database,
    Invoice,
    InvoicePhase,
    InvoiceStatus,
)
from src.notifications import slack_webhook
from src.sentry.codat_client import CodatClient, CodatInvoice, CodatSyncResult

logger = logging.getLogger(__name__)


def run_invoice_sync(
    db: Database | None = None,
    codat: CodatClient | None = None,
) -> CodatSyncResult:
    """Pull overdue invoices from all connected accounting platforms.

    Returns:
        CodatSyncResult with counts and any errors.
    """
    db = db or Database()
    codat = codat or CodatClient()

    result = CodatSyncResult(success=True)

    for sme in db.list_active_smes():
        if not sme.get("codat_company_id"):
            continue  # CSV-only SME, skip

        if AccountingPlatform(sme.get("accounting_platform", "csv")) == AccountingPlatform.CSV:
            continue

        sme_id = UUID(sme["id"])
        company_id = sme["codat_company_id"]
        sme_name = sme["company_name"]

        logger.info("Syncing invoices for %s (Codat: %s)", sme_name, company_id)

        try:
            _sync_sme_invoices(db, codat, sme_id, company_id, sme_name, result)
            result.companies_synced += 1
        except Exception as e:
            error_msg = f"Failed to sync {sme_name}: {e}"
            logger.exception(error_msg)
            result.errors.append(error_msg)

    if result.errors:
        result.success = len(result.errors) < result.companies_synced

    logger.info(
        "Invoice sync complete: %d companies, %d invoices found, %d overdue",
        result.companies_synced,
        result.invoices_found,
        result.overdue_invoices,
    )

    return result


def _sync_sme_invoices(
    db: Database,
    codat: CodatClient,
    sme_id: UUID,
    company_id: str,
    sme_name: str,
    result: CodatSyncResult,
) -> None:
    """Sync invoices for a single SME."""
    overdue = codat.get_overdue_invoices(company_id)
    result.invoices_found += len(overdue)
    result.overdue_invoices += len(overdue)

    # Get existing invoices for this SME to avoid duplicates
    existing = db.list_active_invoices(sme_id=sme_id)
    existing_numbers = {inv["invoice_number"] for inv in existing}

    new_count = 0
    for codat_inv in overdue:
        if codat_inv.invoice_number in existing_numbers:
            continue  # Already tracking this invoice

        if not codat_inv.invoice_number:
            logger.warning("Skipping invoice with no number from %s", sme_name)
            continue

        _create_invoice_from_codat(db, sme_id, codat_inv)
        new_count += 1

    if new_count > 0:
        logger.info("Created %d new invoices for %s", new_count, sme_name)
        slack_webhook.send_alert(
            title="New Overdue Invoices Synced",
            message=f"Synced {new_count} new overdue invoice(s) for {sme_name}",
            severity="info",
        )

    # Check for invoices paid externally
    _check_paid_externally(db, codat, sme_id, company_id, existing)


def _create_invoice_from_codat(
    db: Database,
    sme_id: UUID,
    codat_inv: CodatInvoice,
) -> None:
    """Create an Invoice and Contact from a Codat invoice."""
    invoice = Invoice(
        sme_id=sme_id,
        invoice_number=codat_inv.invoice_number,
        debtor_company=codat_inv.customer_name,
        amount=Decimal(str(codat_inv.amount_due)),
        currency=codat_inv.currency,
        due_date=date.fromisoformat(codat_inv.due_date[:10]),
    )
    db.create_invoice(invoice)

    # Create a contact if we have enough info
    contact_name = codat_inv.contact_name or codat_inv.customer_name
    contact_email = codat_inv.customer_email

    if contact_name and contact_email:
        contact = Contact(
            invoice_id=invoice.id,
            name=contact_name,
            email=contact_email,
            source=ContactSource.CODAT_SYNC,
        )
        db.create_contact(contact)
    else:
        logger.warning(
            "Invoice %s has incomplete contact info (name=%r, email=%r) — "
            "will need manual contact entry",
            codat_inv.invoice_number,
            contact_name,
            contact_email,
        )


def _check_paid_externally(
    db: Database,
    codat: CodatClient,
    sme_id: UUID,
    company_id: str,
    existing_invoices: list[dict],
) -> None:
    """Check if any active invoices have been paid in the accounting software."""
    if not existing_invoices:
        return

    # Pull all invoices (not just overdue) to check paid status
    all_codat = codat.get_invoices(company_id)
    paid_numbers = {
        inv.invoice_number
        for inv in all_codat
        if inv.status == "Paid" or inv.paid_on_date
    }

    for inv in existing_invoices:
        if inv["invoice_number"] in paid_numbers:
            logger.info(
                "Invoice %s marked as paid externally — resolving",
                inv["invoice_number"],
            )
            db.update_invoice(
                UUID(inv["id"]),
                {
                    "status": InvoiceStatus.PAID,
                    "current_phase": InvoicePhase.RESOLVED,
                },
            )
            slack_webhook.send_alert(
                title="Invoice Paid Externally",
                message=(
                    f"Invoice {inv['invoice_number']} ({inv['debtor_company']}) "
                    f"was paid in the accounting software — resolved"
                ),
                invoice_number=inv["invoice_number"],
                debtor_company=inv["debtor_company"],
                severity="info",
            )
