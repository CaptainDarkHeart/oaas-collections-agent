"""FastAPI dashboard for the OaaS Collections Agent.

TactfulPay-inspired design: clean white nav, emerald green accents,
light slate backgrounds, generous spacing, premium fintech feel.

Provides:
- Invoice dashboard with stats, search/filter, and status overview
- Invoice detail with full interaction timeline
- CSV upload for importing invoices
- Manual controls: pause/resume agent, clear dispute/hostile flags
- API endpoints for programmatic access
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.db.models import (
    AccountingConnection,
    AccountingPlatform,
    ConnectionStatus,
    InvoicePhase,
    InvoiceStatus,
)
from src.sentry.oauth import encrypt_token, exchange_code, generate_auth_url, get_xero_tenant_id

logger = logging.getLogger(__name__)

_security = HTTPBasic()
_DASHBOARD_PASSWORD = settings.dashboard_password


def _require_auth(credentials: HTTPBasicCredentials = Depends(_security)) -> None:
    if not _DASHBOARD_PASSWORD:
        return  # No password set — open access
    ok = secrets.compare_digest(credentials.password.encode(), _DASHBOARD_PASSWORD.encode())
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=401,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )


app = FastAPI(
    title="OaaS Collections Agent",
    version="0.1.0",
    dependencies=[Depends(_require_auth)],
)


@app.get("/health", dependencies=[])
async def health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok"}


# Serve static assets (logos, etc.)
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Mount webhook router (no auth — webhooks use their own signature verification)
from src.sentry.webhook_handler import router as webhook_router  # noqa: E402

app.include_router(webhook_router)

# Demo mode: use in-memory data when no Supabase credentials are configured
DEMO_MODE = not os.environ.get("SUPABASE_URL")


def _db():
    if DEMO_MODE:
        return _demo_db()
    from src.db.models import Database

    return Database()


# ---------------------------------------------------------------------------
# Demo data (in-memory, no database needed)
# ---------------------------------------------------------------------------

# OAuth state tokens for CSRF protection
_oauth_states: dict[str, dict] = {}

_DEMO_SME_ID = str(uuid4())
_DEMO_SMES: dict[str, dict] = {}
_DEMO_INVOICES: dict[str, dict] = {}
_DEMO_CONTACTS: dict[str, list[dict]] = {}
_DEMO_INTERACTIONS: dict[str, list[dict]] = {}
_DEMO_CONNECTIONS: dict[str, dict] = {}
_DEMO_FEES: dict[str, dict] = {}


def _init_demo_data() -> None:
    if _DEMO_INVOICES:
        return  # Already initialised

    sme_id = _DEMO_SME_ID
    _DEMO_SMES[sme_id] = {
        "id": sme_id,
        "company_name": "Acme Digital Ltd",
        "contact_email": "owner@acmedigital.co.uk",
        "contact_phone": "+447700900100",
        "accounting_platform": "csv",
        "codat_company_id": None,
        "stripe_customer_id": None,
        "discount_authorised": True,
        "max_discount_percent": 3,
        "onboarded_at": (datetime.now(tz=UTC) - timedelta(days=30)).isoformat(),
        "status": "active",
    }

    test_data = [
        (
            "INV-2025-001",
            "BigCorp International",
            "7500.00",
            65,
            "1",
            "active",
            "Jane Smith",
            "jane.smith@bigcorp.example.com",
            "AP Manager",
        ),
        (
            "INV-2025-002",
            "MegaTech Solutions",
            "3200.00",
            72,
            "2",
            "active",
            "Tom Brown",
            "tom.brown@megatech.example.com",
            "Finance Director",
        ),
        (
            "INV-2025-003",
            "Global Services Ltd",
            "12000.00",
            90,
            "3",
            "active",
            "Sarah Johnson",
            "s.johnson@globalservices.example.com",
            "CFO",
        ),
        (
            "INV-2025-004",
            "Enterprise Holdings",
            "4800.00",
            61,
            "1",
            "active",
            "Mike Davis",
            "m.davis@enterprise.example.com",
            "Accounts Payable",
        ),
        (
            "INV-2025-005",
            "StartupCo",
            "1500.00",
            120,
            "4",
            "paused",
            "Alex Turner",
            "alex@startupco.example.com",
            "CEO",
        ),
        (
            "INV-2025-006",
            "Nordic Digital AS",
            "9200.00",
            80,
            "2",
            "active",
            "Erik Larsen",
            "erik@nordicdigital.example.com",
            "Head of Finance",
        ),
        (
            "INV-2025-007",
            "Catalyst Partners",
            "6100.00",
            68,
            "disputed",
            "disputed",
            "Rachel Green",
            "r.green@catalyst.example.com",
            "Operations Director",
        ),
        (
            "INV-2025-008",
            "Whitmore & Co",
            "2800.00",
            45,
            "resolved",
            "paid",
            "James Whitmore",
            "james@whitmore.example.com",
            "Managing Partner",
        ),
        (
            "INV-2025-009",
            "Pinnacle Group",
            "8500.00",
            55,
            "resolved",
            "paid",
            "Laura Chen",
            "l.chen@pinnacle.example.com",
            "Finance Manager",
        ),
        (
            "INV-2025-010",
            "Greenfield Ltd",
            "4200.00",
            40,
            "resolved",
            "paid",
            "David Park",
            "d.park@greenfield.example.com",
            "Accounts Director",
        ),
        (
            "INV-2025-011",
            "Atlas Consulting",
            "15000.00",
            95,
            "human_review",
            "written_off",
            "Nina Patel",
            "n.patel@atlas.example.com",
            "Managing Director",
        ),
    ]

    for inv_num, debtor, amount, days, phase, status, name, email, role in test_data:
        inv_id = str(uuid4())
        contact_id = str(uuid4())
        due = (date.today() - timedelta(days=days)).isoformat()

        created_at = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resolved_at = None
        fee_charged = False
        fee_amount = None

        if status == "paid":
            resolved_at = (datetime.now(tz=UTC) - timedelta(days=max(days - 20, 2))).isoformat()
            fee_charged = True
            inv_amount = float(amount)
            if inv_amount >= 5000:
                fee_amount = str(round(inv_amount * 0.10, 2))
            else:
                fee_amount = "500.00"

        _DEMO_INVOICES[inv_id] = {
            "id": inv_id,
            "sme_id": sme_id,
            "invoice_number": inv_num,
            "debtor_company": debtor,
            "amount": amount,
            "currency": "GBP",
            "due_date": due,
            "current_phase": phase,
            "status": status,
            "created_at": created_at,
            "resolved_at": resolved_at,
            "fee_charged": fee_charged,
            "fee_amount": fee_amount,
        }

        # Create fee records for paid invoices
        if status == "paid" and fee_amount:
            fee_id = str(uuid4())
            _DEMO_FEES[fee_id] = {
                "id": fee_id,
                "invoice_id": inv_id,
                "sme_id": sme_id,
                "fee_type": "percentage" if float(amount) >= 5000 else "flat",
                "fee_amount": fee_amount,
                "invoice_amount_recovered": amount,
                "stripe_payment_intent_id": None,
                "status": "charged",
                "created_at": resolved_at,
                "charged_at": resolved_at,
            }
        _DEMO_CONTACTS[inv_id] = [
            {
                "id": contact_id,
                "invoice_id": inv_id,
                "name": name,
                "email": email,
                "phone": "+4477009001XX",
                "role": role,
                "is_primary": True,
                "source": "csv_upload",
            }
        ]

        # Add some demo interactions for invoices past Phase 1
        interactions = []
        if phase in ("2", "3", "4", "disputed"):
            interactions.append(
                {
                    "id": str(uuid4()),
                    "invoice_id": inv_id,
                    "contact_id": contact_id,
                    "phase": 1,
                    "channel": "email",
                    "direction": "outbound",
                    "message_type": "initial",
                    "content": f"Subject: Quick check on invoice #{inv_num}\n\nHi {name},\n\nI was just updating our project folder and noticed the system hasn't checked off the latest invoice (#{inv_num}) as received yet. I know how messy email threads get - did that land in your inbox okay, or should I send a fresh link?\n\nBest,\nAlex\nAcme Digital Ltd",
                    "classification": None,
                    "sent_at": (datetime.now(tz=UTC) - timedelta(days=days - 2)).isoformat(),
                    "delivered": True,
                    "opened": True,
                    "replied": False,
                    "metadata": {},
                }
            )
            interactions.append(
                {
                    "id": str(uuid4()),
                    "invoice_id": inv_id,
                    "contact_id": contact_id,
                    "phase": 1,
                    "channel": "email",
                    "direction": "outbound",
                    "message_type": "follow_up",
                    "content": f"Subject: Re: Quick check on invoice #{inv_num}\n\nHi {name},\n\nSending this again in case it got buried - I know how hectic inboxes get. Just wanted to make sure Invoice #{inv_num} landed okay on your end.\n\nBest,\nAlex\nAcme Digital Ltd",
                    "classification": None,
                    "sent_at": (datetime.now(tz=UTC) - timedelta(days=days - 4)).isoformat(),
                    "delivered": True,
                    "opened": False,
                    "replied": False,
                    "metadata": {},
                }
            )
        if phase in ("3", "4"):
            interactions.append(
                {
                    "id": str(uuid4()),
                    "invoice_id": inv_id,
                    "contact_id": contact_id,
                    "phase": 2,
                    "channel": "email",
                    "direction": "outbound",
                    "message_type": "escalation",
                    "content": f"Subject: Re: Invoice #{inv_num} - trying to keep this off the report\n\nHi {name},\n\nIt seems like there's a hurdle on the processing side. I'd hate for our finance lead to flag this for a manual audit next week - it's a huge paperwork headache for everyone.\n\nIs there anything I can provide to help you get this pushed through today?\n\nAlex",
                    "classification": None,
                    "sent_at": (datetime.now(tz=UTC) - timedelta(days=days - 8)).isoformat(),
                    "delivered": True,
                    "opened": True,
                    "replied": True,
                    "metadata": {},
                }
            )
            interactions.append(
                {
                    "id": str(uuid4()),
                    "invoice_id": inv_id,
                    "contact_id": contact_id,
                    "phase": 2,
                    "channel": "email",
                    "direction": "inbound",
                    "message_type": "response",
                    "content": "Hi Alex, thanks for the reminder. We're working on it but things have been slow on our end with the new system migration. Should be sorted soon.",
                    "classification": "stall",
                    "sent_at": (datetime.now(tz=UTC) - timedelta(days=days - 9)).isoformat(),
                    "delivered": True,
                    "opened": None,
                    "replied": False,
                    "metadata": {},
                }
            )
        if phase == "disputed":
            interactions.append(
                {
                    "id": str(uuid4()),
                    "invoice_id": inv_id,
                    "contact_id": contact_id,
                    "phase": 2,
                    "channel": "email",
                    "direction": "inbound",
                    "message_type": "response",
                    "content": "We're disputing this invoice. The deliverables outlined in the SOW were not met and we have documented evidence of this. Please have your project lead contact us directly.",
                    "classification": "dispute",
                    "sent_at": (datetime.now(tz=UTC) - timedelta(days=days - 10)).isoformat(),
                    "delivered": True,
                    "opened": None,
                    "replied": False,
                    "metadata": {},
                }
            )

        _DEMO_INTERACTIONS[inv_id] = interactions


class _DemoDatabase:
    """In-memory mock database for demo/preview mode."""

    def list_active_smes(self):
        _init_demo_data()
        return [s for s in _DEMO_SMES.values() if s.get("status") == "active"]

    def list_active_invoices(self, sme_id=None):
        _init_demo_data()
        invoices = [v for v in _DEMO_INVOICES.values() if v["status"] == "active"]
        if sme_id:
            invoices = [v for v in invoices if v["sme_id"] == str(sme_id)]
        return invoices

    def list_all_invoices(self, sme_id=None):
        _init_demo_data()
        invoices = list(_DEMO_INVOICES.values())
        if sme_id:
            invoices = [v for v in invoices if v["sme_id"] == str(sme_id)]
        return invoices

    def list_all_fees(self):
        _init_demo_data()
        return list(_DEMO_FEES.values())

    def get_invoice(self, invoice_id):
        _init_demo_data()
        return _DEMO_INVOICES.get(str(invoice_id))

    def get_sme(self, sme_id):
        _init_demo_data()
        return _DEMO_SMES.get(str(sme_id))

    def create_sme(self, sme):
        _init_demo_data()
        if hasattr(sme, "model_dump"):
            data = sme.model_dump()
            data = {k: str(v) if isinstance(v, UUID) else v for k, v in data.items()}
            for k, v in data.items():
                if isinstance(v, datetime):
                    data[k] = v.isoformat()
                if hasattr(v, "value"):
                    data[k] = v.value
        else:
            data = sme
        _DEMO_SMES[str(data["id"])] = data
        return data

    def update_sme(self, sme_id, updates):
        _init_demo_data()
        sid = str(sme_id)
        if sid in _DEMO_SMES:
            _DEMO_SMES[sid].update(updates)
            return _DEMO_SMES[sid]
        return None

    def list_contacts(self, invoice_id):
        _init_demo_data()
        return _DEMO_CONTACTS.get(str(invoice_id), [])

    def get_primary_contact(self, invoice_id):
        contacts = self.list_contacts(invoice_id)
        return contacts[0] if contacts else None

    def list_interactions(self, invoice_id):
        _init_demo_data()
        return _DEMO_INTERACTIONS.get(str(invoice_id), [])

    def update_invoice(self, invoice_id, updates):
        _init_demo_data()
        inv_id = str(invoice_id)
        if inv_id in _DEMO_INVOICES:
            _DEMO_INVOICES[inv_id].update(updates)
            return _DEMO_INVOICES[inv_id]

    class _table_proxy:
        def __init__(self, data):
            self._data = data
            self._filters = {}

        def select(self, *a):
            return self

        def eq(self, k, v):
            self._filters[k] = v
            return self

        def execute(self):
            results = list(self._data.values())
            for k, v in self._filters.items():
                results = [r for r in results if r.get(k) == v]
            return type("R", (), {"data": results})()

    @property
    def client(self):
        parent = self

        class _client:
            @staticmethod
            def table(name):
                if name == "invoices":
                    return _DemoDatabase._table_proxy(parent._get_invoices())
                return _DemoDatabase._table_proxy({})

        return _client()

    def _get_invoices(self):
        _init_demo_data()
        return _DEMO_INVOICES

    # -- Accounting connections (demo) --

    def list_connections(self, sme_id):
        return [c for c in _DEMO_CONNECTIONS.values() if c.get("sme_id") == str(sme_id)]

    def create_connection(self, connection):
        data = connection.model_dump()
        data = {k: str(v) if isinstance(v, UUID) else v for k, v in data.items()}
        for k, v in data.items():
            if isinstance(v, datetime):
                data[k] = v.isoformat()
            if hasattr(v, "value"):
                data[k] = v.value
        _DEMO_CONNECTIONS[str(connection.id)] = data
        return data

    def delete_connection(self, connection_id):
        _DEMO_CONNECTIONS.pop(str(connection_id), None)

    def get_connection_by_id(self, connection_id):
        return _DEMO_CONNECTIONS.get(str(connection_id))


def _demo_db():
    return _DemoDatabase()


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------

COLORS = {
    "navy": "#0F172A",
    "navy_light": "#1E293B",
    "navy_dark": "#020617",
    "cyan": "#22C55E",
    "cyan_muted": "#16A34A",
    "cyan_pale": "#F0FDF4",
    "purple": "#22C55E",
    "purple_light": "#4ADE80",
    "sand": "#F8FAFC",
    "sand_dark": "#F1F5F9",
    "white": "#FFFFFF",
    "text_primary": "#0F172A",
    "text_secondary": "#475569",
    "text_muted": "#94A3B8",
    "border": "#E2E8F0",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "info": "#3B82F6",
}

PHASE_COLORS = {
    "1": {"bg": "#E0F2FE", "text": "#0369A1", "label": "Phase 1 — Liaison"},
    "2": {"bg": "#FEF3C7", "text": "#92400E", "label": "Phase 2 — Advocate"},
    "3": {"bg": "#FEE2E2", "text": "#991B1B", "label": "Phase 3 — Loss Aversion"},
    "4": {"bg": "#EDE9FE", "text": "#5B21B6", "label": "Phase 4 — Formal"},
    "human_review": {"bg": "#FEE2E2", "text": "#991B1B", "label": "Human Review"},
    "resolved": {"bg": "#D1FAE5", "text": "#065F46", "label": "Resolved"},
    "disputed": {"bg": "#FFEDD5", "text": "#9A3412", "label": "Disputed"},
}

STATUS_CONFIG = {
    "active": {"bg": "#D1FAE5", "text": "#065F46", "dot": "#10B981"},
    "paused": {"bg": "#FEF3C7", "text": "#92400E", "dot": "#F59E0B"},
    "paid": {"bg": "#DBEAFE", "text": "#1E40AF", "dot": "#3B82F6"},
    "disputed": {"bg": "#FFEDD5", "text": "#9A3412", "dot": "#F97316"},
    "written_off": {"bg": "#F3F4F6", "text": "#4B5563", "dot": "#6B7280"},
}


def _phase_badge(phase: str) -> str:
    cfg = PHASE_COLORS.get(phase, {"bg": "#F3F4F6", "text": "#4B5563", "label": phase})
    return (
        f'<span class="badge" style="background:{cfg["bg"]};color:{cfg["text"]}">'
        f"{cfg['label']}</span>"
    )


def _status_badge(status: str) -> str:
    cfg = STATUS_CONFIG.get(status, {"bg": "#F3F4F6", "text": "#4B5563", "dot": "#6B7280"})
    return (
        f'<span class="badge status-badge" style="background:{cfg["bg"]};color:{cfg["text"]}">'
        f'<span class="status-dot" style="background:{cfg["dot"]}"></span>'
        f"{status.replace('_', ' ').title()}</span>"
    )


def _fmt_currency(amount: str, currency: str = "GBP") -> str:
    """Format amount with currency symbol."""
    symbols = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac"}
    symbol = symbols.get(currency, currency + " ")
    try:
        val = float(amount)
        return f"{symbol}{val:,.2f}"
    except (ValueError, TypeError):
        return f"{symbol}{amount}"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    connected: str | None = None,
    synced: str | None = None,
    onboarded: str | None = None,
):
    """Main dashboard: list all invoices across all SMEs."""
    db = _db()
    smes = db.list_active_smes()

    # Build flash message HTML
    flash_html = ""
    if connected:
        platform_name = connected.replace("quickbooks", "QuickBooks").replace("xero", "Xero")
        flash_html = (
            f'<div style="background: var(--success); color: white; padding: 12px 20px;'
            f' border-radius: var(--radius-md); margin-bottom: 16px;">'
            f'&#10003; Successfully connected to {platform_name}</div>'
        )
    elif synced is not None:
        flash_html = (
            f'<div style="background: var(--success); color: white; padding: 12px 20px;'
            f' border-radius: var(--radius-md); margin-bottom: 16px;">'
            f'&#10003; Sync complete &mdash; {synced} invoice(s) imported</div>'
        )
    elif onboarded is not None:
        flash_html = (
            '<div style="background: var(--success); color: white; padding: 12px 20px;'
            ' border-radius: var(--radius-md); margin-bottom: 16px;">'
            '&#10003; New client onboarded successfully</div>'
        )

    # Build connections panel
    connections_html = _build_connections_panel(db, smes)

    rows = ""
    total_invoices = 0
    active_count = 0
    paused_count = 0
    total_outstanding = 0.0
    paid_count = 0

    for sme in smes:
        invoices = db.client.table("invoices").select("*").eq("sme_id", sme["id"]).execute().data
        for inv in invoices:
            total_invoices += 1
            status = inv["status"]
            if status == "active":
                active_count += 1
                total_outstanding += float(inv.get("amount", 0))
            elif status in ("paused", "disputed"):
                paused_count += 1
                total_outstanding += float(inv.get("amount", 0))
            elif status == "paid":
                paid_count += 1

            due = date.fromisoformat(inv["due_date"])
            days = (date.today() - due).days
            amount_fmt = _fmt_currency(inv["amount"], inv.get("currency", "GBP"))

            rows += f"""<tr class="table-row" onclick="window.location='/invoices/{inv["id"]}'">
                <td class="cell-invoice">
                    <span class="invoice-number">{inv["invoice_number"]}</span>
                </td>
                <td>
                    <div class="debtor-name">{inv["debtor_company"]}</div>
                    <div class="debtor-sme">{sme["company_name"]}</div>
                </td>
                <td class="cell-amount">{amount_fmt}</td>
                <td>
                    <span class="days-overdue {"days-critical" if days > 90 else "days-warning" if days > 75 else ""}">{days} days</span>
                </td>
                <td>{_phase_badge(inv["current_phase"])}</td>
                <td>{_status_badge(inv["status"])}</td>
            </tr>"""

    # Format the outstanding total
    outstanding_fmt = f"\u00a3{total_outstanding:,.0f}"
    recovery_rate = f"{(paid_count / total_invoices * 100):.0f}%" if total_invoices > 0 else "—"

    return HTMLResponse(
        _dashboard_html(
            rows=rows,
            total=total_invoices,
            active=active_count,
            paused=paused_count,
            outstanding=outstanding_fmt,
            recovery_rate=recovery_rate,
            sme_options=_sme_options(smes),
            connections_html=connections_html,
            flash_html=flash_html,
        )
    )


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(invoice_id: str):
    """Invoice detail page with interaction history."""
    try:
        uid = UUID(invoice_id)
    except ValueError:
        return HTMLResponse(
            _base_html("Not Found", '<div class="container"><h1>Invalid invoice ID</h1></div>'),
            status_code=404,
        )
    db = _db()
    invoice = db.get_invoice(uid)
    if not invoice:
        return HTMLResponse(
            _base_html("Not Found", '<div class="container"><h1>Invoice not found</h1></div>'),
            status_code=404,
        )

    contacts = db.list_contacts(UUID(invoice_id))
    interactions = db.list_interactions(UUID(invoice_id))
    sme = db.get_sme(UUID(invoice["sme_id"]))

    due = date.fromisoformat(invoice["due_date"])
    days_overdue = (date.today() - due).days
    amount_fmt = _fmt_currency(invoice["amount"], invoice.get("currency", "GBP"))

    # Build interaction timeline
    timeline = ""
    for ix in interactions:
        is_outbound = ix["direction"] == "outbound"
        direction_label = "Sent" if is_outbound else "Received"
        channel = ix["channel"].upper()

        classification_tag = ""
        if ix.get("classification"):
            cls_name = ix["classification"].replace("_", " ").upper()
            cls_color = "#EF4444" if ix["classification"] in ("dispute", "hostile") else "#22C55E"
            classification_tag = (
                f'<span class="timeline-classification" style="color:{cls_color}">{cls_name}</span>'
            )

        sent_at = ix["sent_at"][:16].replace("T", " ")
        border_color = "#22C55E" if is_outbound else "#0F172A"

        timeline += f"""<div class="timeline-item {"timeline-outbound" if is_outbound else "timeline-inbound"}">
            <div class="timeline-marker" style="background:{border_color}"></div>
            <div class="timeline-content">
                <div class="timeline-header">
                    <span class="timeline-direction">{direction_label}</span>
                    <span class="timeline-channel">{channel}</span>
                    <span class="timeline-type">{ix["message_type"].replace("_", " ").title()}</span>
                    {classification_tag}
                    <span class="timeline-time">{sent_at}</span>
                </div>
                <div class="timeline-body">{_escape(ix["content"][:1500])}</div>
            </div>
        </div>"""

    if not timeline:
        timeline = """<div class="empty-state">
            <div class="empty-icon">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#A3A9BA" stroke-width="1.5">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                </svg>
            </div>
            <p>No interactions yet. The agent will begin outreach based on the cadence schedule.</p>
        </div>"""

    # Build contacts
    contacts_html = ""
    for c in contacts:
        primary_tag = '<span class="contact-primary">Primary</span>' if c.get("is_primary") else ""
        role = f'<span class="contact-role">{c["role"]}</span>' if c.get("role") else ""
        contacts_html += f"""<div class="contact-card">
            <div class="contact-info">
                <div class="contact-name">{c["name"]} {primary_tag}</div>
                {role}
                <div class="contact-email">{c["email"]}</div>
                {'<div class="contact-phone">' + c["phone"] + "</div>" if c.get("phone") else ""}
            </div>
        </div>"""

    # Action buttons
    actions = ""
    if invoice["status"] in ("paused", "disputed"):
        actions = f"""<form method="post" action="/invoices/{invoice_id}/resume" class="inline-form">
            <button type="submit" class="btn btn-primary">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Clear Flag &amp; Resume Agent
            </button>
        </form>"""
    elif invoice["status"] == "active":
        actions = f"""<form method="post" action="/invoices/{invoice_id}/pause" class="inline-form">
            <button type="submit" class="btn btn-warning">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                Pause Agent
            </button>
        </form>"""

    return HTMLResponse(
        _detail_html(
            invoice_id=invoice_id,
            invoice_number=invoice["invoice_number"],
            debtor_company=invoice["debtor_company"],
            sme_name=sme["company_name"] if sme else "Unknown",
            amount=amount_fmt,
            days_overdue=str(days_overdue),
            due_date=invoice["due_date"],
            phase_badge=_phase_badge(invoice["current_phase"]),
            status_badge=_status_badge(invoice["status"]),
            contacts=contacts_html,
            timeline=timeline,
            actions=actions,
            interaction_count=len(interactions),
        )
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@app.post("/invoices/{invoice_id}/pause")
async def pause_invoice(invoice_id: str):
    db = _db()
    db.update_invoice(UUID(invoice_id), {"status": InvoiceStatus.PAUSED.value})
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


@app.post("/invoices/{invoice_id}/resume")
async def resume_invoice(invoice_id: str):
    db = _db()
    invoice = db.get_invoice(UUID(invoice_id))
    if invoice:
        phase = invoice["current_phase"]
        if phase in ("human_review", "disputed"):
            phase = InvoicePhase.PHASE_1.value
        db.update_invoice(
            UUID(invoice_id),
            {
                "status": InvoiceStatus.ACTIVE.value,
                "current_phase": phase,
            },
        )
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


@app.post("/upload-csv")
async def upload_csv(sme_id: str = Form(...), file: UploadFile = File(...)):
    if DEMO_MODE:
        return RedirectResponse("/", status_code=303)
    from src.sentry.csv_importer import import_csv

    db = _db()
    content = await file.read()
    import_csv(content, UUID(sme_id), db)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@app.get("/api/invoices")
async def api_list_invoices(sme_id: str | None = None):
    db = _db()
    if sme_id:
        return db.list_active_invoices(sme_id=UUID(sme_id))
    return db.client.table("invoices").select("*").execute().data


@app.get("/api/invoices/{invoice_id}")
async def api_get_invoice(invoice_id: str):
    db = _db()
    invoice = db.get_invoice(UUID(invoice_id))
    if not invoice:
        return {"error": "Not found"}
    interactions = db.list_interactions(UUID(invoice_id))
    contacts = db.list_contacts(UUID(invoice_id))
    return {"invoice": invoice, "interactions": interactions, "contacts": contacts}


@app.get("/api/smes")
async def api_list_smes():
    db = _db()
    return db.list_active_smes()


@app.post("/api/smes")
async def api_create_sme(request: Request):
    """Create a new SME client via JSON API."""
    from src.db.models import SME as _SME

    body = await request.json()
    sme = _SME(
        company_name=body["company_name"],
        contact_email=body["contact_email"],
        contact_phone=body.get("contact_phone", ""),
        accounting_platform=body.get("accounting_platform", "csv"),
        discount_authorised=body.get("discount_authorised", False),
        max_discount_percent=body.get("max_discount_percent", 0),
    )
    db = _db()
    result = db.create_sme(sme)
    return result


@app.get("/api/smes/{sme_id}")
async def api_get_sme(sme_id: str):
    """Get SME details."""
    db = _db()
    sme = db.get_sme(UUID(sme_id))
    if not sme:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="SME not found")
    return sme


@app.patch("/api/smes/{sme_id}")
async def api_update_sme(sme_id: str, request: Request):
    """Update SME fields."""
    db = _db()
    sme = db.get_sme(UUID(sme_id))
    if not sme:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="SME not found")
    body = await request.json()
    result = db.update_sme(UUID(sme_id), body)
    return result


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


@app.get("/onboard", response_class=HTMLResponse)
async def onboard_page():
    """SME onboarding form."""
    return HTMLResponse(_onboard_html())


@app.post("/onboard")
async def onboard_submit(
    company_name: str = Form(...),
    contact_email: str = Form(...),
    contact_phone: str = Form(""),
    accounting_platform: str = Form("csv"),
    discount_authorised: bool = Form(False),
    max_discount_percent: float = Form(0),
):
    """Create SME from onboarding form and redirect to dashboard."""
    from src.db.models import SME as _SME

    sme = _SME(
        company_name=company_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        accounting_platform=accounting_platform,
        discount_authorised=discount_authorised,
        max_discount_percent=max_discount_percent,
    )
    db = _db()
    db.create_sme(sme)
    return RedirectResponse("/?onboarded=true", status_code=303)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _compute_reports(db) -> dict:
    """Compute reporting data from the database."""
    all_invoices = db.list_all_invoices()
    all_fees = db.list_all_fees()

    total = len(all_invoices)
    paid_count = sum(1 for inv in all_invoices if inv["status"] == "paid")
    recovery_rate = (paid_count / total * 100) if total > 0 else 0

    # Average days to collection for resolved invoices
    days_list = []
    for inv in all_invoices:
        if inv.get("resolved_at") and inv.get("created_at"):
            try:
                resolved = datetime.fromisoformat(str(inv["resolved_at"]))
                created = datetime.fromisoformat(str(inv["created_at"]))
                days_list.append((resolved - created).days)
            except (ValueError, TypeError):
                pass
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else 0

    # Revenue earned
    revenue = sum(float(f["fee_amount"]) for f in all_fees if f.get("status") == "charged")

    # Phase distribution
    phase_counts: dict[str, int] = {}
    for inv in all_invoices:
        p = inv.get("current_phase", "unknown")
        phase_counts[p] = phase_counts.get(p, 0) + 1

    # Status breakdown
    status_counts: dict[str, int] = {}
    for inv in all_invoices:
        s = inv.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total_invoices": total,
        "paid_count": paid_count,
        "recovery_rate": round(recovery_rate, 1),
        "avg_days_to_collection": avg_days,
        "revenue_earned": round(revenue, 2),
        "phase_distribution": phase_counts,
        "status_breakdown": status_counts,
    }


@app.get("/api/reports")
async def api_reports():
    """JSON reporting endpoint."""
    db = _db()
    return _compute_reports(db)


@app.get("/reports", response_class=HTMLResponse)
async def reports_page():
    """Reports dashboard page."""
    db = _db()
    data = _compute_reports(db)

    # Build phase distribution bar chart
    phase_bars = ""
    max_phase = max(data["phase_distribution"].values()) if data["phase_distribution"] else 1
    for phase, count in sorted(data["phase_distribution"].items()):
        cfg = PHASE_COLORS.get(phase, {"bg": "#F3F4F6", "text": "#4B5563", "label": phase})
        width_pct = (count / max_phase * 100) if max_phase > 0 else 0
        phase_bars += f"""<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
            <div style="width:120px;font-size:13px;font-weight:600;color:{cfg['text']};flex-shrink:0">{cfg['label']}</div>
            <div style="flex:1;background:var(--sand-dark);border-radius:6px;height:28px;overflow:hidden">
                <div style="width:{width_pct}%;height:100%;background:{cfg['bg']};border-radius:6px;min-width:2px;
                            display:flex;align-items:center;padding-left:10px;font-size:12px;font-weight:600;color:{cfg['text']}">{count}</div>
            </div>
        </div>"""

    # Build status breakdown bar chart
    status_bars = ""
    max_status = max(data["status_breakdown"].values()) if data["status_breakdown"] else 1
    for status, count in sorted(data["status_breakdown"].items()):
        cfg = STATUS_CONFIG.get(status, {"bg": "#F3F4F6", "text": "#4B5563", "dot": "#6B7280"})
        width_pct = (count / max_status * 100) if max_status > 0 else 0
        label = status.replace("_", " ").title()
        status_bars += f"""<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px">
            <div style="width:120px;font-size:13px;font-weight:600;color:{cfg['text']};flex-shrink:0;display:flex;align-items:center;gap:6px">
                <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{cfg['dot']}"></span>
                {label}
            </div>
            <div style="flex:1;background:var(--sand-dark);border-radius:6px;height:28px;overflow:hidden">
                <div style="width:{width_pct}%;height:100%;background:{cfg['bg']};border-radius:6px;min-width:2px;
                            display:flex;align-items:center;padding-left:10px;font-size:12px;font-weight:600;color:{cfg['text']}">{count}</div>
            </div>
        </div>"""

    revenue_fmt = f"\u00a3{data['revenue_earned']:,.2f}"
    recovery_fmt = f"{data['recovery_rate']:.1f}%"
    avg_days_fmt = f"{data['avg_days_to_collection']:.0f}" if data['avg_days_to_collection'] else "\u2014"

    content = f"""
    <div class="container">
        <div class="page-header">
            <h1>Recovery Reports</h1>
            <p>Performance analytics across all collection activity.</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card stat-highlight">
                <div class="stat-label">Revenue Earned</div>
                <div class="stat-value">{revenue_fmt}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Recovery Rate</div>
                <div class="stat-value">{recovery_fmt}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avg Days to Collect</div>
                <div class="stat-value">{avg_days_fmt}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Invoices</div>
                <div class="stat-value">{data['total_invoices']}</div>
            </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
            <div class="card">
                <div class="card-header">
                    <h2>Phase Distribution</h2>
                </div>
                <div class="card-body">
                    {phase_bars if phase_bars else '<p style="color:var(--text-muted)">No data yet.</p>'}
                </div>
            </div>
            <div class="card">
                <div class="card-header">
                    <h2>Status Breakdown</h2>
                </div>
                <div class="card-body">
                    {status_bars if status_bars else '<p style="color:var(--text-muted)">No data yet.</p>'}
                </div>
            </div>
        </div>
    </div>
    """

    return HTMLResponse(_base_html("Reports", content))


# ---------------------------------------------------------------------------
# OAuth & accounting connections
# ---------------------------------------------------------------------------


@app.get("/connect/{platform}")
async def connect_platform(platform: str, sme_id: str | None = None):
    """Initiate OAuth flow for Xero or QuickBooks."""
    if platform not in ("xero", "quickbooks"):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"Unsupported platform: {platform}")

    db = _db()

    # Resolve SME ID
    if sme_id is None:
        smes = db.list_active_smes()
        if len(smes) == 1:
            sme_id = smes[0]["id"]
        else:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="Multiple SMEs found — provide sme_id query param",
            )

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "sme_id": sme_id,
        "platform": platform,
        "created_at": datetime.now(tz=UTC),
    }

    acct_platform = AccountingPlatform(platform)
    redirect_uri = f"{settings.oauth_redirect_base_url}/callback/{platform}"
    auth_url = generate_auth_url(acct_platform, UUID(sme_id), state)

    # Override the redirect_uri in the generated URL to use our dashboard callback
    # The oauth module builds its own redirect URI, so we rebuild with ours
    if platform == "xero":
        from src.sentry.oauth import _XERO_AUTH_URL, _XERO_SCOPES

        auth_url = (
            f"{_XERO_AUTH_URL}"
            f"?response_type=code"
            f"&client_id={settings.xero_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={_XERO_SCOPES}"
            f"&state={state}"
        )
    elif platform == "quickbooks":
        from src.sentry.oauth import _QB_AUTH_URL, _QB_SCOPES

        auth_url = (
            f"{_QB_AUTH_URL}"
            f"?response_type=code"
            f"&client_id={settings.quickbooks_client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={_QB_SCOPES}"
            f"&state={state}"
        )

    return RedirectResponse(auth_url)


@app.get("/callback/xero", dependencies=[])
async def callback_xero(
    code: str = Query(...),
    state: str = Query(...),
):
    """Xero OAuth callback — no auth required."""
    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    sme_id = state_data["sme_id"]
    redirect_uri = f"{settings.oauth_redirect_base_url}/callback/xero"

    # Exchange code for tokens
    token_resp = exchange_code(AccountingPlatform.XERO, code, redirect_uri)

    access_token = token_resp["access_token"]
    refresh_token = token_resp["refresh_token"]
    expires_in = token_resp.get("expires_in", 1800)

    # Get Xero tenant ID
    tenant_id = get_xero_tenant_id(access_token)

    # Encrypt tokens
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token)

    # Store connection
    connection = AccountingConnection(
        sme_id=UUID(sme_id),
        platform=AccountingPlatform.XERO,
        access_token=encrypted_access,
        refresh_token=encrypted_refresh,
        token_expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(seconds=expires_in),
        tenant_id=tenant_id,
        status=ConnectionStatus.ACTIVE,
    )
    db = _db()
    db.create_connection(connection)

    return RedirectResponse("/?connected=xero", status_code=303)


@app.get("/callback/quickbooks", dependencies=[])
async def callback_quickbooks(
    code: str = Query(...),
    state: str = Query(...),
    realmId: str = Query(...),  # noqa: N803 — QuickBooks sends this param name
):
    """QuickBooks OAuth callback — no auth required."""
    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    sme_id = state_data["sme_id"]
    redirect_uri = f"{settings.oauth_redirect_base_url}/callback/quickbooks"

    # Exchange code for tokens
    token_resp = exchange_code(AccountingPlatform.QUICKBOOKS, code, redirect_uri)

    access_token = token_resp["access_token"]
    refresh_token = token_resp["refresh_token"]
    expires_in = token_resp.get("expires_in", 3600)

    # Encrypt tokens
    encrypted_access = encrypt_token(access_token)
    encrypted_refresh = encrypt_token(refresh_token)

    # Store connection
    connection = AccountingConnection(
        sme_id=UUID(sme_id),
        platform=AccountingPlatform.QUICKBOOKS,
        access_token=encrypted_access,
        refresh_token=encrypted_refresh,
        token_expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(seconds=expires_in),
        tenant_id=realmId,
        status=ConnectionStatus.ACTIVE,
    )
    db = _db()
    db.create_connection(connection)

    return RedirectResponse("/?connected=quickbooks", status_code=303)


@app.post("/disconnect/{connection_id}")
async def disconnect_connection(connection_id: str):
    """Remove an accounting connection."""
    db = _db()
    db.delete_connection(UUID(connection_id))
    return RedirectResponse("/", status_code=303)


@app.post("/sync/{connection_id}")
async def sync_connection(connection_id: str):
    """Manual sync trigger for an accounting connection."""
    try:
        from src.sentry.invoice_sync import sync_from_connection, upsert_normalised_invoices

        db = _db()
        raw_invoices = sync_from_connection(UUID(connection_id), db)
        count = upsert_normalised_invoices(raw_invoices, db)
    except ImportError:
        logger.warning("sync_from_connection not yet implemented — skipping sync")
        count = 0
    except Exception:
        logger.exception("Sync failed for connection %s", connection_id)
        count = 0

    return RedirectResponse(f"/?synced={count}", status_code=303)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_connections_panel(db, smes: list[dict]) -> str:
    """Build the accounting connections panel HTML."""
    all_connections = []
    for sme in smes:
        try:
            conns = db.list_connections(UUID(sme["id"]) if not isinstance(sme["id"], UUID) else sme["id"])
            for c in conns:
                c["_sme_name"] = sme["company_name"]
            all_connections.extend(conns)
        except Exception:
            pass  # list_connections may not exist on older DB class

    # Build connection items or connect buttons
    if all_connections:
        items = ""
        for conn in all_connections:
            platform = conn.get("platform", "unknown")
            platform_label = platform.replace("quickbooks", "QuickBooks").replace("xero", "Xero")
            conn_id = conn.get("id", "")
            last_sync = conn.get("last_sync_at")

            if last_sync:
                try:
                    if isinstance(last_sync, str):
                        sync_dt = datetime.fromisoformat(last_sync)
                    else:
                        sync_dt = last_sync
                    delta = datetime.now(tz=UTC).replace(tzinfo=None) - (
                        sync_dt.replace(tzinfo=None) if sync_dt.tzinfo else sync_dt
                    )
                    hours = int(delta.total_seconds() // 3600)
                    if hours < 1:
                        sync_text = "Last sync: just now"
                    elif hours < 24:
                        sync_text = f"Last sync: {hours}h ago"
                    else:
                        days = hours // 24
                        sync_text = f"Last sync: {days}d ago"
                except Exception:
                    sync_text = "Last sync: unknown"
            else:
                sync_text = "Never synced"

            accent = "#13B5EA" if platform == "xero" else "#2CA01C"

            items += f"""
                <div style="display: flex; align-items: center; gap: 12px; padding: 10px 16px;
                            background: var(--sand); border-radius: var(--radius-sm); border: 1px solid var(--border);">
                    <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%;
                                 background: {accent}; flex-shrink: 0;"></span>
                    <span style="font-weight: 600; font-size: 14px; color: var(--text-primary);">
                        {platform_label} connected</span>
                    <span style="font-size: 12px; color: var(--text-muted);">&middot; {sync_text}</span>
                    <form method="post" action="/sync/{conn_id}" style="display: inline; margin-left: auto;">
                        <button type="submit" class="btn btn-outline" style="padding: 6px 14px; font-size: 12px;">
                            Sync Now
                        </button>
                    </form>
                    <form method="post" action="/disconnect/{conn_id}" style="display: inline;">
                        <button type="submit" class="btn btn-outline"
                                style="padding: 6px 14px; font-size: 12px; color: var(--danger); border-color: var(--danger);"
                                onclick="return confirm('Disconnect this accounting integration?')">
                            Disconnect
                        </button>
                    </form>
                </div>"""

        # Still show connect buttons for platforms not yet connected
        connected_platforms = {c.get("platform") for c in all_connections}
        extra_buttons = ""
        if "xero" not in connected_platforms:
            extra_buttons += (
                '<a href="/connect/xero" class="btn btn-outline"'
                ' style="padding: 8px 16px; font-size: 13px; color: #13B5EA; border-color: #13B5EA;">'
                "Connect Xero</a>"
            )
        if "quickbooks" not in connected_platforms:
            extra_buttons += (
                '<a href="/connect/quickbooks" class="btn btn-outline"'
                ' style="padding: 8px 16px; font-size: 13px; color: #2CA01C; border-color: #2CA01C;">'
                "Connect QuickBooks</a>"
            )

        inner = f"""{items}
            <div style="display: flex; gap: 12px; margin-top: 4px;">{extra_buttons}</div>"""
    else:
        inner = """
            <a href="/connect/xero" class="btn btn-outline"
               style="padding: 10px 20px; font-size: 14px; color: #13B5EA; border-color: #13B5EA;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
                Connect Xero
            </a>
            <a href="/connect/quickbooks" class="btn btn-outline"
               style="padding: 10px 20px; font-size: 14px; color: #2CA01C; border-color: #2CA01C;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     stroke-width="2" style="flex-shrink:0"><circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
                Connect QuickBooks
            </a>"""

    return f"""<div class="card" style="margin-bottom: 24px;">
        <div class="card-header">
            <h2>Accounting Connections</h2>
        </div>
        <div style="padding: 20px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap;">
            {inner}
        </div>
    </div>"""


def _escape(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("\n", "<br>")
    )


def _sme_options(smes: list[dict]) -> str:
    opts = ""
    for sme in smes:
        opts += f'<option value="{sme["id"]}">{sme["company_name"]}</option>'
    return opts


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------


def _base_html(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — TactfulPay</title>
    <link rel="icon" type="image/png" href="/static/logo-square.png">
    <style>
        /* ================================================================
           OaaS Design System — TactfulPay inspired
           Dark navy + emerald green accent + light slate backgrounds
           ================================================================ */

        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        :root {{
            --navy: {COLORS["navy"]};
            --navy-light: {COLORS["navy_light"]};
            --navy-dark: {COLORS["navy_dark"]};
            --cyan: {COLORS["cyan"]};
            --cyan-muted: {COLORS["cyan_muted"]};
            --cyan-pale: {COLORS["cyan_pale"]};
            --purple: {COLORS["purple"]};
            --purple-light: {COLORS["purple_light"]};
            --sand: {COLORS["sand"]};
            --sand-dark: {COLORS["sand_dark"]};
            --white: {COLORS["white"]};
            --text-primary: {COLORS["text_primary"]};
            --text-secondary: {COLORS["text_secondary"]};
            --text-muted: {COLORS["text_muted"]};
            --border: {COLORS["border"]};
            --success: {COLORS["success"]};
            --warning: {COLORS["warning"]};
            --danger: {COLORS["danger"]};
            --radius-sm: 6px;
            --radius-md: 12px;
            --radius-lg: 16px;
            --radius-xl: 24px;
            --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.04);
            --shadow-md: 0 4px 12px rgba(15, 23, 42, 0.08);
            --shadow-lg: 0 8px 30px rgba(15, 23, 42, 0.12);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--sand);
            color: var(--text-primary);
            line-height: 1.5;
            -webkit-font-smoothing: antialiased;
        }}

        /* Nav */
        .nav {{
            background: var(--navy);
            border-bottom: none;
            padding: 0 32px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 64px;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .nav-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
            text-decoration: none;
        }}
        .nav-logo {{
            height: 40px;
            width: 40px;
            background: var(--white);
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 4px;
            flex-shrink: 0;
        }}
        .nav-logo img {{
            height: 100%;
            width: auto;
            display: block;
        }}
        .nav-links {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .nav-link {{
            color: rgba(255,255,255,0.65);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            padding: 8px 16px;
            border-radius: var(--radius-sm);
            transition: all 0.15s ease;
        }}
        .nav-link:hover, .nav-link.active {{
            color: var(--white);
            background: rgba(255,255,255,0.1);
        }}

        /* Container */
        .container {{
            max-width: 1280px;
            margin: 0 auto;
            padding: 32px;
        }}

        /* Page header */
        .page-header {{
            margin-bottom: 32px;
        }}
        .page-header h1 {{
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -0.5px;
            color: var(--navy);
        }}
        .page-header p {{
            color: var(--text-secondary);
            font-size: 15px;
            margin-top: 4px;
        }}

        /* Stats grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: var(--white);
            border-radius: var(--radius-lg);
            padding: 24px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border);
            transition: all 0.2s ease;
        }}
        .stat-card:hover {{
            box-shadow: var(--shadow-md);
            transform: translateY(-1px);
        }}
        .stat-card.stat-highlight {{
            background: var(--navy);
            border-color: var(--navy);
        }}
        .stat-card.stat-highlight .stat-label {{
            color: rgba(255,255,255,0.6);
        }}
        .stat-card.stat-highlight .stat-value {{
            color: var(--cyan);
        }}
        .stat-label {{
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: 700;
            color: var(--navy);
            letter-spacing: -1px;
            line-height: 1.1;
        }}

        /* Card */
        .card {{
            background: var(--white);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border);
            overflow: hidden;
        }}
        .card-header {{
            padding: 20px 24px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .card-header h2 {{
            font-size: 16px;
            font-weight: 600;
            color: var(--navy);
        }}
        .card-body {{
            padding: 24px;
        }}

        /* Table */
        .data-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .data-table th {{
            text-align: left;
            padding: 12px 20px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            background: var(--sand);
            border-bottom: 1px solid var(--border);
        }}
        .data-table td {{
            padding: 16px 20px;
            font-size: 14px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }}
        .table-row {{
            cursor: pointer;
            transition: background 0.1s ease;
        }}
        .table-row:hover {{
            background: var(--cyan-pale);
        }}
        .table-row:last-child td {{
            border-bottom: none;
        }}
        .cell-invoice {{
            font-weight: 600;
        }}
        .invoice-number {{
            color: var(--purple);
        }}
        .cell-amount {{
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }}
        .debtor-name {{
            font-weight: 500;
            color: var(--text-primary);
        }}
        .debtor-sme {{
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 2px;
        }}
        .days-overdue {{
            font-weight: 500;
            font-variant-numeric: tabular-nums;
        }}
        .days-warning {{
            color: var(--warning);
        }}
        .days-critical {{
            color: var(--danger);
            font-weight: 600;
        }}

        /* Badges */
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 100px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.2px;
            white-space: nowrap;
        }}
        .status-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            display: inline-block;
        }}

        /* Buttons */
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 10px 20px;
            border-radius: var(--radius-sm);
            font-size: 14px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.15s ease;
            text-decoration: none;
            font-family: inherit;
        }}
        .btn-primary {{
            background: var(--cyan);
            color: var(--white);
        }}
        .btn-primary:hover {{
            background: var(--cyan-muted);
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(34, 197, 94, 0.3);
        }}
        .btn-secondary {{
            background: var(--navy);
            color: var(--white);
        }}
        .btn-secondary:hover {{
            background: var(--navy-light);
        }}
        .btn-warning {{
            background: #FEF3C7;
            color: #92400E;
            border: 1px solid #FDE68A;
        }}
        .btn-warning:hover {{
            background: #FDE68A;
        }}
        .btn-outline {{
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border);
        }}
        .btn-outline:hover {{
            background: var(--sand);
            border-color: var(--text-muted);
        }}
        .inline-form {{
            display: inline;
        }}

        /* Upload area */
        .upload-area {{
            border: 2px dashed var(--border);
            border-radius: var(--radius-md);
            padding: 32px;
            text-align: center;
            transition: all 0.2s ease;
            background: var(--sand);
        }}
        .upload-area:hover {{
            border-color: var(--cyan-muted);
            background: var(--cyan-pale);
        }}
        .upload-icon {{
            margin-bottom: 12px;
        }}
        .upload-label {{
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 4px;
        }}
        .upload-hint {{
            font-size: 13px;
            color: var(--text-muted);
        }}

        /* Detail page */
        .detail-header {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            margin-bottom: 32px;
        }}
        .detail-title {{
            font-size: 28px;
            font-weight: 700;
            color: var(--navy);
            letter-spacing: -0.5px;
        }}
        .detail-badges {{
            display: flex;
            gap: 8px;
            margin-top: 8px;
        }}
        .detail-meta {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 32px;
        }}
        .meta-card {{
            background: var(--white);
            border-radius: var(--radius-md);
            padding: 20px;
            border: 1px solid var(--border);
        }}
        .meta-label {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 6px;
        }}
        .meta-value {{
            font-size: 20px;
            font-weight: 700;
            color: var(--navy);
        }}
        .meta-value.meta-amount {{
            color: var(--purple);
        }}
        .meta-value.meta-danger {{
            color: var(--danger);
        }}

        /* Contact cards */
        .contact-card {{
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
        }}
        .contact-card:last-child {{
            border-bottom: none;
        }}
        .contact-avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            background: var(--navy);
            color: var(--cyan);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 15px;
            flex-shrink: 0;
        }}
        .contact-name {{
            font-weight: 600;
            font-size: 14px;
        }}
        .contact-primary {{
            background: var(--cyan-pale);
            color: var(--cyan-muted);
            font-size: 10px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 100px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-left: 8px;
        }}
        .contact-role {{
            font-size: 12px;
            color: var(--text-muted);
        }}
        .contact-email, .contact-phone {{
            font-size: 13px;
            color: var(--text-secondary);
        }}

        /* Timeline */
        .timeline {{
            position: relative;
            padding-left: 32px;
        }}
        .timeline::before {{
            content: '';
            position: absolute;
            left: 11px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: var(--border);
        }}
        .timeline-item {{
            position: relative;
            padding-bottom: 24px;
        }}
        .timeline-item:last-child {{
            padding-bottom: 0;
        }}
        .timeline-marker {{
            position: absolute;
            left: -27px;
            top: 4px;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            border: 3px solid var(--white);
            box-shadow: 0 0 0 2px var(--border);
        }}
        .timeline-content {{
            background: var(--white);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 16px 20px;
            transition: box-shadow 0.15s ease;
        }}
        .timeline-content:hover {{
            box-shadow: var(--shadow-md);
        }}
        .timeline-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }}
        .timeline-direction {{
            font-weight: 600;
            font-size: 13px;
            color: var(--navy);
        }}
        .timeline-channel, .timeline-type {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            background: var(--sand);
            padding: 2px 8px;
            border-radius: 4px;
            color: var(--text-muted);
        }}
        .timeline-classification {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .timeline-time {{
            font-size: 12px;
            color: var(--text-muted);
            margin-left: auto;
        }}
        .timeline-body {{
            font-size: 13px;
            line-height: 1.6;
            color: var(--text-secondary);
            word-break: break-word;
        }}

        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 48px 24px;
            color: var(--text-muted);
        }}
        .empty-icon {{
            margin-bottom: 16px;
        }}
        .empty-state p {{
            font-size: 14px;
            max-width: 320px;
            margin: 0 auto;
        }}

        /* Back link */
        .back-link {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 24px;
            transition: color 0.15s ease;
        }}
        .back-link:hover {{
            color: var(--navy);
        }}

        /* Grid layout for detail page */
        .detail-grid {{
            display: grid;
            grid-template-columns: 1fr 340px;
            gap: 24px;
        }}

        /* Responsive */
        @media (max-width: 1024px) {{
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .detail-meta {{ grid-template-columns: repeat(2, 1fr); }}
            .detail-grid {{ grid-template-columns: 1fr; }}
        }}
        @media (max-width: 640px) {{
            .container {{ padding: 16px; }}
            .stats-grid {{ grid-template-columns: 1fr; }}
            .detail-meta {{ grid-template-columns: 1fr; }}
            .nav {{ padding: 0 16px; }}
        }}
    </style>
</head>
<body>
    <nav class="nav">
        <a href="/" class="nav-brand">
            <div class="nav-logo">
                <img src="/static/logo-square.png" alt="TactfulPay">
            </div>
        </a>
        <div class="nav-links">
            <a href="/" class="nav-link active">Dashboard</a>
            <a href="/onboard" class="nav-link">Add Client</a>
            <a href="/reports" class="nav-link">Reports</a>
        </div>
    </nav>
    {content}
</body>
</html>"""


def _dashboard_html(
    rows: str,
    total: int,
    active: int,
    paused: int,
    outstanding: str,
    recovery_rate: str,
    sme_options: str,
    connections_html: str = "",
    flash_html: str = "",
) -> str:
    return _base_html(
        "Dashboard",
        f"""
    <div class="container">
        <div class="page-header">
            <h1>Collections Dashboard</h1>
            <p>Track and manage overdue invoice recovery across all clients.</p>
        </div>

        {flash_html}

        {connections_html}

        <div class="stats-grid">
            <div class="stat-card stat-highlight">
                <div class="stat-label">Outstanding</div>
                <div class="stat-value">{outstanding}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Active Invoices</div>
                <div class="stat-value">{active}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Needs Attention</div>
                <div class="stat-value">{paused}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Recovery Rate</div>
                <div class="stat-value">{recovery_rate}</div>
            </div>
        </div>

        <div class="card" style="margin-bottom:24px">
            <div class="card-header">
                <h2>All Invoices</h2>
            </div>
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Invoice</th>
                        <th>Company</th>
                        <th>Amount</th>
                        <th>Overdue</th>
                        <th>Phase</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows if rows else '<tr><td colspan="6" style="text-align:center;padding:48px;color:var(--text-muted)"><div class="empty-state"><div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#A3A9BA" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div><p>No invoices yet. Upload a CSV below to get started.</p></div></td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="card">
            <div class="card-header">
                <h2>Import Invoices</h2>
            </div>
            <div class="card-body">
                <form method="post" action="/upload-csv" enctype="multipart/form-data">
                    <div style="margin-bottom:16px">
                        <label class="meta-label" for="sme_id">Client (SME)</label>
                        <select name="sme_id" id="sme_id" required style="display:block;width:100%;max-width:400px;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                            {sme_options if sme_options else '<option value="">No clients — create an SME first</option>'}
                        </select>
                    </div>
                    <div class="upload-area" id="dropZone">
                        <div class="upload-icon">
                            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="{COLORS["text_muted"]}" stroke-width="1.5">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="17 8 12 3 7 8"/>
                                <line x1="12" y1="3" x2="12" y2="15"/>
                            </svg>
                        </div>
                        <div class="upload-label">Drop your CSV here or click to browse</div>
                        <div class="upload-hint">Required columns: debtor_company, contact_name, contact_email, invoice_number, amount, due_date</div>
                        <input type="file" name="file" accept=".csv" required style="margin-top:16px;font-size:14px;font-family:inherit">
                    </div>
                    <div style="margin-top:16px">
                        <button type="submit" class="btn btn-secondary">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                            Upload &amp; Import
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
    """,
    )


def _detail_html(
    invoice_id: str,
    invoice_number: str,
    debtor_company: str,
    sme_name: str,
    amount: str,
    days_overdue: str,
    due_date: str,
    phase_badge: str,
    status_badge: str,
    contacts: str,
    timeline: str,
    actions: str,
    interaction_count: int,
) -> str:
    days_int = int(days_overdue) if days_overdue.isdigit() else 0
    days_class = "meta-danger" if days_int > 90 else ""

    return _base_html(
        f"Invoice #{invoice_number}",
        f"""
    <div class="container">
        <a href="/" class="back-link">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
            Back to Dashboard
        </a>

        <div class="detail-header">
            <div>
                <div class="detail-title">Invoice #{invoice_number}</div>
                <div class="detail-badges">
                    {phase_badge}
                    {status_badge}
                </div>
            </div>
            <div>{actions}</div>
        </div>

        <div class="detail-meta">
            <div class="meta-card">
                <div class="meta-label">Amount</div>
                <div class="meta-value meta-amount">{amount}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Days Overdue</div>
                <div class="meta-value {days_class}">{days_overdue}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Debtor</div>
                <div class="meta-value" style="font-size:16px">{debtor_company}</div>
            </div>
            <div class="meta-card">
                <div class="meta-label">Client</div>
                <div class="meta-value" style="font-size:16px">{sme_name}</div>
            </div>
        </div>

        <div class="detail-grid">
            <div>
                <div class="card">
                    <div class="card-header">
                        <h2>Interaction Timeline</h2>
                        <span class="badge" style="background:var(--sand);color:var(--text-muted)">{interaction_count} interactions</span>
                    </div>
                    <div class="card-body">
                        <div class="timeline">
                            {timeline}
                        </div>
                    </div>
                </div>
            </div>

            <div>
                <div class="card" style="margin-bottom:20px">
                    <div class="card-header">
                        <h2>Contacts</h2>
                    </div>
                    {contacts if contacts else '<div class="empty-state"><p>No contacts found.</p></div>'}
                </div>

                <div class="card">
                    <div class="card-header">
                        <h2>Invoice Details</h2>
                    </div>
                    <div class="card-body" style="font-size:14px">
                        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
                            <span style="color:var(--text-muted)">Invoice #</span>
                            <span style="font-weight:600">{invoice_number}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
                            <span style="color:var(--text-muted)">Due Date</span>
                            <span style="font-weight:600">{due_date}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
                            <span style="color:var(--text-muted)">Amount</span>
                            <span style="font-weight:600">{amount}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;padding:8px 0">
                            <span style="color:var(--text-muted)">Overdue</span>
                            <span style="font-weight:600">{days_overdue} days</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """,
    )


def _onboard_html() -> str:
    return _base_html(
        "Add Client",
        f"""
    <div class="container" style="max-width:680px">
        <a href="/" class="back-link">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
            Back to Dashboard
        </a>
        <div class="page-header">
            <h1>Add New Client</h1>
            <p>Onboard a new SME client to start collections.</p>
        </div>
        <div class="card">
            <div class="card-body">
                <form method="post" action="/onboard">
                    <div style="margin-bottom:20px">
                        <label class="meta-label" for="company_name">Company Name *</label>
                        <input type="text" name="company_name" id="company_name" required
                               style="display:block;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                    </div>
                    <div style="margin-bottom:20px">
                        <label class="meta-label" for="contact_email">Contact Email *</label>
                        <input type="email" name="contact_email" id="contact_email" required
                               style="display:block;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                    </div>
                    <div style="margin-bottom:20px">
                        <label class="meta-label" for="contact_phone">Contact Phone</label>
                        <input type="tel" name="contact_phone" id="contact_phone"
                               style="display:block;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                    </div>
                    <div style="margin-bottom:20px">
                        <label class="meta-label" for="accounting_platform">Accounting Platform</label>
                        <select name="accounting_platform" id="accounting_platform"
                                style="display:block;width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                            <option value="csv">CSV</option>
                            <option value="xero">Xero</option>
                            <option value="quickbooks">QuickBooks</option>
                        </select>
                    </div>
                    <div style="margin-bottom:20px;display:flex;align-items:center;gap:10px">
                        <input type="checkbox" name="discount_authorised" id="discount_authorised" value="true"
                               style="width:18px;height:18px;accent-color:{COLORS['cyan']}">
                        <label for="discount_authorised" style="font-size:14px;font-weight:500;color:var(--text-primary)">Discount Authorised</label>
                    </div>
                    <div style="margin-bottom:24px">
                        <label class="meta-label" for="max_discount_percent">Max Discount %</label>
                        <input type="number" name="max_discount_percent" id="max_discount_percent" value="0" min="0" max="100" step="0.5"
                               style="display:block;width:200px;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:14px;font-family:inherit;background:var(--white);color:var(--text-primary);margin-top:6px">
                    </div>
                    <button type="submit" class="btn btn-primary">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/>
                            <line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>
                        </svg>
                        Add Client
                    </button>
                </form>
            </div>
        </div>
    </div>
    """,
    )
