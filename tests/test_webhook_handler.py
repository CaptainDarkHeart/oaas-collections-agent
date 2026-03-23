"""Tests for Codat and Stripe webhook handlers."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.dashboard.app import app

client = TestClient(app, headers={"Authorization": "Basic dXNlcjp0ZXN0"})


class TestCodatWebhook:
    def test_codat_webhook_accepts_valid_payload(self):
        resp = client.post(
            "/webhooks/codat",
            json={
                "AlertType": "DataSyncCompleted",
                "CompanyId": "comp-123",
                "DataType": "customers",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"received": True}

    def test_codat_webhook_unknown_type(self):
        resp = client.post(
            "/webhooks/codat",
            json={
                "AlertType": "SomethingElse",
                "CompanyId": "comp-123",
            },
        )
        assert resp.status_code == 200

    @patch("src.sentry.invoice_sync.run_invoice_sync")
    def test_codat_sync_complete_triggers_sync(self, mock_sync):
        resp = client.post(
            "/webhooks/codat",
            json={
                "AlertType": "invoices.dataSync.completed",
                "CompanyId": "comp-123",
                "DataType": "invoices",
            },
        )
        assert resp.status_code == 200
        mock_sync.assert_called_once()


class TestStripeWebhook:
    @patch("src.sentry.webhook_handler.StripeBilling")
    def test_stripe_webhook_invalid_signature(self, mock_billing_cls):
        import stripe

        mock_billing = MagicMock()
        mock_billing.verify_webhook_signature.side_effect = stripe.SignatureVerificationError(
            "bad sig", "sig_header"
        )
        mock_billing_cls.return_value = mock_billing

        resp = client.post(
            "/webhooks/stripe",
            content=b'{"type": "checkout.session.completed"}',
            headers={
                "Stripe-Signature": "bad_sig",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
