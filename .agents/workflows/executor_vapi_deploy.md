---
description: Executor Vapi Deployment Workflow
---
# Executor Vapi Deployment Workflow

// turbo
1. Authenticate Vapi CLI
Run `vapi login` using the `VAPI_API_KEY` environment variable. This step establishes access to the voice orchestration platform.

2. Load Configuration
Gemini 3.1 Flash reads the `src/executor/vapi_config.json` file. It prepares the deployment payload containing the Chris Voss tactical empathy instructions and the ElevenLabs voice profile.

// turbo
3. Provision Assistant
Execute `vapi assistant create` using the local JSON configuration. The command returns a unique assistant ID for the collections agent.

// turbo
4. Database Registration
Run the Python script at `src/executor/register_assistant.py`. This script saves the new assistant ID to the `assistant_registry` table in Supabase. This ensures the Strategist brain can reference the correct agent during the 21 day behavioral cycle.

// turbo
5. Integration Verification
Initiate a test call to a verified sandbox number using `vapi call start`. This verifies the connection between the LLM and the voice provider.

6. Performance Audit
The Executor brain reviews the call logs to confirm low latency and script accuracy. It flags any deviations from the psychological escalation plan.
