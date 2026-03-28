/* Enable RLS on all relevant tables */
ALTER TABLE smes ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE interactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE fees ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounting_connections ENABLE ROW LEVEL SECURITY;

/* Drop any existing permissive policies */
DROP POLICY IF EXISTS "Enable read access for all users" ON smes;
DROP POLICY IF EXISTS "Enable insert for all users" ON smes;
DROP POLICY IF EXISTS "Enable read access for all users" ON invoices;
DROP POLICY IF EXISTS "Enable insert for all users" ON invoices;

/* Create policies based on authenticated user matching the sme identifier */
CREATE POLICY "smes_isolation_policy" ON smes
    FOR ALL
    USING (id = auth.uid());

CREATE POLICY "invoices_isolation_policy" ON invoices
    FOR ALL
    USING (sme_id = auth.uid());

CREATE POLICY "contacts_isolation_policy" ON contacts
    FOR ALL
    USING (invoice_id IN (SELECT id FROM invoices WHERE sme_id = auth.uid()));

CREATE POLICY "interactions_isolation_policy" ON interactions
    FOR ALL
    USING (invoice_id IN (SELECT id FROM invoices WHERE sme_id = auth.uid()));

CREATE POLICY "fees_isolation_policy" ON fees
    FOR ALL
    USING (sme_id = auth.uid());

CREATE POLICY "accounting_connections_isolation_policy" ON accounting_connections
    FOR ALL
    USING (sme_id = auth.uid());
