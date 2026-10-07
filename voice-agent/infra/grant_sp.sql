-- Service-principal mode only (deploy.py --auth sp). Run in the Lakebase SQL editor as the database owner.
-- Replace <sp-client-id> with the app's service_principal_client_id (`databricks apps get hub-concierge`).
-- PAT mode needs none of this: the app runs as the PAT's user, who loaded the data.
CREATE EXTENSION IF NOT EXISTS databricks_auth;
SELECT databricks_create_role('<sp-client-id>', 'SERVICE_PRINCIPAL');
GRANT USAGE ON SCHEMA hub TO "<sp-client-id>";
GRANT SELECT ON hub.resources TO "<sp-client-id>";
GRANT SELECT, INSERT, UPDATE, DELETE ON hub.shortlist TO "<sp-client-id>";
