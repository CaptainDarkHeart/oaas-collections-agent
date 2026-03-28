# OaaS Collections Agent

## Project Overview

AI-powered collections agent that chases overdue invoices on behalf of SMEs using psychological escalation techniques (Chris Voss tactical empathy). Operates across email, AI voice, and LinkedIn DM with four behavioural phases over a 21+ day cycle.

Business model: outcome-only pricing. 10% fee on invoices over GBP 5,000, or GBP 500 flat fee for stalled invoices 60+ days overdue. Zero upfront cost to the SME.

## Architecture

Three-brain agentic workflow:
- **Sentry** (`src/sentry/`) — Integration brain. Monitors accounting software (Codat/CSV), identifies overdue invoices, pulls contact metadata.
- **Strategist** (`src/strategist/`) — Psychological brain. LLM-powered (Claude Sonnet 4). Manages phase state machine, classifies responses, generates messages.
- **Executor** (`src/executor/`) — Multi-channel brain. Sends emails (Resend), voice calls (Vapi/ElevenLabs), LinkedIn DMs. Handles variable cadence.

## Tech Stack

- **Language:** Python 3.11+
- **LLM:** Claude Sonnet 4 via Anthropic API
- **Database:** PostgreSQL via Supabase
- **Email:** Resend
- **Voice:** Vapi + ElevenLabs
- **Accounting API:** Codat (MVP), Nango (Phase 3 evaluation)
- **Payments:** Stripe
- **Config:** pydantic-settings with .env

## Key Constraints

- Agent must NEVER hallucinate discounts, payment terms, or legal threats
- Discount offers gated by `discount_authorised` boolean + phase-specific limits (see `src/strategist/constraints.py`)
- On DISPUTE or HOSTILE classification, agent pauses immediately — human must clear flag
- Phase 4 language is templated, not LLM-generated, to eliminate hallucination risk
- "External compliance partner" is the strongest language permitted — never threaten legal action
- Variable send cadence — never look automated, never contact same person twice in one day
- Max 30 cold emails per day per inbox

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Fill in API keys
pytest
```

## Running

```bash
# Run tests
pytest

# Run daily processing cycle
python -m scripts.run_daily_sync

# Seed test data
python -m scripts.seed_test_data

# Start dashboard
uvicorn src.dashboard.app:app --reload --port 8000
```

## Current Status

Phase 1 MVP implemented. All core components built and tested (69 tests passing).

Next steps (Phase 2): Vapi voice integration, Codat accounting API, Stripe payment links, write-back to accounting software.
