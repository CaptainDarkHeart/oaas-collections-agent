Project Context and Identity

Core Identity
AI powered collections agent that chases overdue invoices on behalf of SMEs using psychological escalation techniques (specifically Chris Voss tactical empathy). The agent operates across multiple channels (email, AI voice, LinkedIn DM) with a structured 21 day behavioral phase cycle enforced by phase_start_date based timing.

Business Model
Outcome only pricing with zero upfront cost to SMEs:

10% fee on invoices over GBP 5,000
GBP 500 flat fee for stalled invoices 60+ days overdue

Architecture: Three Brain Agentic Workflow

Sentry (src/sentry/) Integration brain. Monitors accounting software (Codat, Xero, QuickBooks, CSV). Identifies overdue invoices. Pulls contact metadata. Manages OAuth tokens. Processes webhooks with idempotency.

Strategist (src/strategist/) Psychological brain. LLM powered (Claude Sonnet 4). Manages phase state machine with phase_start_date based escalation. Classifies responses into 8 categories. Generates messages with tactical empathy prompts and post generation guardrails.

Executor (src/executor/) Multi channel brain. Sends emails (resend.com). Voice calls (Vapi/ElevenLabs). LinkedIn DMs. Handles variable cadence and custom sending domains.

Constraints. Do not use hashtags. Do not use semicolons. Do not use emojis. Do not use asterisks. Do not use dashes of any kind. Use standard numbered lists for organization.

Technical Stack and Tools

Python 3.11+ with Claude Sonnet 4 API, PostgreSQL (Supabase with Row Level Security), resend.com, Vapi/ElevenLabs, Codat, Stripe, FastAPI dashboard with JWT auth

AI Coordination. Claude 4.6 is the primary reasoning engine for architectural decisions. Gemini 3.1 Pro is the execution agent for code generation and research.

Database Security. PostgreSQL enforces tenant isolation through Row Level Security (RLS). Dashboard sessions use JWT tokens via Supabase anon key. Backend processes use the service role key. The RLS migration is at migrations/20260328_rls_policies.sql. All queries from the dashboard are scoped to the authenticated user.

Messaging Standards. All generated messaging must employ Chris Voss tactical empathy (late night FM DJ voice, calibrated questions, empathy mirrors, labelling, accusation audits). Semicolons and hyphens are strictly prohibited. Post generation regex guardrails enforce this in src/strategist/message_generator.py.

Gated Execution Protocols

Explain Mode. Enter this mode when analyzing existing code or researching APIs. Gemini must use Google Search to verify the latest documentation. It must summarize findings in plain text without excessive adjectives.

Plan Mode. Enter this mode when a new feature is requested. Gemini must first read the current CLAUDE.md file to understand the reasoning behind previous changes. It must generate a markdown implementation plan. The plan must be approved before execution.

Implement Mode. Enter this mode only after plan approval. Gemini must write clean and idiomatic code. It must ensure all copy is optimized for AI SEO and traditional SEO. It must verify that no semicolons are used in text files or documentation.

Review Mode. Use this mode to perform a peer review of code written by Claude agents. Check for logical consistency and adherence to the project style guide.

SEO and Content Standards

Optimization. All generated text must prioritize clarity and keyword relevance for both LLM indexers and traditional search engines.

Formatting. Use clear headings but do not overuse numbered lists. Ensure the document is scannable.

Accuracy. Verify all technical claims against the live web using the built in browser in Antigravity.

Current Status. Phase 2 complete. 276 tests passing.