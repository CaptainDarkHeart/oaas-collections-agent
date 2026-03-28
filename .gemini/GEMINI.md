Project Context and Identity
Core Identity
AI-powered collections agent that chases overdue invoices on behalf of SMEs using psychological escalation techniques (specifically Chris Voss tactical empathy). The agent operates across multiple channels (email, AI voice, LinkedIn DM) with a structured 21+ day behavioral phase cycle.

Business Model
Outcome-only pricing — zero upfront cost to SMEs:

10% fee on invoices over GBP 5,000
GBP 500 flat fee for stalled invoices 60+ days overdue
Architecture: Three-Brain Agentic Workflow
Sentry (src/sentry/) — Integration brain

Monitors accounting software (Codat/CSV)
Identifies overdue invoices
Pulls contact metadata
Strategist (src/strategist/) — Psychological brain

LLM-powered (Claude Sonnet 4)
Manages phase state machine
Classifies responses & generates messages
Executor (src/executor/) — Multi-channel brain

Sends emails (resend.com)
Voice calls (Vapi/ElevenLabs)
LinkedIn DMs
Handles variable cadence

Constraints. Do not use hashtags. Do not use semicolons. Do not use emojis. Do not use asterisks. Do not use dashes of any kind. Use standard numbered lists for organization.

Technical Stack and Tools

Python 3.11+ · Claude Sonnet 4 API · PostgreSQL (Supabase) · resend.com · Vapi/ElevenLabs · Codat · Stripe

AI Coordination. Claude 4.6 is the primary reasoning engine for architectural decisions. Gemini 3.1 Pro is the execution agent for code generation and research.

Database. Firestore via the Firebase Studio integration.

Gated Execution Protocols
Explain Mode. Enter this mode when analyzing existing code or researching APIs. Gemini must use Google Search to verify the latest documentation. It must summarize findings in plain text without excessive adjectives.

Plan Mode. Enter this mode when a new feature is requested. Gemini must first read the current CLAUDE.md file to understand the reasoning behind previous changes. It must generate a markdown implementation plan. The plan must be approved before execution.

Implement Mode. Enter this mode only after plan approval. Gemini must write clean and idiomatic code. It must ensure all copy is optimized for AI SEO and traditional SEO. It must verify that no semicolons are used in text files or documentation.

Review Mode. Use this mode to perform a peer review of code written by Claude agents. Check for logical consistency and adherence to the photography startup style guide.

SEO and Content Standards
Optimization. All generated text must prioritize clarity and keyword relevance for both LLM indexers and traditional search engines.

Formatting. Use clear headings but do not over use numbered lists. Ensure the document is scannable.

Accuracy. Verify all technical claims against the live web using the built in browser in Antigravity.