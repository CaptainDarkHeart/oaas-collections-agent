"""Xero API client for the Sentry (Integration Brain).

Handles:
- Fetching overdue invoices from Xero
- Parsing Xero's date formats (ISO and /Date(...)/)
- Normalising invoices into the shared NormalisedInvoice shape

Xero API docs: https://developer.xero.com/documentation/api/accounting/invoices
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from decimal import Decimal

from src.db.models import AccountingPlatform
from src.sentry.normalised_invoice import NormalisedInvoice
from src.utils.retry import resilient_session

logger = logging.getLogger(__name__)


class XeroAPIError(Exception):
    """Raised when the Xero API returns an unexpected error."""


class XeroRateLimitError(XeroAPIError):
    """Raised when Xero returns HTTP 429 (rate limited)."""


class XeroClient:
    """Client for the Xero Accounting API.

    Args:
        access_token: OAuth2 bearer token for Xero.
        tenant_id: Xero tenant (organisation) ID.
    """

    BASE_URL = "https://api.xero.com/api.xro/2.0"

    def __init__(self, access_token: str, tenant_id: str) -> None:
        self.access_token = access_token
        self.tenant_id = tenant_id
        self.session = resilient_session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Xero-Tenant-Id": tenant_id,
                "Accept": "application/json",
            }
        )

    def get_overdue_invoices(self) -> list[NormalisedInvoice]:
        """Fetch all authorised invoices past their due date.

        Uses Xero's OData-style filter to retrieve only AUTHORISED invoices
        with a DueDate before today.

        Returns:
            List of NormalisedInvoice objects for overdue invoices.
        """
        today = date.today()
        where_filter = (
            f'Status=="AUTHORISED"&&DueDate<DateTime({today.year},{today.month},{today.day})'
        )

        try:
            data = self._request("GET", "/Invoices", params={"where": where_filter})
        except XeroRateLimitError:
            logger.warning("Xero rate limit hit while fetching overdue invoices")
            return []
        except XeroAPIError as e:
            logger.error("Failed to fetch overdue invoices from Xero: %s", e)
            return []

        invoices: list[NormalisedInvoice] = []
        for inv in data.get("Invoices", []):
            try:
                normalised = self._parse_invoice(inv)
                invoices.append(normalised)
            except Exception:
                inv_id = inv.get("InvoiceID", "unknown")
                logger.warning("Skipping unparseable Xero invoice %s", inv_id, exc_info=True)

        logger.info(
            "Fetched %d overdue invoices from Xero (tenant %s)",
            len(invoices),
            self.tenant_id,
        )
        return invoices

    def get_invoice_status(self, invoice_id: str) -> str | None:
        """Fetch the status of a single invoice by its Xero InvoiceID.

        Returns the Xero status string (e.g. "AUTHORISED", "PAID", "VOIDED")
        or None if the invoice could not be fetched.
        """
        try:
            data = self._request("GET", f"/Invoices/{invoice_id}")
            invoices = data.get("Invoices", [])
            if invoices:
                return invoices[0].get("Status")
            return None
        except XeroAPIError as e:
            logger.warning("Could not fetch Xero invoice %s: %s", invoice_id, e)
            return None

    def create_payment(
        self,
        invoice_external_id: str,
        amount: Decimal,
        payment_date: date,
        account_code: str = "090",
    ) -> bool:
        """Record a payment against an invoice in Xero.

        Args:
            invoice_external_id: The Xero InvoiceID.
            amount: Payment amount.
            payment_date: Date the payment was made.
            account_code: Xero account code for the payment (default "090").

        Returns:
            True on success, False on failure.
        """
        payload = {
            "Invoice": {"InvoiceID": invoice_external_id},
            "Account": {"Code": account_code},
            "Amount": str(amount),
            "Date": payment_date.isoformat(),
        }
        try:
            self._request("POST", "/Payments", json_body=payload)
            logger.info(
                "Recorded payment of %s against Xero invoice %s",
                amount,
                invoice_external_id,
            )
            return True
        except XeroAPIError as e:
            logger.error(
                "Failed to record payment in Xero for invoice %s: %s",
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
        """Make an authenticated request to the Xero API.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: API path relative to BASE_URL (e.g. "/Invoices").
            params: Optional query parameters.

        Returns:
            Parsed JSON response body.

        Raises:
            XeroRateLimitError: If the API returns HTTP 429.
            XeroAPIError: For any other non-2xx response.
        """
        url = f"{self.BASE_URL}{path}"
        resp = self.session.request(method, url, params=params, json=json_body, timeout=30)

        if resp.status_code == 429:
            raise XeroRateLimitError(
                f"Rate limited by Xero (429) on {method} {path}"
            )

        if not resp.ok:
            raise XeroAPIError(
                f"Xero API error {resp.status_code} on {method} {path}: {resp.text[:500]}"
            )

        return resp.json()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_invoice(self, inv: dict) -> NormalisedInvoice:
        """Convert a raw Xero invoice dict into a NormalisedInvoice."""
        contact = inv.get("Contact", {})

        return NormalisedInvoice(
            external_id=inv["InvoiceID"],
            invoice_number=inv.get("InvoiceNumber", ""),
            debtor_company=contact.get("Name", ""),
            contact_name=contact.get("Name", ""),
            contact_email=contact.get("EmailAddress", ""),
            contact_phone=_extract_phone(contact),
            amount_due=Decimal(str(inv.get("AmountDue", 0))),
            currency=inv.get("CurrencyCode", "GBP"),
            due_date=_parse_xero_date(inv.get("DueDateString", inv.get("DueDate", ""))),
            platform=AccountingPlatform.XERO,
        )


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------

_XERO_DATE_RE = re.compile(r"/Date\((\d+)([+-]\d{4})?\)/")


def _parse_xero_date(value: str) -> date:
    """Parse a Xero date string into a Python date.

    Xero may return dates in two formats:
    - ISO 8601: "2026-03-15" or "2026-03-15T00:00:00"
    - .NET JSON: "/Date(1647302400000+0000)/"

    Args:
        value: The raw date string from Xero.

    Returns:
        A date object.

    Raises:
        ValueError: If the date string cannot be parsed.
    """
    if not value:
        raise ValueError("Empty date string")

    # Try .NET /Date(...)/ format first
    match = _XERO_DATE_RE.search(value)
    if match:
        timestamp_ms = int(match.group(1))
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date()

    # Try ISO format (with or without time component)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:len(fmt.replace("%", "0"))], fmt).date()
        except ValueError:
            continue

    # Last resort: try the standard parser
    return date.fromisoformat(value[:10])


def _extract_phone(contact: dict) -> str:
    """Extract the best available phone number from a Xero contact."""
    phones = contact.get("Phones", [])
    for phone in phones:
        number = phone.get("PhoneNumber", "")
        if number:
            area = phone.get("PhoneAreaCode", "")
            country = phone.get("PhoneCountryCode", "")
            parts = [p for p in (country, area, number) if p]
            return " ".join(parts)
    return ""
