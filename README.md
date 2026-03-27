# OaaS Collections Agent

AI-powered collections agent that recovers overdue invoices for SMEs using psychological escalation techniques.

## How It Works

The agent deploys a 4-phase escalation sequence over 21+ days, using tactical empathy (Chris Voss methodology) to move invoices to the top of the "to-pay" pile:

1. **Phase 1 — Helpful Project Liaison** (Days 1-5): Friendly check-in, assumes technical error
2. **Phase 2 — Internal Advocate** (Days 7-10): Positions as ally against bureaucracy, introduces "finance lead" pressure
3. **Phase 3 — Loss Aversion Pivot** (Days 14-17): Introduces consequences (priority loss, scheduling slots)
4. **Phase 4 — Regulatory/Formal Shift** (Day 21+): Cold AP-style professional tone, compliance language

Channels escalate from email-only to voice calls to LinkedIn DMs.

## Business Model

**Outcome-only pricing.** The SME pays nothing upfront.
- 10% fee on recovered invoices over GBP 5,000
- GBP 500 flat fee for stalled invoices 60+ days overdue
- If nothing is recovered, the SME pays nothing

Fee attribution: if payment is received after first agent contact (regardless of payment method), the fee applies. This is enforced both contractually and via `first_contacted_at` tracking in the database.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Fill in your API keys
pytest
```

## Tech Stack

| Component | Tool |
|---|---|
| LLM | Claude Sonnet 4 (Anthropic API) |
| Email | Resend (transactional) + Instantly.ai (campaigns) |
| Voice | Vapi + ElevenLabs |
| Accounting API | Codat, Xero (OAuth), QuickBooks (OAuth), CSV upload |
| Payments | Stripe (debtor payment links + SME fee billing) |
| Database | PostgreSQL (Supabase) |
| Config | pydantic-settings |

## Project Structure

```
src/
  config.py                  # Settings via pydantic-settings
  main.py                    # Daily cycle orchestrator
  sentry/                    # Integration Brain
    invoice_sync.py          # Codat + OAuth sync, external payment detection
    xero_client.py           # Xero API client
    quickbooks_client.py     # QuickBooks API client
    webhook_handler.py       # Codat + Stripe webhook handlers
    write_back.py            # Write payments back to accounting software
    oauth.py                 # Token encryption and refresh
  strategist/                # Psychological Brain
    state_machine.py         # Phase transitions
    response_classifier.py   # LLM-based reply classification
    message_generator.py     # LLM-based message generation
    constraints.py           # Discount and language guardrails
  executor/                  # Multi-Channel Brain
    email_sender.py          # Resend email sending
    payment_link.py          # Stripe payment link creation
    cadence.py               # Variable send timing
    domain_manager.py        # Custom sending domain setup
  billing/                   # Fee calculation and Stripe billing
    fee_calculator.py        # 10% / £500 fee logic
    stripe_billing.py        # SME fee checkout sessions
  db/                        # Database models
    models.py                # Pydantic models + Supabase client
  notifications/             # Slack and email alerts
tests/
scripts/
  run_daily_sync.py          # Cron entry point
  seed_test_data.py          # Seed database with test invoices
```

## Payment Detection

The system detects payments via three paths:

1. **Stripe payment link** — debtor pays via link we send; webhook fires immediately, fee created
2. **Codat sync** — daily pull from accounting platform detects `status == "Paid"`
3. **OAuth direct check** — during each sync, active invoices with `external_id` are queried directly in Xero/QuickBooks

In all cases, a fee is created only if `first_contacted_at` is set (i.e. the agent actually contacted the debtor). If no prior contact, payment is marked resolved with no fee charged.

## Safety Guardrails

- Agent never hallucinate discounts or legal threats
- Discount offers gated by `discount_authorised` flag + per-SME `max_discount_percent`
- DISPUTE or HOSTILE classifications pause the agent immediately — human must clear before re-engagement
- Phase 4 uses templated language only (no LLM generation)
- "External compliance partner" is the strongest language permitted
- Variable cadence — never looks automated, never contacts same person twice in one day
- Max 30 cold emails per day per inbox

## Disconnect Protection

If an SME disconnects their accounting integration while contacted invoices are still active, a Slack alert fires immediately. This prevents the exploit where an SME collects payment and removes our visibility before the daily sync runs.

## Status

Phase 1 MVP complete. 84+ tests passing.

**Phase 2 (next):** Vapi voice integration, Stripe payment link write-back, deeper Codat webhook handling.
