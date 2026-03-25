"""Write-back payment to connected accounting software (Xero/QuickBooks).

When an invoice is marked as paid, this module records the payment in the
SME's connected accounting platform so their books stay in sync.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.config import settings
from src.db.models import AccountingPlatform, ConnectionStatus, Database
from src.sentry.oauth import decrypt_token

logger = logging.getLogger(__name__)


def write_back_payment(db: Database, invoice_id: UUID) -> bool:
    """Write payment back to the connected accounting platform.

    Looks up the invoice, finds the SME's active accounting connection,
    and calls the appropriate platform client to record the payment.

    Args:
        db: Database instance.
        invoice_id: The invoice that was paid.

    Returns:
        True if the write-back succeeded, False otherwise.
        Never raises — errors are logged and swallowed to protect the caller.
    """
    try:
        invoice = db.get_invoice(invoice_id)
        if not invoice:
            logger.warning("Write-back: invoice %s not found", invoice_id)
            return False

        external_id = invoice.get("external_id")
        if not external_id:
            logger.info(
                "Write-back: invoice %s has no external_id — skipping",
                invoice.get("invoice_number", invoice_id),
            )
            return False

        sme_id = UUID(invoice["sme_id"])
        amount = Decimal(str(invoice["amount"]))

        # Find an active accounting connection for this SME
        connections = db.list_connections(sme_id)
        active_conn = next(
            (
                c
                for c in connections
                if c.get("status") == ConnectionStatus.ACTIVE.value
            ),
            None,
        )

        if not active_conn:
            logger.info(
                "Write-back: no active accounting connection for SME %s — skipping",
                sme_id,
            )
            return False

        platform = AccountingPlatform(active_conn["platform"])
        access_token = decrypt_token(active_conn["access_token"])
        payment_date = date.today()

        if platform == AccountingPlatform.XERO:
            from src.sentry.xero_client import XeroClient

            tenant_id = active_conn.get("tenant_id", "")
            client = XeroClient(access_token=access_token, tenant_id=tenant_id)
            success = client.create_payment(external_id, amount, payment_date)

        elif platform == AccountingPlatform.QUICKBOOKS:
            from src.sentry.quickbooks_client import QuickBooksClient

            realm_id = active_conn.get("tenant_id", "")
            client = QuickBooksClient(
                access_token=access_token,
                realm_id=realm_id,
                sandbox=settings.quickbooks_sandbox,
            )
            success = client.create_payment(external_id, amount, payment_date)

        else:
            logger.info(
                "Write-back: platform %s does not support payment write-back",
                platform.value,
            )
            return False

        if success:
            logger.info(
                "Write-back: recorded payment for invoice %s in %s",
                invoice.get("invoice_number", invoice_id),
                platform.value,
            )
        else:
            logger.warning(
                "Write-back: failed to record payment for invoice %s in %s",
                invoice.get("invoice_number", invoice_id),
                platform.value,
            )

        return success

    except Exception:
        logger.exception(
            "Write-back: unexpected error for invoice %s", invoice_id
        )
        return False
