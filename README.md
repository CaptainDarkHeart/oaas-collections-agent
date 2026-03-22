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
| Email | Instantly.ai |
| Voice | Vapi + ElevenLabs |
| Accounting API | Codat / CSV upload |
| Payments | Stripe |
| Database | PostgreSQL (Supabase) |
| Config | pydantic-settings |

## Project Structure

```
src/
  config.py                  # Settings via pydantic-settings
  main.py                    # Entry point
  sentry/                    # Integration Brain (Codat, CSV, webhooks)
  strategist/                # Psychological Brain (state machine, classifier, prompts)
  executor/                  # Multi-Channel Brain (email, voice, LinkedIn, cadence)
  billing/                   # Fee calculation and Stripe billing
  db/                        # Database models and migrations
  notifications/             # Slack and email alerts
tests/
scripts/
```

## Status

Pre-MVP — project foundation scaffolded, implementation pending.
