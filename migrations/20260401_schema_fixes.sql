-- Migration: Fix critical schema gaps
-- Date: 2026-04-01
-- Issues fixed: #1 (missing accounting_connections table), #2 (missing write_off_claimed enum values)

-- ============================================================================
-- Issue #1: Create accounting_connections table
-- The RLS policy references this table but it was never created
-- ============================================================================

CREATE TABLE IF NOT EXISTS accounting_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sme_id UUID NOT NULL REFERENCES smes(id) ON DELETE CASCADE,
    platform accounting_platform NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expires_at TIMESTAMPTZ NOT NULL,
    tenant_id TEXT NOT NULL DEFAULT '',
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_sync_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(sme_id, platform)
);

CREATE INDEX idx_accounting_connections_sme_id ON accounting_connections(sme_id);
CREATE INDEX idx_accounting_connections_platform ON accounting_connections(platform);
CREATE INDEX idx_accounting_connections_status ON accounting_connections(status) WHERE status = 'active';

-- Enable RLS on accounting_connections (referenced in 20260328_rls_policies.sql)
ALTER TABLE accounting_connections ENABLE ROW LEVEL SECURITY;

-- Service role bypass for backend processes
CREATE POLICY "Service role full access" ON accounting_connections FOR ALL USING (true) WITH CHECK (true);

-- ============================================================================
-- Issue #2: Add write_off_claimed to invoice_phase enum
-- Python model has InvoicePhase.WRITE_OFF_CLAIMED but SQL enum is missing it
-- ============================================================================

ALTER TYPE invoice_phase ADD VALUE IF NOT EXISTS 'write_off_claimed';

-- Add missing classification values to the classification enum
-- The enum currently has: promise_to_pay, payment_pending, dispute, redirect, stall, hostile, no_response
-- We need to add write_off_claimed (quickbooks_sync and xero_sync are also missing from contact_source)
ALTER TYPE classification ADD VALUE IF NOT EXISTS 'write_off_claimed';

-- Also add missing contact_source values
ALTER TYPE contact_source ADD VALUE IF NOT EXISTS 'xero_sync';
ALTER TYPE contact_source ADD VALUE IF NOT EXISTS 'quickbooks_sync';

-- ============================================================================
-- Enable RLS on email_domains and webhook_events tables
-- These are enabled in earlier migrations but have no policies
-- ============================================================================

ALTER TABLE email_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;

-- Policy: users can only see their own email domains (via sme_id join)
CREATE POLICY "email_domains_isolation_policy" ON email_domains
    FOR ALL
    USING (
        sme_id IN (SELECT id FROM smes WHERE id = auth.uid())
    );

-- Policy: service role bypass for webhook_events (processed by backend, not users)
CREATE POLICY "Service role full access" ON webhook_events FOR ALL USING (true) WITH CHECK (true);

-- ============================================================================
-- Verification queries (run these to confirm the migration succeeded)
-- ============================================================================

-- SELECT enumlabel FROM pg_enum WHERE enumtypid = 'invoice_phase'::regtype ORDER BY enumsortorder;
-- SELECT enumlabel FROM pg_enum WHERE enumtypid = 'classification'::regtype ORDER BY enumsortorder;
-- SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'accounting_connections') AS accounting_connections_exists;
