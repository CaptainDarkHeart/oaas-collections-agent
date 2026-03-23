"""Tests for Stripe payment link generator."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.executor.payment_link import PaymentLinkResult, StripePaymentLinks


class TestStripePaymentLinks:
    def setup_method(self):
        self.client = StripePaymentLinks(api_key="sk_test_fake")

    def test_zero_amount_returns_error(self):
        result = self.client.create_invoice_payment_link(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            debtor_company="Acme Ltd",
            amount=Decimal("0"),
        )
        assert not result.success
        assert "positive" in result.error

    def test_negative_amount_returns_error(self):
        result = self.client.create_invoice_payment_link(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            debtor_company="Acme Ltd",
            amount=Decimal("-100"),
        )
        assert not result.success

    @patch("src.executor.payment_link.stripe")
    def test_successful_link_creation(self, mock_stripe):
        mock_price = MagicMock()
        mock_price.id = "price_123"
        mock_stripe.Price.create.return_value = mock_price

        mock_link = MagicMock()
        mock_link.url = "https://pay.stripe.com/test_link"
        mock_link.id = "plink_123"
        mock_stripe.PaymentLink.create.return_value = mock_link

        invoice_id = uuid4()
        sme_id = uuid4()

        result = self.client.create_invoice_payment_link(
            invoice_id=invoice_id,
            invoice_number="INV-042",
            debtor_company="Widget Corp",
            amount=Decimal("7500.00"),
            currency="GBP",
            sme_id=sme_id,
        )

        assert result.success
        assert result.url == "https://pay.stripe.com/test_link"
        assert result.payment_link_id == "plink_123"

        # Verify price was created with correct amount (pence)
        mock_stripe.Price.create.assert_called_once()
        price_call = mock_stripe.Price.create.call_args
        assert price_call.kwargs["unit_amount"] == 750000
        assert price_call.kwargs["currency"] == "gbp"

    @patch("src.executor.payment_link.stripe")
    def test_stripe_error_returns_failure(self, mock_stripe):
        import stripe

        mock_stripe.StripeError = stripe.StripeError
        mock_stripe.Price.create.side_effect = stripe.StripeError("API error")

        result = self.client.create_invoice_payment_link(
            invoice_id=uuid4(),
            invoice_number="INV-001",
            debtor_company="Acme Ltd",
            amount=Decimal("1000"),
        )

        assert not result.success
        assert "API error" in result.error

    @patch("src.executor.payment_link.stripe")
    def test_usd_currency(self, mock_stripe):
        mock_price = MagicMock()
        mock_price.id = "price_456"
        mock_stripe.Price.create.return_value = mock_price

        mock_link = MagicMock()
        mock_link.url = "https://pay.stripe.com/usd_link"
        mock_link.id = "plink_456"
        mock_stripe.PaymentLink.create.return_value = mock_link

        result = self.client.create_invoice_payment_link(
            invoice_id=uuid4(),
            invoice_number="INV-100",
            debtor_company="US Corp",
            amount=Decimal("500.50"),
            currency="USD",
        )

        assert result.success
        price_call = mock_stripe.Price.create.call_args
        assert price_call.kwargs["currency"] == "usd"
        assert price_call.kwargs["unit_amount"] == 50050
