"""Shared normalised invoice dataclass for all accounting platform integrations.

Used by Xero, QuickBooks, Codat, and CSV importers to present a uniform
invoice representation to the Sentry brain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.db.models import AccountingPlatform


@dataclass
class NormalisedInvoice:
    """Platform-agnostic representation of an overdue invoice."""

    external_id: str
    invoice_number: str
    debtor_company: str
    contact_name: str
    contact_email: str
    contact_phone: str
    amount_due: Decimal
    currency: str
    due_date: date
    platform: AccountingPlatform
