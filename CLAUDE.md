# OaaS Collections Agent

## Project Overview

AI-powered collections agent that chases overdue invoices on behalf of SMEs using psychological escalation techniques (Chris Voss tactical empathy). Operates across email, AI voice, and LinkedIn DM with four behavioural phases over a 21+ day cycle.

Business model: outcome-only pricing. 10% fee on invoices over GBP 5,000, or GBP 500 flat fee for stalled invoices 60+ days overdue. Zero upfront cost to the SME.

## Architecture

Three-brain agentic workflow:
- **Sentry** (`src/sentry/`) — Integration brain. Monitors accounting software (Codat/CSV), identifies overdue invoices, pulls contact metadata.
- **Strategist** (`src/strategist/`) — Psychological brain. LLM-powered (Claude Sonnet 4). Manages phase state machine, classifies responses, generates messages.
- **Executor** (`src/executor/`) — Multi-channel brain. Sends emails (Instantly.ai), voice calls (Vapi/ElevenLabs), LinkedIn DMs. Handles variable cadence.

## Tech Stack

- **Language:** Python 3.11+
- **LLM:** Claude Sonnet 4 via Anthropic API
- **Database:** PostgreSQL via Supabase
- **Email:** Instantly.ai
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

## Current Status

Phase 1 MVP (pre-implementation). File structure and config scaffolded. Next: implement components in this order:
1. CSV importer
2. Database models
3. State machine
4. Response classifier
5. Message generator
6. Email sender (Instantly.ai)
7. Cadence engine
8. Main loop / scheduler
