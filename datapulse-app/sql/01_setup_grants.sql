-- Run once as a catalog owner or metastore admin, before or after the first deploy.
-- Replace <app-service-principal> with the app's service principal application ID
-- (Compute > Apps > datapulse > Authorization), and main/datapulse if you changed them in app.yaml.

CREATE SCHEMA IF NOT EXISTS main.datapulse COMMENT 'DataPulse assessment data';

GRANT USE CATALOG ON CATALOG main TO `<app-service-principal>`;
GRANT USE SCHEMA, CREATE TABLE, SELECT, MODIFY ON SCHEMA main.datapulse TO `<app-service-principal>`;

-- Analysts who build portfolio dashboards only need read access:
-- GRANT USE CATALOG ON CATALOG main TO `data-leaders`;
-- GRANT USE SCHEMA, SELECT ON SCHEMA main.datapulse TO `data-leaders`;
