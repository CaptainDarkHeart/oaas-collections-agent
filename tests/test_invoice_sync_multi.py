"""Tests for multi-provider invoice sync (Xero, QuickBooks via direct OAuth)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from src.db.models import AccountingPlatform, ContactSource
from src.sentry.invoice_sync import (
    run_full_sync,
    sync_from_connection,
    upsert_normalised_invoices,
)
from src.sentry.normalised_invoice import NormalisedInvoice

_TEST_FERNET_KEY = Fernet.generate_key().decode()


def _make_normalised_invoice(
    number="INV-001",
    amount=Decimal("5000"),
    due="2025-01-15",
    platform=AccountingPlatform.XERO,
    email="ap@debtor.com",
    external_id=None,
):
    return NormalisedInvoice(
        external_id=external_id or f"ext-{number}",
        invoice_number=number,
        debtor_company="Debtor Co",
        contact_name="Jane Smith",
        contact_email=email,
        contact_phone="020 1234 5678",
        amount_due=amount,
        currency="GBP",
        due_date=date.fromisoformat(due),
        platform=platform,
    )


def _make_connection(
    platform="xero",
    expired=False,
    access_token="enc-access",
    refresh_token="enc-refresh",
    tenant_id="tenant-123",
    status="active",
):
    if expired:
        expires_at = datetime.now(tz=UTC).replace(tzinfo=None) - timedelta(hours=1)
    else:
        expires_at = datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(hours=1)

    return {
        "id": str(uuid4()),
        "sme_id": str(uuid4()),
        "platform": platform,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": expires_at,
        "tenant_id": tenant_id,
        "status": status,
    }


def _make_sme(sme_id=None):
    return {
        "id": str(sme_id or uuid4()),
        "company_name": "Test SME",
        "contact_email": "sme@example.com",
        "codat_company_id": None,
        "accounting_platform": "csv",
        "status": "active",
    }


class TestUpsertNormalisedInvoices:
    def test_creates_new_invoices(self):
        db = MagicMock()
        db.list_active_invoices.return_value = []
        sme_id = uuid4()

        invoices = [
            _make_normalised_invoice("INV-001"),
            _make_normalised_invoice("INV-002"),
        ]

        count = upsert_normalised_invoices(db, sme_id, invoices)

        assert count == 2
        assert db.create_invoice.call_count == 2
        assert db.create_contact.call_count == 2

    def test_skips_duplicate_invoice_numbers(self):
        db = MagicMock()
        db.list_active_invoices.return_value = [
            {"invoice_number": "INV-001", "id": str(uuid4())},
        ]
        sme_id = uuid4()

        invoices = [
            _make_normalised_invoice("INV-001"),  # duplicate
            _make_normalised_invoice("INV-NEW"),   # new
        ]

        count = upsert_normalised_invoices(db, sme_id, invoices)

        assert count == 1
        assert db.create_invoice.call_count == 1

    def test_skips_invoice_without_number(self):
        db = MagicMock()
        db.list_active_invoices.return_value = []
        sme_id = uuid4()

        invoices = [_make_normalised_invoice("")]

        count = upsert_normalised_invoices(db, sme_id, invoices)

        assert count == 0
        db.create_invoice.assert_not_called()

    def test_skips_contact_when_no_email(self):
        db = MagicMock()
        db.list_active_invoices.return_value = []
        sme_id = uuid4()

        invoices = [_make_normalised_invoice("INV-001", email="")]

        count = upsert_normalised_invoices(db, sme_id, invoices)

        assert count == 1
        db.create_invoice.call_count == 1
        db.create_contact.assert_not_called()

    def test_deduplicates_within_batch(self):
        """Two invoices with the same number in one batch should only create one."""
        db = MagicMock()
        db.list_active_invoices.return_value = []
        sme_id = uuid4()

        invoices = [
            _make_normalised_invoice("INV-DUP"),
            _make_normalised_invoice("INV-DUP"),
        ]

        count = upsert_normalised_invoices(db, sme_id, invoices)

        assert count == 1

    def test_contact_source_matches_platform(self):
        db = MagicMock()
        db.list_active_invoices.return_value = []
        sme_id = uuid4()

        invoices = [_make_normalised_invoice("INV-X", platform=AccountingPlatform.XERO)]
        upsert_normalised_invoices(db, sme_id, invoices)

        contact_call = db.create_contact.call_args
        created_contact = contact_call.args[0]
        assert created_contact.source == ContactSource.XERO_SYNC


class TestSyncFromConnection:
    @patch("src.sentry.invoice_sync.XeroClient")
    @patch("src.sentry.invoice_sync.decrypt_token")
    def test_xero_sync_with_valid_token(self, mock_decrypt, mock_xero_cls):
        mock_decrypt.return_value = "decrypted-access"
        mock_client = MagicMock()
        mock_client.get_overdue_invoices.return_value = [
            _make_normalised_invoice("INV-001"),
        ]
        mock_xero_cls.return_value = mock_client

        db = MagicMock()
        sme_id = uuid4()
        conn = _make_connection(platform="xero", expired=False)

        invoices = sync_from_connection(db, sme_id, conn)

        assert len(invoices) == 1
        mock_xero_cls.assert_called_once_with(
            access_token="decrypted-access", tenant_id="tenant-123"
        )

    @patch("src.sentry.invoice_sync.settings")
    @patch("src.sentry.invoice_sync.QuickBooksClient")
    @patch("src.sentry.invoice_sync.decrypt_token")
    def test_quickbooks_sync(self, mock_decrypt, mock_qb_cls, mock_settings):
        mock_settings.quickbooks_sandbox = True
        mock_decrypt.return_value = "decrypted-access"
        mock_client = MagicMock()
        mock_client.get_overdue_invoices.return_value = []
        mock_qb_cls.return_value = mock_client

        db = MagicMock()
        sme_id = uuid4()
        conn = _make_connection(platform="quickbooks", expired=False)

        invoices = sync_from_connection(db, sme_id, conn)

        assert invoices == []
        mock_qb_cls.assert_called_once()

    @patch("src.sentry.invoice_sync.XeroClient")
    @patch("src.sentry.invoice_sync.refresh_access_token")
    @patch("src.sentry.invoice_sync.encrypt_token")
    @patch("src.sentry.invoice_sync.decrypt_token")
    def test_expired_token_triggers_refresh(
        self, mock_decrypt, mock_encrypt, mock_refresh, mock_xero_cls
    ):
        mock_decrypt.return_value = "decrypted-refresh"
        mock_refresh.return_value = {
            "access_token": "fresh-access",
            "refresh_token": "fresh-refresh",
            "expires_in": 1800,
        }
        mock_encrypt.side_effect = lambda t: f"enc-{t}"

        mock_client = MagicMock()
        mock_client.get_overdue_invoices.return_value = []
        mock_xero_cls.return_value = mock_client

        db = MagicMock()
        sme_id = uuid4()
        conn = _make_connection(platform="xero", expired=True)

        sync_from_connection(db, sme_id, conn)

        # Verify refresh was called
        mock_refresh.assert_called_once_with(AccountingPlatform.XERO, "decrypted-refresh")

        # Verify tokens were updated in DB
        db.update_connection.assert_any_call(
            db.update_connection.call_args_list[0].args[0],
            access_token="enc-fresh-access",
            refresh_token="enc-fresh-refresh",
            token_expires_at=db.update_connection.call_args_list[0].kwargs["token_expires_at"],
        )

        # Verify the XeroClient was created with the fresh token
        mock_xero_cls.assert_called_once_with(
            access_token="fresh-access", tenant_id="tenant-123"
        )

    @patch("src.sentry.invoice_sync.decrypt_token")
    def test_unsupported_platform_raises(self, mock_decrypt):
        mock_decrypt.return_value = "decrypted-access"
        db = MagicMock()
        sme_id = uuid4()
        conn = _make_connection(platform="csv", expired=False)

        with pytest.raises(ValueError, match="Direct sync not supported"):
            sync_from_connection(db, sme_id, conn)


class TestRunFullSync:
    @patch("src.sentry.invoice_sync.slack_webhook")
    @patch("src.sentry.invoice_sync.upsert_normalised_invoices")
    @patch("src.sentry.invoice_sync.sync_from_connection")
    @patch("src.sentry.invoice_sync.run_invoice_sync")
    def test_processes_multiple_connections(
        self, mock_codat_sync, mock_sync_conn, mock_upsert, mock_slack
    ):
        mock_codat_sync.return_value = MagicMock(
            success=True, companies_synced=0, invoices_found=0,
            overdue_invoices=0, errors=[],
        )

        sme_id = uuid4()
        sme = _make_sme(sme_id=sme_id)

        conn1 = _make_connection(platform="xero", status="active")
        conn2 = _make_connection(platform="quickbooks", status="active")

        db = MagicMock()
        db.list_active_smes.return_value = [sme]
        db.list_connections.return_value = [conn1, conn2]

        mock_sync_conn.return_value = [_make_normalised_invoice("INV-001")]
        mock_upsert.return_value = 1

        summary = run_full_sync(db=db)

        assert summary["smes_processed"] == 1
        assert summary["connections_synced"] == 2
        assert mock_sync_conn.call_count == 2
        assert mock_upsert.call_count == 2

    @patch("src.sentry.invoice_sync.slack_webhook")
    @patch("src.sentry.invoice_sync.sync_from_connection")
    @patch("src.sentry.invoice_sync.run_invoice_sync")
    def test_connection_error_does_not_block_others(
        self, mock_codat_sync, mock_sync_conn, mock_slack
    ):
        mock_codat_sync.return_value = MagicMock(
            success=True, companies_synced=0, invoices_found=0,
            overdue_invoices=0, errors=[],
        )

        sme = _make_sme()
        conn1 = _make_connection(platform="xero", status="active")
        conn2 = _make_connection(platform="quickbooks", status="active")

        db = MagicMock()
        db.list_active_smes.return_value = [sme]
        db.list_connections.return_value = [conn1, conn2]

        # First connection fails, second succeeds
        mock_sync_conn.side_effect = [
            Exception("Xero API down"),
            [_make_normalised_invoice("INV-QB")],
        ]

        with patch("src.sentry.invoice_sync.upsert_normalised_invoices", return_value=1):
            summary = run_full_sync(db=db)

        assert summary["connections_synced"] == 1
        assert len(summary["errors"]) == 1
        assert "Xero API down" in summary["errors"][0]

    @patch("src.sentry.invoice_sync.slack_webhook")
    @patch("src.sentry.invoice_sync.run_invoice_sync")
    def test_skips_inactive_connections(self, mock_codat_sync, mock_slack):
        mock_codat_sync.return_value = MagicMock(
            success=True, companies_synced=0, invoices_found=0,
            overdue_invoices=0, errors=[],
        )

        sme = _make_sme()
        conn_expired = _make_connection(platform="xero", status="expired")

        db = MagicMock()
        db.list_active_smes.return_value = [sme]
        db.list_connections.return_value = [conn_expired]

        summary = run_full_sync(db=db)

        # Expired connection should not be synced
        assert summary["connections_synced"] == 0
