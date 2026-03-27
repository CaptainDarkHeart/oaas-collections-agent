"""QuickBooks Online API client for the Sentry (Integration Brain).

Handles:
- Fetching overdue invoices via the QuickBooks query API
- Resolving customer contact details (email, phone)
- Normalising invoices into the shared NormalisedInvoice shape

QuickBooks API docs: https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/invoice
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import requests

from src.db.models import AccountingPlatform
from src.sentry.normalised_invoice import NormalisedInvoice
from src.utils.retry import resilient_session

logger = logging.getLogger(__name__)


class QuickBooksAPIError(Exception):
    """Raised when the QuickBooks API returns an unexpected error."""


class QuickBooksRateLimitError(QuickBooksAPIError):
    """Raised when QuickBooks returns HTTP 429 (rate limited)."""


class QuickBooksClient:
    """Client for the QuickBooks Online Accounting API.

    Args:
        access_token: OAuth2 bearer token for QuickBooks.
        realm_id: The QuickBooks company (realm) ID.
        sandbox: Whether to use the sandbox environment (default True).
    """

    PRODUCTION_URL = "https://quickbooks.api.intuit.com/v3/company"
    SANDBOX_URL = "https://sandbox-quickbooks.api.intuit.com/v3/company"

    def __init__(
        self,
        access_token: str,
        realm_id: str,
        sandbox: bool = True,
    ) -> None:
        self.access_token = access_token
        self.realm_id = realm_id
        self.sandbox = sandbox
        self.base_url = self.SANDBOX_URL if sandbox else self.PRODUCTION_URL
        self.session = resilient_session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )

    def get_overdue_invoices(self) -> list[NormalisedInvoice]:
        """Fetch all invoices with a positive balance past their due date.

        Uses a QuickBooks SQL-like query to find invoices where
        DueDate < today AND Balance > 0.

        Returns:
            List of NormalisedInvoice objects for overdue invoices.
        """
        today = date.today().isoformat()
        query = f"SELECT * FROM Invoice WHERE DueDate < '{today}' AND Balance > '0'"

        try:
            data = self._request("GET", "/query", params={"query": query})
        except QuickBooksRateLimitError:
            logger.warning("QuickBooks rate limit hit while fetching overdue invoices")
            return []
        except QuickBooksAPIError as e:
            logger.error("Failed to fetch overdue invoices from QuickBooks: %s", e)
            return []

        query_response = data.get("QueryResponse", {})
        raw_invoices = query_response.get("Invoice", [])

        if not raw_invoices:
            logger.info(
                "No overdue invoices found in QuickBooks (realm %s)", self.realm_id
            )
            return []

        # Collect unique customer IDs so we can batch-resolve contact details
        customer_cache: dict[str, dict] = {}

        invoices: list[NormalisedInvoice] = []
        for inv in raw_invoices:
            try:
                customer_id = inv.get("CustomerRef", {}).get("value", "")
                if customer_id and customer_id not in customer_cache:
                    customer_cache[customer_id] = self._fetch_customer_safe(customer_id)

                customer = customer_cache.get(customer_id, {})
                normalised = self._parse_invoice(inv, customer)
                invoices.append(normalised)
            except Exception:
                inv_id = inv.get("Id", "unknown")
                logger.warning(
                    "Skipping unparseable QuickBooks invoice %s",
                    inv_id,
                    exc_info=True,
                )

        logger.info(
            "Fetched %d overdue invoices from QuickBooks (realm %s)",
            len(invoices),
            self.realm_id,
        )
        return invoices

    def get_customer(self, customer_id: str) -> dict:
        """Fetch a single customer record by ID.

        Args:
            customer_id: The QuickBooks customer ID.

        Returns:
            The raw customer dict from the QuickBooks API.

        Raises:
            QuickBooksAPIError: If the request fails.
        """
        data = self._request("GET", f"/customer/{customer_id}")
        return data.get("Customer", {})

    def get_invoice_status(self, invoice_id: str) -> tuple[str | None, bool]:
        """Fetch the status of a single invoice by its QuickBooks ID.

        Returns a tuple of (status_string, is_paid) where is_paid is True
        if Balance == 0. Returns (None, False) on failure.
        """
        try:
            data = self._request("GET", f"/invoice/{invoice_id}")
            invoice = data.get("Invoice", {})
            balance = invoice.get("Balance", -1)
            return invoice.get("Id"), float(balance) == 0.0
        except QuickBooksAPIError as e:
            logger.warning("Could not fetch QuickBooks invoice %s: %s", invoice_id, e)
            return None, False

    def create_payment(
        self,
        invoice_external_id: str,
        amount: Decimal,
        payment_date: date,
    ) -> bool:
        """Record a payment against an invoice in QuickBooks.

        Args:
            invoice_external_id: The QuickBooks Invoice ID.
            amount: Payment amount.
            payment_date: Date the payment was made.

        Returns:
            True on success, False on failure.
        """
        payload = {
            "TxnDate": payment_date.isoformat(),
            "TotalAmt": str(amount),
            "Line": [
                {
                    "Amount": str(amount),
                    "LinkedTxn": [
                        {
                            "TxnId": invoice_external_id,
                            "TxnType": "Invoice",
                        }
                    ],
                }
            ],
        }
        try:
            self._request("POST", "/payment", json_body=payload)
            logger.info(
                "Recorded payment of %s against QuickBooks invoice %s",
                amount,
                invoice_external_id,
            )
            return True
        except QuickBooksAPIError as e:
            logger.error(
                "Failed to record payment in QuickBooks for invoice %s: %s",
                invoice_external_id,
                e,
            )
            return False

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict:
        """Make an authenticated request to the QuickBooks API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path relative to /{realm_id} (e.g. "/query", "/customer/123").
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            QuickBooksRateLimitError: If the API returns HTTP 429.
            QuickBooksAPIError: For any other non-2xx response.
        """
        url = f"{self.base_url}/{self.realm_id}{path}"
        resp = self.session.request(method, url, params=params, json=json_body, timeout=30)

        if resp.status_code == 429:
            raise QuickBooksRateLimitError(
                f"Rate limited by QuickBooks (429) on {method} {path}"
            )

        if not resp.ok:
            raise QuickBooksAPIError(
                f"QuickBooks API error {resp.status_code} on {method} {path}: "
                f"{resp.text[:500]}"
            )

        return resp.json()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_customer_safe(self, customer_id: str) -> dict:
        """Fetch a customer, returning an empty dict on failure."""
        try:
            return self.get_customer(customer_id)
        except (QuickBooksAPIError, requests.exceptions.RequestException) as e:
            logger.warning(
                "Could not fetch QuickBooks customer %s: %s", customer_id, e
            )
            return {}

    def _parse_invoice(self, inv: dict, customer: dict) -> NormalisedInvoice:
        """Convert a raw QuickBooks invoice dict into a NormalisedInvoice.

        Args:
            inv: The raw invoice from the QuickBooks query response.
            customer: The resolved customer record (may be empty).

        Returns:
            A NormalisedInvoice.
        """
        customer_ref = inv.get("CustomerRef", {})

        # Contact details come from the separate customer record
        email = customer.get("PrimaryEmailAddr", {}).get("Address", "")
        phone = customer.get("PrimaryPhone", {}).get("FreeFormNumber", "")
        display_name = customer.get("DisplayName", customer_ref.get("name", ""))

        return NormalisedInvoice(
            external_id=inv["Id"],
            invoice_number=inv.get("DocNumber", ""),
            debtor_company=customer_ref.get("name", ""),
            contact_name=display_name,
            contact_email=email,
            contact_phone=phone,
            amount_due=Decimal(str(inv.get("Balance", 0))),
            currency=inv.get("CurrencyRef", {}).get("value", "GBP"),
            due_date=date.fromisoformat(inv["DueDate"]),
            platform=AccountingPlatform.QUICKBOOKS,
        )
