"""Database models and Supabase client for the OaaS Collections Agent.

Defines Pydantic models for validation and a thin Supabase wrapper for CRUD.
Tables: smes, invoices, contacts, interactions, fees.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.config import settings


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountingPlatform(str, enum.Enum):
    XERO = "xero"
    QUICKBOOKS = "quickbooks"
    FRESHBOOKS = "freshbooks"
    SAGE = "sage"
    CSV = "csv"


class SMEStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CHURNED = "churned"


class InvoicePhase(str, enum.Enum):
    PHASE_1 = "1"
    PHASE_2 = "2"
    PHASE_3 = "3"
    PHASE_4 = "4"
    HUMAN_REVIEW = "human_review"
    RESOLVED = "resolved"
    DISPUTED = "disputed"


class InvoiceStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    PAID = "paid"
    DISPUTED = "disputed"
    WRITTEN_OFF = "written_off"


class Channel(str, enum.Enum):
    EMAIL = "email"
    VOICE = "voice"
    LINKEDIN = "linkedin"
    SMS = "sms"


class Direction(str, enum.Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class MessageType(str, enum.Enum):
    INITIAL = "initial"
    FOLLOW_UP = "follow_up"
    RESPONSE = "response"
    ESCALATION = "escalation"


class Classification(str, enum.Enum):
    PROMISE_TO_PAY = "promise_to_pay"
    PAYMENT_PENDING = "payment_pending"
    DISPUTE = "dispute"
    REDIRECT = "redirect"
    STALL = "stall"
    HOSTILE = "hostile"
    NO_RESPONSE = "no_response"


class ContactSource(str, enum.Enum):
    CSV_UPLOAD = "csv_upload"
    CODAT_SYNC = "codat_sync"
    DISCOVERY_AGENT = "discovery_agent"
    REDIRECT = "redirect"


class FeeType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FLAT = "flat"


class FeeStatus(str, enum.Enum):
    PENDING = "pending"
    CHARGED = "charged"
    FAILED = "failed"
    WAIVED = "waived"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SME(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    company_name: str
    contact_email: str
    contact_phone: str = ""
    accounting_platform: AccountingPlatform = AccountingPlatform.CSV
    codat_company_id: str | None = None
    stripe_customer_id: str | None = None
    discount_authorised: bool = False
    max_discount_percent: Decimal = Decimal("0")
    onboarded_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC).replace(tzinfo=None))
    status: SMEStatus = SMEStatus.ACTIVE


class Invoice(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    sme_id: UUID
    invoice_number: str
    debtor_company: str
    amount: Decimal
    currency: str = "GBP"
    due_date: date
    current_phase: InvoicePhase = InvoicePhase.PHASE_1
    status: InvoiceStatus = InvoiceStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC).replace(tzinfo=None))
    resolved_at: datetime | None = None
    fee_charged: bool = False
    fee_amount: Decimal | None = None

    @property
    def days_overdue(self) -> int:
        return (date.today() - self.due_date).days


class Contact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    name: str
    email: str
    phone: str | None = None
    linkedin_url: str | None = None
    role: str | None = None
    is_primary: bool = True
    source: ContactSource = ContactSource.CSV_UPLOAD


class Interaction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    contact_id: UUID
    phase: int
    channel: Channel
    direction: Direction
    message_type: MessageType
    content: str
    classification: Classification | None = None
    sent_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC).replace(tzinfo=None))
    delivered: bool = False
    opened: bool | None = None
    replied: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class Fee(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    invoice_id: UUID
    sme_id: UUID
    fee_type: FeeType
    fee_amount: Decimal
    invoice_amount_recovered: Decimal
    stripe_payment_intent_id: str | None = None
    status: FeeStatus = FeeStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC).replace(tzinfo=None))
    charged_at: datetime | None = None


# ---------------------------------------------------------------------------
# Supabase client wrapper
# ---------------------------------------------------------------------------

class Database:
    """Thin wrapper around the Supabase client for CRUD operations."""

    def __init__(self) -> None:
        from supabase import create_client

        self.client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # -- SME --

    def create_sme(self, sme: SME) -> dict:
        return (
            self.client.table("smes")
            .insert(self._serialize(sme))
            .execute()
            .data[0]
        )

    def get_sme(self, sme_id: UUID) -> dict | None:
        resp = (
            self.client.table("smes")
            .select("*")
            .eq("id", str(sme_id))
            .execute()
        )
        return resp.data[0] if resp.data else None

    def list_active_smes(self) -> list[dict]:
        return (
            self.client.table("smes")
            .select("*")
            .eq("status", SMEStatus.ACTIVE.value)
            .execute()
            .data
        )

    # -- Invoice --

    def create_invoice(self, invoice: Invoice) -> dict:
        return (
            self.client.table("invoices")
            .insert(self._serialize(invoice))
            .execute()
            .data[0]
        )

    def get_invoice(self, invoice_id: UUID) -> dict | None:
        resp = (
            self.client.table("invoices")
            .select("*")
            .eq("id", str(invoice_id))
            .execute()
        )
        return resp.data[0] if resp.data else None

    def list_active_invoices(self, sme_id: UUID | None = None) -> list[dict]:
        query = (
            self.client.table("invoices")
            .select("*")
            .eq("status", InvoiceStatus.ACTIVE.value)
        )
        if sme_id:
            query = query.eq("sme_id", str(sme_id))
        return query.execute().data

    def update_invoice(self, invoice_id: UUID, updates: dict) -> dict:
        serialized = {k: self._serialize_value(v) for k, v in updates.items()}
        return (
            self.client.table("invoices")
            .update(serialized)
            .eq("id", str(invoice_id))
            .execute()
            .data[0]
        )

    # -- Contact --

    def create_contact(self, contact: Contact) -> dict:
        return (
            self.client.table("contacts")
            .insert(self._serialize(contact))
            .execute()
            .data[0]
        )

    def get_primary_contact(self, invoice_id: UUID) -> dict | None:
        resp = (
            self.client.table("contacts")
            .select("*")
            .eq("invoice_id", str(invoice_id))
            .eq("is_primary", True)
            .execute()
        )
        return resp.data[0] if resp.data else None

    def list_contacts(self, invoice_id: UUID) -> list[dict]:
        return (
            self.client.table("contacts")
            .select("*")
            .eq("invoice_id", str(invoice_id))
            .execute()
            .data
        )

    # -- Interaction --

    def create_interaction(self, interaction: Interaction) -> dict:
        return (
            self.client.table("interactions")
            .insert(self._serialize(interaction))
            .execute()
            .data[0]
        )

    def list_interactions(self, invoice_id: UUID) -> list[dict]:
        return (
            self.client.table("interactions")
            .select("*")
            .eq("invoice_id", str(invoice_id))
            .order("sent_at", desc=False)
            .execute()
            .data
        )

    def get_latest_outbound(self, invoice_id: UUID) -> dict | None:
        resp = (
            self.client.table("interactions")
            .select("*")
            .eq("invoice_id", str(invoice_id))
            .eq("direction", Direction.OUTBOUND.value)
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None

    # -- Fee --

    def create_fee(self, fee: Fee) -> dict:
        return (
            self.client.table("fees")
            .insert(self._serialize(fee))
            .execute()
            .data[0]
        )

    # -- Helpers --

    @staticmethod
    def _serialize_value(v: Any) -> Any:
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, enum.Enum):
            return v.value
        return v

    @classmethod
    def _serialize(cls, model: BaseModel) -> dict:
        data = model.model_dump()
        return {k: cls._serialize_value(v) for k, v in data.items()}
