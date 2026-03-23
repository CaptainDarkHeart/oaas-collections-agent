"""Tests for the Codat invoice sync job."""

from decimal import Decimal
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

from src.db.models import AccountingPlatform, InvoicePhase, InvoiceStatus
from src.sentry.codat_client import CodatInvoice
from src.sentry.invoice_sync import run_invoice_sync


def _make_sme(codat_id=None, platform="xero"):
    return {
        "id": str(uuid4()),
        "company_name": "Test SME",
        "contact_email": "sme@example.com",
        "codat_company_id": codat_id,
        "accounting_platform": platform,
        "status": "active",
    }


def _make_codat_invoice(number="INV-001", amount=5000.0, due="2025-01-15"):
    return CodatInvoice(
        codat_invoice_id=f"codat-{number}",
        invoice_number=number,
        customer_name="Debtor Co",
        customer_email="ap@debtor.com",
        contact_name="Jane Smith",
        amount_due=amount,
        total_amount=amount,
        currency="GBP",
        issue_date="2025-01-01",
        due_date=due,
        status="Submitted",
    )


class TestInvoiceSync:
    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_skips_csv_only_smes(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        db.list_active_smes.return_value = [_make_sme(codat_id=None, platform="csv")]

        result = run_invoice_sync(db=db, codat=codat)

        assert result.success
        assert result.companies_synced == 0
        codat.get_overdue_invoices.assert_not_called()

    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_syncs_new_overdue_invoices(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        sme = _make_sme(codat_id="codat-comp-1", platform="xero")
        db.list_active_smes.return_value = [sme]
        db.list_active_invoices.return_value = []  # no existing invoices

        codat.get_overdue_invoices.return_value = [
            _make_codat_invoice("INV-001", 5000),
            _make_codat_invoice("INV-002", 3000),
        ]
        codat.get_invoices.return_value = []  # no paid externally

        result = run_invoice_sync(db=db, codat=codat)

        assert result.success
        assert result.companies_synced == 1
        assert result.overdue_invoices == 2
        assert db.create_invoice.call_count == 2
        assert db.create_contact.call_count == 2

    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_skips_duplicate_invoices(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        sme = _make_sme(codat_id="codat-comp-1", platform="xero")
        db.list_active_smes.return_value = [sme]
        db.list_active_invoices.return_value = [
            {"id": str(uuid4()), "invoice_number": "INV-001", "debtor_company": "Debtor Co"},
        ]

        codat.get_overdue_invoices.return_value = [
            _make_codat_invoice("INV-001", 5000),  # already exists
            _make_codat_invoice("INV-NEW", 2000),  # new
        ]
        codat.get_invoices.return_value = []

        result = run_invoice_sync(db=db, codat=codat)

        assert db.create_invoice.call_count == 1  # only the new one

    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_detects_paid_externally(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        sme = _make_sme(codat_id="codat-comp-1", platform="xero")
        db.list_active_smes.return_value = [sme]

        existing_id = str(uuid4())
        db.list_active_invoices.return_value = [
            {"id": existing_id, "invoice_number": "INV-001", "debtor_company": "Debtor Co"},
        ]

        codat.get_overdue_invoices.return_value = []

        # Codat shows INV-001 as Paid
        paid_inv = _make_codat_invoice("INV-001", 5000)
        paid_inv.status = "Paid"
        paid_inv.paid_on_date = "2026-03-20"
        codat.get_invoices.return_value = [paid_inv]

        result = run_invoice_sync(db=db, codat=codat)

        db.update_invoice.assert_called_once()
        update_call = db.update_invoice.call_args
        assert update_call.args[1]["status"] == InvoiceStatus.PAID
        assert update_call.args[1]["current_phase"] == InvoicePhase.RESOLVED

    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_handles_sync_error_gracefully(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        sme = _make_sme(codat_id="codat-comp-1", platform="xero")
        db.list_active_smes.return_value = [sme]
        codat.get_overdue_invoices.side_effect = Exception("API timeout")

        result = run_invoice_sync(db=db, codat=codat)

        assert len(result.errors) == 1
        assert "API timeout" in result.errors[0]

    @patch("src.sentry.invoice_sync.slack_webhook")
    def test_skips_invoice_without_number(self, mock_slack):
        db = MagicMock()
        codat = MagicMock()

        sme = _make_sme(codat_id="codat-comp-1", platform="xero")
        db.list_active_smes.return_value = [sme]
        db.list_active_invoices.return_value = []

        inv_no_number = _make_codat_invoice("", 1000)
        codat.get_overdue_invoices.return_value = [inv_no_number]
        codat.get_invoices.return_value = []

        result = run_invoice_sync(db=db, codat=codat)

        db.create_invoice.assert_not_called()
