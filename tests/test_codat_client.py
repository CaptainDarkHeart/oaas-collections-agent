"""Tests for Codat API client."""

from unittest.mock import MagicMock, patch

from src.sentry.codat_client import CodatClient, CodatCompany, CodatInvoice


class TestCodatClient:
    def setup_method(self):
        self.client = CodatClient(api_key="test-key")

    @patch.object(CodatClient, "__init__", lambda self, **kw: None)
    def _make_client_with_mock_session(self, response_json, status_code=200):
        client = CodatClient()
        client.api_key = "test-key"
        client.session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status.return_value = None
        client.session.get.return_value = mock_resp
        client.session.post.return_value = mock_resp
        return client

    def test_list_companies(self):
        client = self._make_client_with_mock_session({
            "results": [
                {"id": "comp-1", "name": "Acme Ltd", "platform": "Xero", "status": "Linked"},
                {"id": "comp-2", "name": "Widget Co", "platform": "QuickBooks", "status": "Linked"},
            ]
        })

        companies = client.list_companies()
        assert len(companies) == 2
        assert companies[0].codat_company_id == "comp-1"
        assert companies[0].name == "Acme Ltd"
        assert companies[1].platform == "QuickBooks"

    def test_list_companies_empty(self):
        client = self._make_client_with_mock_session({"results": []})
        assert client.list_companies() == []

    def test_get_invoices(self):
        client = self._make_client_with_mock_session({
            "results": [
                {
                    "id": "inv-1",
                    "invoiceNumber": "INV-001",
                    "customerRef": {"companyName": "Debtor Co", "email": "ap@debtor.com"},
                    "amountDue": 5000.00,
                    "totalAmount": 5000.00,
                    "currency": "GBP",
                    "issueDate": "2026-01-01",
                    "dueDate": "2026-01-31",
                    "status": "Submitted",
                },
            ]
        })

        invoices = client.get_invoices("comp-1")
        assert len(invoices) == 1
        assert invoices[0].invoice_number == "INV-001"
        assert invoices[0].customer_name == "Debtor Co"
        assert invoices[0].customer_email == "ap@debtor.com"
        assert invoices[0].amount_due == 5000.00
        assert invoices[0].due_date == "2026-01-31"

    def test_get_overdue_invoices_filters_correctly(self):
        client = self._make_client_with_mock_session({
            "results": [
                {
                    "id": "inv-1",
                    "invoiceNumber": "INV-001",
                    "customerRef": {"companyName": "Debtor Co"},
                    "amountDue": 5000.00,
                    "totalAmount": 5000.00,
                    "currency": "GBP",
                    "dueDate": "2025-01-01",  # overdue
                    "status": "Submitted",
                },
                {
                    "id": "inv-2",
                    "invoiceNumber": "INV-002",
                    "customerRef": {"companyName": "Paid Co"},
                    "amountDue": 0,
                    "totalAmount": 3000.00,
                    "currency": "GBP",
                    "dueDate": "2025-01-01",
                    "status": "Paid",
                },
                {
                    "id": "inv-3",
                    "invoiceNumber": "INV-003",
                    "customerRef": {"companyName": "Future Co"},
                    "amountDue": 2000.00,
                    "totalAmount": 2000.00,
                    "currency": "GBP",
                    "dueDate": "2099-12-31",  # not overdue
                    "status": "Submitted",
                },
            ]
        })

        overdue = client.get_overdue_invoices("comp-1")
        assert len(overdue) == 1
        assert overdue[0].invoice_number == "INV-001"

    def test_get_customers(self):
        client = self._make_client_with_mock_session({
            "results": [
                {"id": "cust-1", "customerName": "Debtor Co", "emailAddress": "ap@debtor.com"},
            ]
        })

        customers = client.get_customers("comp-1")
        assert len(customers) == 1
        assert customers[0]["customerName"] == "Debtor Co"

    def test_refresh_data_success(self):
        client = self._make_client_with_mock_session({})
        assert client.refresh_data("comp-1", "invoices") is True

    def test_api_error_returns_empty(self):
        import requests

        client = self._make_client_with_mock_session({})
        client.session.get.side_effect = requests.exceptions.ConnectionError("timeout")

        assert client.list_companies() == []
        assert client.get_invoices("comp-1") == []
        assert client.get_customers("comp-1") == []
