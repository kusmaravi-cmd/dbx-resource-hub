-- Hub Concierge schema in Lakebase. {schema} and {dim} are substituted by infra/load_catalog.py.
-- Lakebase Search extensions must exist before the vector column.
CREATE EXTENSION IF NOT EXISTS lakebase_tokenizer CASCADE;
CREATE EXTENSION IF NOT EXISTS lakebase_vector CASCADE;
CREATE EXTENSION IF NOT EXISTS lakebase_text CASCADE;

CREATE SCHEMA IF NOT EXISTS {schema};

-- One row per Resource Hub entry (docs, repos, launches, videos, demos, ...).
CREATE TABLE IF NOT EXISTS {schema}.resources (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    summary      TEXT,
    url          TEXT NOT NULL,
    kind         TEXT NOT NULL,
    topic        TEXT NOT NULL,
    area         TEXT,
    status       TEXT,
    released_on  DATE,
    content      TEXT NOT NULL,
    embedding    vector({dim}),
    content_tsv  tsvector,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS resources_kind_topic ON {schema}.resources (kind, topic);
CREATE INDEX IF NOT EXISTS resources_released ON {schema}.resources (released_on DESC) WHERE kind = 'Launch';

-- Per-user shortlist the agent writes to ("save that one for me"). user_key is the Databricks
-- Apps user (X-Forwarded-Email), carried in the LiveKit token metadata.
CREATE TABLE IF NOT EXISTS {schema}.shortlist (
    user_key     TEXT NOT NULL,
    resource_id  TEXT NOT NULL REFERENCES {schema}.resources (id) ON DELETE CASCADE,
    note         TEXT,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_key, resource_id)
);

-- Lakebase Search indexes: ANN (cosine) for semantic, BM25 for keywords.
CREATE INDEX IF NOT EXISTS resources_ann ON {schema}.resources USING lakebase_ann (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS resources_bm25 ON {schema}.resources USING lakebase_bm25 (content_tsv);
