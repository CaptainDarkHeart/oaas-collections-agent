-- Per-SME custom email domain configuration
-- Stores Resend domain registrations and DNS records for customer email sending

CREATE TABLE email_domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sme_id UUID NOT NULL REFERENCES smes(id),
    domain_name TEXT NOT NULL,
    resend_domain_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'not_started',
    sending_email TEXT,
    dns_records JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT now(),
    verified_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    UNIQUE(sme_id)
);

CREATE INDEX idx_email_domains_sme_id ON email_domains(sme_id);
CREATE INDEX idx_email_domains_status ON email_domains(status);
