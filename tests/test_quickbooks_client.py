"""Tests for QuickBooks Online API client."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.db.models import AccountingPlatform
from src.sentry.quickbooks_client import (
    QuickBooksAPIError,
    QuickBooksClient,
    QuickBooksRateLimitError,
)


def _make_qb_invoice(
    inv_id="1",
    doc_number="INV-001",
    balance=5000.0,
    due_date="2025-01-15",
    customer_id="100",
    customer_name="Debtor Co",
    currency="GBP",
):
    """Build a raw QuickBooks invoice dict."""
    return {
        "Id": inv_id,
        "DocNumber": doc_number,
        "Balance": balance,
        "DueDate": due_date,
        "CustomerRef": {"value": customer_id, "name": customer_name},
        "CurrencyRef": {"value": currency},
    }


def _make_qb_customer(
    display_name="Debtor Co",
    email="ap@debtor.com",
    phone="020 1234 5678",
):
    """Build a raw QuickBooks customer dict."""
    return {
        "DisplayName": display_name,
        "PrimaryEmailAddr": {"Address": email},
        "PrimaryPhone": {"FreeFormNumber": phone},
    }


class TestQuickBooksClient:
    def _make_client_with_mock(self, status_code=200):
        """Create a QuickBooksClient with a mocked session.

        Returns (client, mock_session) so callers can set up responses.
        """
        client = QuickBooksClient(
            access_token="test-token",
            realm_id="test-realm",
            sandbox=True,
        )
        client.session = MagicMock()
        return client

    def _set_responses(self, client, responses):
        """Set up a sequence of mock responses on the session."""
        mock_resps = []
        for resp_json, status_code in responses:
            mock_resp = MagicMock()
            mock_resp.status_code = status_code
            mock_resp.ok = status_code < 400
            mock_resp.json.return_value = resp_json
            mock_resp.text = "error body"
            mock_resps.append(mock_resp)
        client.session.request.side_effect = mock_resps

    def test_get_overdue_invoices_success(self):
        client = self._make_client_with_mock()
        customer = _make_qb_customer()
        self._set_responses(client, [
            # First call: query for invoices
            ({"QueryResponse": {"Invoice": [_make_qb_invoice()]}}, 200),
            # Second call: customer lookup
            ({"Customer": customer}, 200),
        ])

        invoices = client.get_overdue_invoices()

        assert len(invoices) == 1
        assert invoices[0].external_id == "1"
        assert invoices[0].invoice_number == "INV-001"
        assert invoices[0].amount_due == Decimal("5000.0")
        assert invoices[0].contact_email == "ap@debtor.com"
        assert invoices[0].contact_phone == "020 1234 5678"
        assert invoices[0].platform == AccountingPlatform.QUICKBOOKS

    def test_customer_lookup_caching(self):
        """Two invoices with the same customer should only trigger one customer lookup."""
        client = self._make_client_with_mock()
        inv1 = _make_qb_invoice("1", "INV-001", customer_id="100")
        inv2 = _make_qb_invoice("2", "INV-002", customer_id="100")
        customer = _make_qb_customer()

        self._set_responses(client, [
            # Invoice query
            ({"QueryResponse": {"Invoice": [inv1, inv2]}}, 200),
            # Only one customer lookup (cached for second invoice)
            ({"Customer": customer}, 200),
        ])

        invoices = client.get_overdue_invoices()

        assert len(invoices) == 2
        # session.request called twice: once for query, once for customer
        assert client.session.request.call_count == 2

    def test_different_customers_trigger_separate_lookups(self):
        """Invoices with different customers should trigger separate lookups."""
        client = self._make_client_with_mock()
        inv1 = _make_qb_invoice("1", "INV-001", customer_id="100")
        inv2 = _make_qb_invoice("2", "INV-002", customer_id="200")

        self._set_responses(client, [
            ({"QueryResponse": {"Invoice": [inv1, inv2]}}, 200),
            ({"Customer": _make_qb_customer("Co A", "a@a.com", "111")}, 200),
            ({"Customer": _make_qb_customer("Co B", "b@b.com", "222")}, 200),
        ])

        invoices = client.get_overdue_invoices()

        assert len(invoices) == 2
        assert invoices[0].contact_email == "a@a.com"
        assert invoices[1].contact_email == "b@b.com"
        assert client.session.request.call_count == 3

    def test_customer_lookup_failure_returns_empty_contact(self):
        """If customer lookup fails, invoice should still be created with empty contact."""
        client = self._make_client_with_mock()
        inv = _make_qb_invoice()

        # Invoice query succeeds, customer lookup returns 500
        mock_resp_query = MagicMock()
        mock_resp_query.status_code = 200
        mock_resp_query.ok = True
        mock_resp_query.json.return_value = {"QueryResponse": {"Invoice": [inv]}}

        mock_resp_customer = MagicMock()
        mock_resp_customer.status_code = 500
        mock_resp_customer.ok = False
        mock_resp_customer.json.return_value = {}
        mock_resp_customer.text = "Internal Server Error"

        client.session.request.side_effect = [mock_resp_query, mock_resp_customer]

        invoices = client.get_overdue_invoices()

        assert len(invoices) == 1
        assert invoices[0].contact_email == ""
        assert invoices[0].contact_phone == ""

    def test_sandbox_url_selection(self):
        client_sandbox = QuickBooksClient("token", "realm", sandbox=True)
        assert "sandbox" in client_sandbox.base_url

    def test_production_url_selection(self):
        client_prod = QuickBooksClient("token", "realm", sandbox=False)
        assert "sandbox" not in client_prod.base_url
        assert client_prod.base_url == QuickBooksClient.PRODUCTION_URL

    def test_api_error_on_non_200(self):
        client = self._make_client_with_mock()
        self._set_responses(client, [({}, 500)])

        with pytest.raises(QuickBooksAPIError):
            client._request("GET", "/query")

    def test_rate_limit_error_on_429(self):
        client = self._make_client_with_mock()
        self._set_responses(client, [({}, 429)])

        with pytest.raises(QuickBooksRateLimitError):
            client._request("GET", "/query")

    def test_get_overdue_invoices_handles_api_error(self):
        """get_overdue_invoices returns [] on API error, not raise."""
        client = self._make_client_with_mock()
        self._set_responses(client, [({}, 500)])

        invoices = client.get_overdue_invoices()
        assert invoices == []

    def test_empty_query_response(self):
        client = self._make_client_with_mock()
        self._set_responses(client, [
            ({"QueryResponse": {}}, 200),
        ])

        invoices = client.get_overdue_invoices()
        assert invoices == []
