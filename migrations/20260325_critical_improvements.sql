-- Phase 2.1: Critical Improvements
-- Implements: payment link caching, webhook idempotency, external_id tracking
-- Date: 2026-03-25

-- ============================================================================
-- 1. Payment link caching on invoices
-- ============================================================================

ALTER TABLE invoices ADD COLUMN payment_link_url TEXT;
ALTER TABLE invoices ADD COLUMN payment_link_id TEXT;

CREATE INDEX idx_invoices_payment_link_url ON invoices(payment_link_url) WHERE payment_link_url IS NOT NULL;

-- ============================================================================
-- 2. External ID tracking (for accounting software write-back)
-- ============================================================================

ALTER TABLE invoices ADD COLUMN external_id TEXT;

CREATE INDEX idx_invoices_external_id ON invoices(external_id) WHERE external_id IS NOT NULL;

-- ============================================================================
-- 3. Webhook event idempotency tracking
-- ============================================================================

CREATE TABLE webhook_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,  -- 'stripe', 'codat', etc.
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_webhook_events_event_id ON webhook_events(event_id);
CREATE INDEX idx_webhook_events_processed_at ON webhook_events(processed_at);

-- Clean up old webhook events after 30 days (optional, can be done via job)
-- For now, events are kept indefinitely for audit trail

-- ============================================================================
-- 4. Add RLS policies for webhook_events (if using RLS)
-- ============================================================================

-- Note: If you use RLS, add policies here. Example:
-- ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "Service role can manage webhook events" ON webhook_events
--   USING (auth.role() = 'authenticated' OR auth.role() = 'service_role');

-- ============================================================================
-- Verification
-- ============================================================================

-- Verify columns exist:
-- SELECT column_name FROM information_schema.columns WHERE table_name = 'invoices' AND column_name IN ('payment_link_url', 'payment_link_id', 'external_id');
-- SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'webhook_events') AS webhook_events_exists;
