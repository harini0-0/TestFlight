CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS compiler;
CREATE SCHEMA IF NOT EXISTS control;
CREATE SCHEMA IF NOT EXISTS investigator;
CREATE SCHEMA IF NOT EXISTS actions;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS gateway;
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE IF EXISTS ingestion_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS control_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS control_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS audit_events ENABLE ROW LEVEL SECURITY;

-- Application role sets glasswing.tenant_id per request.
DROP POLICY IF EXISTS tenant_isolation_documents ON ingestion_documents;
CREATE POLICY tenant_isolation_documents ON ingestion_documents
  USING (tenant_id = current_setting('glasswing.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_bundles ON control_bundles;
CREATE POLICY tenant_isolation_bundles ON control_bundles
  USING (tenant_id = current_setting('glasswing.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_findings ON control_findings;
CREATE POLICY tenant_isolation_findings ON control_findings
  USING (tenant_id = current_setting('glasswing.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation_audit ON audit_events;
CREATE POLICY tenant_isolation_audit ON audit_events
  USING (tenant_id = current_setting('glasswing.tenant_id', true));
