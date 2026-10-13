-- Portfolio views over every assessment, for AI/BI dashboards or Genie.
-- The app rewrites the flattened tables after each save, so they always hold the latest version.

CREATE OR REPLACE VIEW main.datapulse.v_assessment_readiness AS
SELECT a.assessment_id, a.name, a.org, a.mode, a.version, a.updated_at, a.updated_by,
       min(CASE WHEN s.dimension IN ('R1','R2','R3','R4','R5','R6') AND NOT s.provisional THEN s.enforced END) AS readiness_ceiling,
       min(CASE WHEN s.dimension IN ('R1','R2','R3','R4','R5','R6') AND NOT s.provisional THEN s.evidence_backed END) AS ceiling_evidence_backed,
       avg(CASE WHEN s.tier = 'T3' AND NOT s.provisional THEN s.enforced END) AS execution_score,
       sum(CASE WHEN s.claimed - s.enforced >= 0.5 THEN 1 ELSE 0 END) AS inflated_dimensions
FROM main.datapulse.assessments a
JOIN main.datapulse.dimension_scores s USING (assessment_id)
WHERE NOT coalesce(a.deleted, false)
GROUP BY ALL;

CREATE OR REPLACE VIEW main.datapulse.v_binding_constraints AS
SELECT s.assessment_id, s.dimension, s.dimension_name, s.enforced
FROM main.datapulse.dimension_scores s
JOIN main.datapulse.v_assessment_readiness r USING (assessment_id)
WHERE s.dimension IN ('R1','R2','R3','R4','R5','R6') AND NOT s.provisional
  AND s.enforced - r.readiness_ceiling < 0.05;

CREATE OR REPLACE VIEW main.datapulse.v_lever_enforcement AS
SELECT a.org, a.name AS assessment, l.*
FROM main.datapulse.lever_plan l
JOIN main.datapulse.assessments a USING (assessment_id)
WHERE NOT coalesce(a.deleted, false);

CREATE OR REPLACE VIEW main.datapulse.v_blocked_use_cases AS
SELECT a.org, a.name AS assessment, u.use_case, u.domain, u.job, u.status, u.readiness,
       from_json(u.blocking, 'ARRAY<STRING>') AS blocking_dimensions,
       from_json(u.gate_missing, 'ARRAY<STRING>') AS missing_levers
FROM main.datapulse.use_case_readiness u
JOIN main.datapulse.assessments a USING (assessment_id)
WHERE u.status <> 'Go' AND NOT coalesce(a.deleted, false);
