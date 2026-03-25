"""Tests for write_back_payment to accounting software."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.db.models import ConnectionStatus
from src.sentry.write_back import write_back_payment


def _make_invoice(sme_id, external_id="xero-inv-123", amount="5000.00"):
    return {
        "id": str(uuid4()),
        "sme_id": str(sme_id),
        "invoice_number": "INV-001",
        "debtor_company": "Debtor Co",
        "amount": amount,
        "currency": "GBP",
        "external_id": external_id,
    }


def _make_connection(platform="xero", status="active"):
    return {
        "id": str(uuid4()),
        "sme_id": str(uuid4()),
        "platform": platform,
        "access_token": "encrypted-token",
        "refresh_token": "encrypted-refresh",
        "tenant_id": "tenant-123",
        "status": status,
    }


class TestWriteBackPayment:
    @patch("src.sentry.write_back.decrypt_token", return_value="decrypted-token")
    @patch("src.sentry.xero_client.XeroClient.create_payment", return_value=True)
    def test_xero_write_back_success(self, mock_create_payment, mock_decrypt):
        db = MagicMock()
        sme_id = uuid4()
        invoice_id = uuid4()

        db.get_invoice.return_value = _make_invoice(sme_id, external_id="xero-inv-1")
        db.list_connections.return_value = [
            _make_connection(platform="xero", status=ConnectionStatus.ACTIVE.value)
        ]

        result = write_back_payment(db, invoice_id)

        assert result is True
        mock_create_payment.assert_called_once()
        call_args = mock_create_payment.call_args
        assert call_args[0][0] == "xero-inv-1"
        assert call_args[0][1] == Decimal("5000.00")
        assert isinstance(call_args[0][2], date)

    @patch("src.sentry.write_back.decrypt_token", return_value="decrypted-token")
    @patch("src.sentry.quickbooks_client.QuickBooksClient.create_payment", return_value=True)
    def test_quickbooks_write_back_success(self, mock_create_payment, mock_decrypt):
        db = MagicMock()
        sme_id = uuid4()
        invoice_id = uuid4()

        db.get_invoice.return_value = _make_invoice(sme_id, external_id="qb-inv-1")
        db.list_connections.return_value = [
            _make_connection(
                platform="quickbooks", status=ConnectionStatus.ACTIVE.value
            )
        ]

        result = write_back_payment(db, invoice_id)

        assert result is True
        mock_create_payment.assert_called_once()
        call_args = mock_create_payment.call_args
        assert call_args[0][0] == "qb-inv-1"
        assert call_args[0][1] == Decimal("5000.00")

    def test_missing_invoice_returns_false(self):
        db = MagicMock()
        db.get_invoice.return_value = None

        result = write_back_payment(db, uuid4())

        assert result is False

    def test_no_external_id_returns_false(self):
        db = MagicMock()
        sme_id = uuid4()
        db.get_invoice.return_value = _make_invoice(sme_id, external_id=None)

        result = write_back_payment(db, uuid4())

        assert result is False
        db.list_connections.assert_not_called()

    def test_no_active_connection_returns_false(self):
        db = MagicMock()
        sme_id = uuid4()
        db.get_invoice.return_value = _make_invoice(sme_id)
        db.list_connections.return_value = [
            _make_connection(status=ConnectionStatus.EXPIRED.value)
        ]

        result = write_back_payment(db, uuid4())

        assert result is False

    def test_no_connections_returns_false(self):
        db = MagicMock()
        sme_id = uuid4()
        db.get_invoice.return_value = _make_invoice(sme_id)
        db.list_connections.return_value = []

        result = write_back_payment(db, uuid4())

        assert result is False

    @patch("src.sentry.write_back.decrypt_token", return_value="decrypted-token")
    @patch("src.sentry.xero_client.XeroClient.create_payment", return_value=False)
    def test_api_failure_returns_false(self, mock_create_payment, mock_decrypt):
        db = MagicMock()
        sme_id = uuid4()
        invoice_id = uuid4()

        db.get_invoice.return_value = _make_invoice(sme_id)
        db.list_connections.return_value = [
            _make_connection(platform="xero", status=ConnectionStatus.ACTIVE.value)
        ]

        result = write_back_payment(db, invoice_id)

        assert result is False

    def test_unexpected_exception_returns_false(self):
        """write_back_payment should never crash the caller."""
        db = MagicMock()
        db.get_invoice.side_effect = RuntimeError("DB connection lost")

        result = write_back_payment(db, uuid4())

        assert result is False

    def test_unsupported_platform_returns_false(self):
        db = MagicMock()
        sme_id = uuid4()
        db.get_invoice.return_value = _make_invoice(sme_id)
        db.list_connections.return_value = [
            _make_connection(platform="csv", status=ConnectionStatus.ACTIVE.value)
        ]

        result = write_back_payment(db, uuid4())

        assert result is False
