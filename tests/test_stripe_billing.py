"""Tests for Stripe billing (SME fee charging)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.billing.stripe_billing import StripeBilling


class TestStripeBilling:
    def setup_method(self):
        self.billing = StripeBilling(api_key="sk_test_fake")

    def test_zero_fee_returns_error(self):
        result = self.billing.create_fee_checkout(
            sme_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            fee_amount=Decimal("0"),
        )
        assert not result.success
        assert "positive" in result.error

    @patch("src.billing.stripe_billing.stripe")
    def test_get_or_create_customer_existing(self, mock_stripe):
        mock_customer = MagicMock()
        mock_customer.id = "cus_existing"
        mock_customer.get.return_value = None  # not deleted
        mock_stripe.Customer.retrieve.return_value = mock_customer

        result = self.billing.get_or_create_customer(
            sme_id=uuid4(),
            company_name="Test Co",
            email="test@example.com",
            existing_stripe_id="cus_existing",
        )

        assert result == "cus_existing"
        mock_stripe.Customer.retrieve.assert_called_once_with("cus_existing")

    @patch("src.billing.stripe_billing.stripe")
    def test_get_or_create_customer_new(self, mock_stripe):
        mock_customer = MagicMock()
        mock_customer.id = "cus_new"
        mock_stripe.Customer.create.return_value = mock_customer

        sme_id = uuid4()
        result = self.billing.get_or_create_customer(
            sme_id=sme_id,
            company_name="New Co",
            email="new@example.com",
        )

        assert result == "cus_new"
        mock_stripe.Customer.create.assert_called_once()

    @patch("src.billing.stripe_billing.stripe")
    def test_create_fee_checkout_success(self, mock_stripe):
        mock_session = MagicMock()
        mock_session.id = "cs_123"
        mock_session.url = "https://checkout.stripe.com/session"
        mock_stripe.checkout.Session.create.return_value = mock_session

        result = self.billing.create_fee_checkout(
            sme_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-042",
            fee_amount=Decimal("750.00"),
            customer_id="cus_abc",
        )

        assert result.success
        assert result.checkout_url == "https://checkout.stripe.com/session"
        assert result.stripe_customer_id == "cus_abc"

    @patch("src.billing.stripe_billing.stripe")
    def test_create_fee_checkout_stripe_error(self, mock_stripe):
        import stripe

        mock_stripe.StripeError = stripe.StripeError
        mock_stripe.checkout.Session.create.side_effect = stripe.StripeError("declined")

        result = self.billing.create_fee_checkout(
            sme_id=uuid4(),
            invoice_id=uuid4(),
            invoice_number="INV-001",
            fee_amount=Decimal("500"),
        )

        assert not result.success
        assert "declined" in result.error

    def test_handle_checkout_completed_recovery_fee(self):
        event = {
            "data": {
                "object": {
                    "metadata": {
                        "fee_type": "recovery_fee",
                        "sme_id": str(uuid4()),
                        "invoice_id": str(uuid4()),
                        "invoice_number": "INV-042",
                    },
                    "payment_intent": "pi_123",
                    "amount_total": 75000,
                    "currency": "gbp",
                }
            }
        }

        result = self.billing.handle_checkout_completed(event)

        assert result is not None
        assert result["invoice_number"] == "INV-042"
        assert result["payment_intent_id"] == "pi_123"
        assert result["amount_total"] == 75000

    def test_handle_checkout_completed_not_our_payment(self):
        event = {
            "data": {
                "object": {
                    "metadata": {"fee_type": "something_else"},
                }
            }
        }

        result = self.billing.handle_checkout_completed(event)
        assert result is None
