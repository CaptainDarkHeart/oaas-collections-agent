"""Tests for Xero API client."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.db.models import AccountingPlatform
from src.sentry.xero_client import (
    XeroAPIError,
    XeroClient,
    XeroRateLimitError,
    _parse_xero_date,
)


def _make_xero_invoice(
    invoice_id="xero-inv-1",
    number="INV-001",
    amount_due=5000.0,
    due_date_string="2025-01-15",
    due_date=None,
    contact_name="Debtor Co",
    contact_email="ap@debtor.com",
    phones=None,
    currency="GBP",
):
    """Build a raw Xero invoice dict."""
    contact = {"Name": contact_name}
    if contact_email is not None:
        contact["EmailAddress"] = contact_email
    if phones is not None:
        contact["Phones"] = phones
    inv = {
        "InvoiceID": invoice_id,
        "InvoiceNumber": number,
        "Contact": contact,
        "AmountDue": amount_due,
        "CurrencyCode": currency,
        "DueDateString": due_date_string,
    }
    if due_date is not None:
        inv["DueDate"] = due_date
    return inv


class TestXeroDateParsing:
    def test_dotnet_date_format(self):
        # /Date(1647302400000)/ = 2022-03-15 in UTC
        result = _parse_xero_date("/Date(1647302400000)/")
        assert result == date(2022, 3, 15)

    def test_dotnet_date_format_with_timezone(self):
        result = _parse_xero_date("/Date(1647302400000+0000)/")
        assert result == date(2022, 3, 15)

    def test_iso_date_string(self):
        result = _parse_xero_date("2026-03-15")
        assert result == date(2026, 3, 15)

    def test_iso_datetime_string(self):
        result = _parse_xero_date("2026-03-15T00:00:00")
        assert result == date(2026, 3, 15)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty date string"):
            _parse_xero_date("")


class TestXeroClient:
    def _make_client_with_mock(self, response_json, status_code=200):
        """Create a XeroClient with a mocked session."""
        client = XeroClient(access_token="test-token", tenant_id="test-tenant")
        client.session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.ok = status_code < 400
        mock_resp.json.return_value = response_json
        mock_resp.text = "error body"
        client.session.request.return_value = mock_resp
        return client

    def test_get_overdue_invoices_success(self):
        client = self._make_client_with_mock({
            "Invoices": [
                _make_xero_invoice("inv-1", "INV-001", 5000.0, "2025-01-15"),
                _make_xero_invoice("inv-2", "INV-002", 3000.0, "2025-02-01"),
            ]
        })

        invoices = client.get_overdue_invoices()

        assert len(invoices) == 2
        assert invoices[0].external_id == "inv-1"
        assert invoices[0].invoice_number == "INV-001"
        assert invoices[0].amount_due == Decimal("5000.0")
        assert invoices[0].platform == AccountingPlatform.XERO
        assert invoices[0].contact_email == "ap@debtor.com"
        assert invoices[1].invoice_number == "INV-002"

    def test_get_overdue_invoices_empty(self):
        client = self._make_client_with_mock({"Invoices": []})
        invoices = client.get_overdue_invoices()
        assert invoices == []

    def test_missing_contact_email_defaults_to_empty(self):
        """Invoices with no contact email should have email set to empty string."""
        inv = _make_xero_invoice()
        # Remove EmailAddress key entirely to simulate missing email
        inv["Contact"].pop("EmailAddress", None)

        client = self._make_client_with_mock({"Invoices": [inv]})
        invoices = client.get_overdue_invoices()

        assert len(invoices) == 1
        assert invoices[0].contact_email == ""

    def test_xero_api_error_on_non_200(self):
        """Non-200 responses should raise XeroAPIError (via _request)."""
        client = self._make_client_with_mock({}, status_code=500)
        with pytest.raises(XeroAPIError):
            client._request("GET", "/Invoices")

    def test_xero_rate_limit_error_on_429(self):
        """429 responses should raise XeroRateLimitError."""
        client = self._make_client_with_mock({}, status_code=429)
        with pytest.raises(XeroRateLimitError):
            client._request("GET", "/Invoices")

    def test_get_overdue_invoices_handles_rate_limit(self):
        """get_overdue_invoices should return [] on rate limit, not raise."""
        client = self._make_client_with_mock({}, status_code=429)
        invoices = client.get_overdue_invoices()
        assert invoices == []

    def test_get_overdue_invoices_handles_api_error(self):
        """get_overdue_invoices should return [] on API error, not raise."""
        client = self._make_client_with_mock({}, status_code=500)
        invoices = client.get_overdue_invoices()
        assert invoices == []

    def test_skips_unparseable_invoice(self):
        """Invoices that fail to parse should be skipped with a warning."""
        bad_invoice = {"InvoiceID": "bad-1"}  # Missing required fields
        good_invoice = _make_xero_invoice("good-1", "INV-OK", 1000.0, "2025-03-01")

        client = self._make_client_with_mock({
            "Invoices": [bad_invoice, good_invoice]
        })
        invoices = client.get_overdue_invoices()
        assert len(invoices) == 1
        assert invoices[0].invoice_number == "INV-OK"

    def test_phone_extraction(self):
        """Phone numbers should be extracted from Xero contact Phones array."""
        phones = [
            {"PhoneType": "DEFAULT", "PhoneNumber": "1234567", "PhoneAreaCode": "020", "PhoneCountryCode": "+44"},
        ]
        client = self._make_client_with_mock({
            "Invoices": [_make_xero_invoice(phones=phones)]
        })
        invoices = client.get_overdue_invoices()
        assert invoices[0].contact_phone == "+44 020 1234567"

    def test_dotnet_date_in_due_date_field(self):
        """When DueDateString is missing, DueDate with .NET format should work."""
        inv = _make_xero_invoice()
        # Remove DueDateString so _parse_invoice falls through to DueDate
        del inv["DueDateString"]
        inv["DueDate"] = "/Date(1647302400000)/"

        client = self._make_client_with_mock({"Invoices": [inv]})
        invoices = client.get_overdue_invoices()
        assert len(invoices) == 1
        assert invoices[0].due_date == date(2022, 3, 15)
