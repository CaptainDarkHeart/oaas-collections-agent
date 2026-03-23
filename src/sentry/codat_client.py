"""Codat API wrapper for the Sentry (Integration Brain).

Handles:
- Listing connected companies
- Pulling invoices (with overdue filtering)
- Pulling customer/contact details
- Checking connection status

Codat API docs: https://docs.codat.io/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import requests

from src.config import settings

logger = logging.getLogger(__name__)

CODAT_BASE_URL = "https://api.codat.io"


@dataclass
class CodatInvoice:
    """Normalised invoice from Codat."""

    codat_invoice_id: str
    invoice_number: str
    customer_name: str
    customer_email: str = ""
    contact_name: str = ""
    amount_due: float = 0.0
    total_amount: float = 0.0
    currency: str = "GBP"
    issue_date: str = ""
    due_date: str = ""
    status: str = ""
    paid_on_date: str | None = None


@dataclass
class CodatCompany:
    """A company connected through Codat."""

    codat_company_id: str
    name: str
    platform: str = ""
    status: str = ""


@dataclass
class CodatSyncResult:
    """Result of a Codat sync operation."""

    success: bool
    companies_synced: int = 0
    invoices_found: int = 0
    overdue_invoices: int = 0
    errors: list[str] = field(default_factory=list)


class CodatClient:
    """Client for the Codat unified accounting API."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.codat_api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Basic {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def list_companies(self) -> list[CodatCompany]:
        """List all companies connected through Codat."""
        try:
            resp = self.session.get(
                f"{CODAT_BASE_URL}/companies",
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            return [
                CodatCompany(
                    codat_company_id=c["id"],
                    name=c.get("name", ""),
                    platform=c.get("platform", ""),
                    status=c.get("status", ""),
                )
                for c in data.get("results", [])
            ]
        except requests.exceptions.RequestException as e:
            logger.error("Failed to list Codat companies: %s", e)
            return []

    def get_invoices(
        self,
        company_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> list[CodatInvoice]:
        """Fetch invoices for a connected company.

        Args:
            company_id: The Codat company ID.
            page: Page number (1-indexed).
            page_size: Results per page.

        Returns:
            List of normalised CodatInvoice objects.
        """
        try:
            resp = self.session.get(
                f"{CODAT_BASE_URL}/companies/{company_id}/data/invoices",
                params={"page": page, "pageSize": page_size},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            invoices = []
            for inv in data.get("results", []):
                customer_ref = inv.get("customerRef", {})
                invoices.append(
                    CodatInvoice(
                        codat_invoice_id=inv["id"],
                        invoice_number=inv.get("invoiceNumber", ""),
                        customer_name=customer_ref.get("companyName", ""),
                        customer_email=_extract_email(inv),
                        contact_name=_extract_contact_name(inv),
                        amount_due=float(inv.get("amountDue", 0)),
                        total_amount=float(inv.get("totalAmount", 0)),
                        currency=inv.get("currency", "GBP"),
                        issue_date=inv.get("issueDate", ""),
                        due_date=inv.get("dueDate", ""),
                        status=inv.get("status", ""),
                        paid_on_date=inv.get("paidOnDate"),
                    )
                )

            return invoices

        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch invoices for company %s: %s", company_id, e)
            return []

    def get_overdue_invoices(self, company_id: str) -> list[CodatInvoice]:
        """Fetch only overdue (unpaid, past due date) invoices for a company."""
        all_invoices = self.get_invoices(company_id)
        today = date.today().isoformat()

        return [
            inv
            for inv in all_invoices
            if inv.status not in ("Paid", "Void", "Draft")
            and inv.due_date
            and inv.due_date < today
            and inv.amount_due > 0
        ]

    def get_customers(self, company_id: str) -> list[dict]:
        """Fetch customer records for a connected company."""
        try:
            resp = self.session.get(
                f"{CODAT_BASE_URL}/companies/{company_id}/data/customers",
                params={"pageSize": 100},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch customers for company %s: %s", company_id, e)
            return []

    def get_company_status(self, company_id: str) -> dict | None:
        """Check connection/sync status for a company."""
        try:
            resp = self.session.get(
                f"{CODAT_BASE_URL}/companies/{company_id}/dataStatus",
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("Failed to get status for company %s: %s", company_id, e)
            return None

    def refresh_data(self, company_id: str, data_type: str = "invoices") -> bool:
        """Trigger a data refresh for a specific data type.

        Args:
            company_id: The Codat company ID.
            data_type: The data type to refresh (e.g. "invoices", "customers").

        Returns:
            True if refresh was queued successfully.
        """
        try:
            resp = self.session.post(
                f"{CODAT_BASE_URL}/companies/{company_id}/data/queue/{data_type}",
                timeout=30,
            )
            resp.raise_for_status()
            logger.info("Queued %s refresh for company %s", data_type, company_id)
            return True
        except requests.exceptions.RequestException as e:
            logger.error("Failed to queue refresh for company %s: %s", company_id, e)
            return False


def _extract_email(invoice_data: dict) -> str:
    """Try to extract a contact email from Codat invoice data."""
    customer_ref = invoice_data.get("customerRef", {})
    if "email" in customer_ref:
        return customer_ref["email"]

    # Some platforms put contacts in metadata or line items
    metadata = invoice_data.get("metadata", {})
    return metadata.get("customerEmail", "")


def _extract_contact_name(invoice_data: dict) -> str:
    """Try to extract a contact person name from Codat invoice data."""
    customer_ref = invoice_data.get("customerRef", {})
    return customer_ref.get("contactName", customer_ref.get("companyName", ""))
