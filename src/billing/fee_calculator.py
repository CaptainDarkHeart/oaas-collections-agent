"""Fee calculation: 10% of invoice value or GBP 500 flat.

Business rules:
- For invoices over GBP 5,000 (FEE_PERCENTAGE_THRESHOLD): 10% of recovered amount
- For invoices at or below GBP 5,000, or stalled invoices 60+ days: GBP 500 flat fee
- If nothing is recovered, no fee is charged
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from src.config import settings
from src.db.models import Fee, FeeStatus, FeeType


def calculate_fee(
    invoice_amount: Decimal,
    sme_id: UUID | str,
    invoice_id: UUID | str,
) -> Fee:
    """Calculate the recovery fee for a successfully collected invoice.

    Args:
        invoice_amount: The amount that was recovered.
        sme_id: The SME client's ID.
        invoice_id: The invoice ID.

    Returns:
        A Fee object (not yet persisted) with the calculated amount.
    """
    if invoice_amount <= 0:
        raise ValueError(f"Invoice amount must be positive, got {invoice_amount}")

    threshold = Decimal(str(settings.fee_percentage_threshold))
    percentage = Decimal(str(settings.fee_percentage))
    flat_amount = Decimal(str(settings.fee_flat_amount))

    if invoice_amount > threshold:
        fee_amount = (invoice_amount * percentage / 100).quantize(Decimal("0.01"))
        fee_type = FeeType.PERCENTAGE
    else:
        fee_amount = flat_amount
        fee_type = FeeType.FLAT

    return Fee(
        invoice_id=UUID(str(invoice_id)),
        sme_id=UUID(str(sme_id)),
        fee_type=fee_type,
        fee_amount=fee_amount,
        invoice_amount_recovered=invoice_amount,
        status=FeeStatus.PENDING,
    )
