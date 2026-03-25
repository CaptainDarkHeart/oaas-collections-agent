"""Stripe payment link generator for debtor payments.

Creates one-time Stripe Payment Links that can be included in collection emails,
allowing debtors to pay invoices directly. Each link is tied to a specific invoice
and includes metadata for reconciliation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import stripe

from src.config import settings
from src.utils.retry import with_retry

logger = logging.getLogger(__name__)

# Stripe amounts are in the smallest currency unit (pence for GBP)
CURRENCY_MULTIPLIERS = {
    "GBP": 100,
    "USD": 100,
    "EUR": 100,
}


@dataclass
class PaymentLinkResult:
    """Result of creating a Stripe payment link."""

    success: bool
    url: str | None = None
    payment_link_id: str | None = None
    error: str | None = None


class StripePaymentLinks:
    """Creates Stripe Payment Links for debtor invoice payments."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.stripe_secret_key
        stripe.api_key = self.api_key

    @with_retry(
        max_attempts=3,
        backoff_factor=1.0,
        retryable_exceptions=(stripe.APIConnectionError, stripe.RateLimitError),
    )
    def create_invoice_payment_link(
        self,
        invoice_id: UUID,
        invoice_number: str,
        debtor_company: str,
        amount: Decimal,
        currency: str = "GBP",
        sme_id: UUID | None = None,
    ) -> PaymentLinkResult:
        """Create a one-time payment link for a specific invoice.

        Args:
            invoice_id: Internal invoice ID for reconciliation.
            invoice_number: Human-readable invoice number (shown to debtor).
            debtor_company: Debtor company name (shown on checkout).
            amount: Invoice amount to collect.
            currency: Three-letter currency code.
            sme_id: The SME client ID (for metadata).

        Returns:
            PaymentLinkResult with the payment URL or error.
        """
        multiplier = CURRENCY_MULTIPLIERS.get(currency.upper(), 100)
        amount_minor = int(amount * multiplier)

        if amount_minor <= 0:
            return PaymentLinkResult(success=False, error="Amount must be positive")

        try:
            # Create a one-time price for this specific invoice
            price = stripe.Price.create(
                unit_amount=amount_minor,
                currency=currency.lower(),
                product_data={
                    "name": f"Invoice {invoice_number}",
                    "metadata": {
                        "invoice_id": str(invoice_id),
                        "debtor_company": debtor_company,
                    },
                },
            )

            # Create the payment link
            metadata = {
                "invoice_id": str(invoice_id),
                "invoice_number": invoice_number,
                "debtor_company": debtor_company,
                "payment_type": "debtor_payment",
            }
            if sme_id:
                metadata["sme_id"] = str(sme_id)

            payment_link = stripe.PaymentLink.create(
                line_items=[{"price": price.id, "quantity": 1}],
                metadata=metadata,
                after_completion={
                    "type": "hosted_confirmation",
                    "hosted_confirmation": {
                        "custom_message": (
                            f"Thank you for settling invoice {invoice_number}. "
                            "A confirmation will be sent to your email."
                        ),
                    },
                },
            )

            logger.info(
                "Created payment link for invoice %s: %s",
                invoice_number,
                payment_link.url,
            )

            return PaymentLinkResult(
                success=True,
                url=payment_link.url,
                payment_link_id=payment_link.id,
            )

        except stripe.StripeError as e:
            logger.error("Stripe error creating payment link for %s: %s", invoice_number, e)
            return PaymentLinkResult(success=False, error=str(e))
