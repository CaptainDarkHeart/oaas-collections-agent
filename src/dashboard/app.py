"""Basic FastAPI dashboard for the OaaS Collections Agent.

Provides:
- Invoice list with status, phase, and days overdue
- Invoice detail with full interaction history
- CSV upload for importing invoices
- Manual controls: pause/resume agent, clear dispute/hostile flags
- API endpoints for programmatic access
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.db.models import Database, InvoicePhase, InvoiceStatus, SME
from src.sentry.csv_importer import import_csv

TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="OaaS Collections Agent", version="0.1.0")


def _db() -> Database:
    return Database()


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _render(template_name: str, **context: object) -> HTMLResponse:
    """Render an HTML template with context substitution."""
    template_path = TEMPLATES_DIR / template_name
    html = template_path.read_text()
    for key, value in context.items():
        html = html.replace(f"{{{{{key}}}}}", str(value))
    return HTMLResponse(html)


def _phase_badge(phase: str) -> str:
    colors = {
        "1": "#3B82F6", "2": "#F59E0B", "3": "#EF4444", "4": "#7C3AED",
        "human_review": "#DC2626", "resolved": "#10B981", "disputed": "#F97316",
    }
    color = colors.get(phase, "#6B7280")
    label = f"Phase {phase}" if phase.isdigit() else phase.replace("_", " ").title()
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{label}</span>'


def _status_badge(status: str) -> str:
    colors = {
        "active": "#10B981", "paused": "#F59E0B", "paid": "#3B82F6",
        "disputed": "#F97316", "written_off": "#6B7280",
    }
    color = colors.get(status, "#6B7280")
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{status.title()}</span>'


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Main dashboard: list all invoices across all SMEs."""
    db = _db()
    smes = db.list_active_smes()

    rows = ""
    total_invoices = 0
    active_count = 0
    paused_count = 0

    for sme in smes:
        invoices = db.client.table("invoices").select("*").eq("sme_id", sme["id"]).execute().data
        for inv in invoices:
            total_invoices += 1
            if inv["status"] == "active":
                active_count += 1
            elif inv["status"] in ("paused", "disputed"):
                paused_count += 1

            due = date.fromisoformat(inv["due_date"])
            days = (date.today() - due).days

            rows += f"""<tr>
                <td><a href="/invoices/{inv['id']}">{inv['invoice_number']}</a></td>
                <td>{inv['debtor_company']}</td>
                <td>{sme['company_name']}</td>
                <td>{inv['currency']} {inv['amount']}</td>
                <td>{days} days</td>
                <td>{_phase_badge(inv['current_phase'])}</td>
                <td>{_status_badge(inv['status'])}</td>
            </tr>"""

    return HTMLResponse(_dashboard_html(
        rows=rows,
        total=total_invoices,
        active=active_count,
        paused=paused_count,
    ))


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(invoice_id: str):
    """Invoice detail page with interaction history."""
    db = _db()
    invoice = db.get_invoice(UUID(invoice_id))
    if not invoice:
        return HTMLResponse("<h1>Invoice not found</h1>", status_code=404)

    contacts = db.list_contacts(UUID(invoice_id))
    interactions = db.list_interactions(UUID(invoice_id))
    sme = db.get_sme(UUID(invoice["sme_id"]))

    due = date.fromisoformat(invoice["due_date"])
    days_overdue = (date.today() - due).days

    # Build interaction timeline
    timeline = ""
    for ix in interactions:
        direction_icon = "→" if ix["direction"] == "outbound" else "←"
        direction_class = "outbound" if ix["direction"] == "outbound" else "inbound"
        classification_tag = ""
        if ix.get("classification"):
            classification_tag = f' <span style="background:#EEE;padding:1px 6px;border-radius:3px;font-size:11px">{ix["classification"].upper()}</span>'

        sent_at = ix["sent_at"][:16].replace("T", " ")
        timeline += f"""<div style="border-left:3px solid {'#3B82F6' if ix['direction']=='outbound' else '#10B981'};padding:8px 16px;margin:8px 0">
            <div style="font-size:12px;color:#666">{sent_at} {direction_icon} {ix['channel'].upper()} ({ix['message_type']}){classification_tag}</div>
            <pre style="white-space:pre-wrap;font-size:13px;margin:4px 0">{ix['content'][:1000]}</pre>
        </div>"""

    if not timeline:
        timeline = "<p style='color:#999'>No interactions yet.</p>"

    # Build contacts list
    contacts_html = ""
    for c in contacts:
        primary = " (primary)" if c.get("is_primary") else ""
        contacts_html += f"<li>{c['name']} — {c['email']}{primary}</li>"

    # Action buttons
    actions = ""
    if invoice["status"] in ("paused", "disputed"):
        actions = f"""<form method="post" action="/invoices/{invoice_id}/resume" style="display:inline">
            <button type="submit" style="background:#10B981;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer">Clear Flag & Resume Agent</button>
        </form>"""
    elif invoice["status"] == "active":
        actions = f"""<form method="post" action="/invoices/{invoice_id}/pause" style="display:inline">
            <button type="submit" style="background:#F59E0B;color:#fff;border:none;padding:6px 16px;border-radius:4px;cursor:pointer">Pause Agent</button>
        </form>"""

    return HTMLResponse(_detail_html(
        invoice_number=invoice["invoice_number"],
        debtor_company=invoice["debtor_company"],
        sme_name=sme["company_name"] if sme else "Unknown",
        amount=f"{invoice['currency']} {invoice['amount']}",
        days_overdue=str(days_overdue),
        phase_badge=_phase_badge(invoice["current_phase"]),
        status_badge=_status_badge(invoice["status"]),
        contacts=contacts_html,
        timeline=timeline,
        actions=actions,
    ))


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
        # Reset to the phase it was in, or Phase 1 if disputed
        phase = invoice["current_phase"]
        if phase in ("human_review", "disputed"):
            phase = InvoicePhase.PHASE_1.value
        db.update_invoice(UUID(invoice_id), {
            "status": InvoiceStatus.ACTIVE.value,
            "current_phase": phase,
        })
    return RedirectResponse(f"/invoices/{invoice_id}", status_code=303)


@app.post("/upload-csv")
async def upload_csv(sme_id: str = Form(...), file: UploadFile = File(...)):
    db = _db()
    content = await file.read()
    result = import_csv(content, UUID(sme_id), db)
    # TODO: Flash message with result
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


# ---------------------------------------------------------------------------
# HTML templates (inline for MVP simplicity)
# ---------------------------------------------------------------------------

def _base_html(title: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — OaaS Collections Agent</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #F9FAFB; color: #111827; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        nav {{ background: #111827; color: #fff; padding: 12px 20px; }}
        nav a {{ color: #fff; text-decoration: none; margin-right: 20px; }}
        h1 {{ margin: 20px 0 10px; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #F3F4F6; text-align: left; padding: 10px 12px; font-size: 12px; text-transform: uppercase; color: #6B7280; }}
        td {{ padding: 10px 12px; border-top: 1px solid #E5E7EB; font-size: 14px; }}
        tr:hover {{ background: #F9FAFB; }}
        a {{ color: #3B82F6; }}
        .stats {{ display: flex; gap: 16px; margin: 16px 0; }}
        .stat {{ background: #fff; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .stat-value {{ font-size: 24px; font-weight: 700; }}
        .stat-label {{ font-size: 12px; color: #6B7280; text-transform: uppercase; }}
    </style>
</head>
<body>
    <nav>
        <a href="/"><strong>OaaS</strong> Collections Agent</a>
        <a href="/">Dashboard</a>
    </nav>
    <div class="container">
        {content}
    </div>
</body>
</html>"""


def _dashboard_html(rows: str, total: int, active: int, paused: int) -> str:
    return _base_html("Dashboard", f"""
        <h1>Invoice Dashboard</h1>
        <div class="stats">
            <div class="stat"><div class="stat-value">{total}</div><div class="stat-label">Total Invoices</div></div>
            <div class="stat"><div class="stat-value">{active}</div><div class="stat-label">Active</div></div>
            <div class="stat"><div class="stat-value">{paused}</div><div class="stat-label">Paused / Disputed</div></div>
        </div>
        <table>
            <thead><tr>
                <th>Invoice #</th><th>Debtor</th><th>SME</th><th>Amount</th><th>Overdue</th><th>Phase</th><th>Status</th>
            </tr></thead>
            <tbody>{rows if rows else '<tr><td colspan="7" style="text-align:center;padding:40px;color:#999">No invoices yet. Upload a CSV to get started.</td></tr>'}</tbody>
        </table>
    """)


def _detail_html(
    invoice_number: str,
    debtor_company: str,
    sme_name: str,
    amount: str,
    days_overdue: str,
    phase_badge: str,
    status_badge: str,
    contacts: str,
    timeline: str,
    actions: str,
) -> str:
    return _base_html(f"Invoice #{invoice_number}", f"""
        <h1>Invoice #{invoice_number} {phase_badge} {status_badge}</h1>
        <div class="stats">
            <div class="stat"><div class="stat-value">{amount}</div><div class="stat-label">Amount</div></div>
            <div class="stat"><div class="stat-value">{days_overdue}</div><div class="stat-label">Days Overdue</div></div>
            <div class="stat"><div class="stat-label">Debtor</div><div style="font-size:16px;font-weight:600">{debtor_company}</div></div>
            <div class="stat"><div class="stat-label">SME Client</div><div style="font-size:16px;font-weight:600">{sme_name}</div></div>
        </div>
        <div style="margin:16px 0">{actions}</div>
        <h2 style="margin:24px 0 8px">Contacts</h2>
        <ul style="margin-left:20px">{contacts}</ul>
        <h2 style="margin:24px 0 8px">Interaction Timeline</h2>
        {timeline}
        <p style="margin-top:24px"><a href="/">← Back to Dashboard</a></p>
    """)
