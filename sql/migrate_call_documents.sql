-- ============================================
-- Call Document Extraction — Migration
-- Creates call_documents table + RPC functions
-- Run this in your Supabase SQL Editor
-- ============================================

-- 1. Table: call_documents
-- Stores the extracted + curated document for each analyzed call
CREATE TABLE IF NOT EXISTS call_documents (
    doc_id              TEXT PRIMARY KEY,
    call_id             TEXT NOT NULL REFERENCES call_analyses(call_id),
    generated_at        TIMESTAMPTZ DEFAULT NOW(),

    -- Financial data extracted from transcript
    financial_data      JSONB NOT NULL DEFAULT '{}',

    -- Key entities (persons, orgs, dates, etc.)
    entities            JSONB NOT NULL DEFAULT '{}',

    -- Commitments & promises made during the call
    commitments         JSONB NOT NULL DEFAULT '[]',

    -- Human-readable narrative summary
    call_summary        TEXT NOT NULL,

    -- Classification
    call_purpose        TEXT,
    call_outcome        TEXT,

    -- Bullet-point discussion highlights
    key_discussion_points JSONB DEFAULT '[]',

    -- Compliance & risk
    compliance_notes    JSONB DEFAULT '[]',
    risk_flags          JSONB DEFAULT '[]',
    action_items        JSONB DEFAULT '[]',

    -- Chronological event timeline
    call_timeline       JSONB DEFAULT '[]',

    -- Extraction metadata
    extraction_model    TEXT DEFAULT 'gpt-4o-mini',
    extraction_tokens   INT DEFAULT 0,
    extraction_version  TEXT DEFAULT 'v1',

    -- Vector embedding for semantic search across documents
    doc_embedding       vector(1536),

    UNIQUE(call_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_call_documents_call_id
    ON call_documents(call_id);

CREATE INDEX IF NOT EXISTS idx_call_documents_generated_at
    ON call_documents(generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_call_documents_purpose
    ON call_documents(call_purpose);

CREATE INDEX IF NOT EXISTS idx_call_documents_outcome
    ON call_documents(call_outcome);


-- 2. RPC: Semantic search across call documents
CREATE OR REPLACE FUNCTION match_call_documents(
    query_embedding vector(1536),
    match_limit INT DEFAULT 5
)
RETURNS TABLE (
    doc_id TEXT,
    call_id TEXT,
    call_summary TEXT,
    call_purpose TEXT,
    call_outcome TEXT,
    financial_data JSONB,
    entities JSONB,
    commitments JSONB,
    key_discussion_points JSONB,
    action_items JSONB,
    generated_at TIMESTAMPTZ,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cd.doc_id,
        cd.call_id,
        cd.call_summary,
        cd.call_purpose,
        cd.call_outcome,
        cd.financial_data,
        cd.entities,
        cd.commitments,
        cd.key_discussion_points,
        cd.action_items,
        cd.generated_at,
        1 - (cd.doc_embedding <=> query_embedding) AS similarity
    FROM call_documents cd
    WHERE cd.doc_embedding IS NOT NULL
    ORDER BY cd.doc_embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;


-- 3. RPC: Aggregated financial summary across recent calls
CREATE OR REPLACE FUNCTION financial_summary(days_back INT DEFAULT 30)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT jsonb_build_object(
        'documents_generated', COUNT(*),
        'total_payment_commitments', COALESCE(
            SUM(
                (SELECT COALESCE(SUM((elem->>'amount')::NUMERIC), 0)
                 FROM jsonb_array_elements(cd.financial_data->'payment_commitments') AS elem)
            ), 0
        ),
        'avg_outstanding', COALESCE(
            AVG((cd.financial_data->>'total_outstanding')::NUMERIC), 0
        ),
        'purpose_breakdown', (
            SELECT jsonb_object_agg(purpose, cnt)
            FROM (
                SELECT cd2.call_purpose AS purpose, COUNT(*) AS cnt
                FROM call_documents cd2
                WHERE cd2.generated_at >= NOW() - (days_back || ' days')::INTERVAL
                  AND cd2.call_purpose IS NOT NULL
                GROUP BY cd2.call_purpose
            ) sub
        ),
        'outcome_breakdown', (
            SELECT jsonb_object_agg(outcome, cnt)
            FROM (
                SELECT cd3.call_outcome AS outcome, COUNT(*) AS cnt
                FROM call_documents cd3
                WHERE cd3.generated_at >= NOW() - (days_back || ' days')::INTERVAL
                  AND cd3.call_outcome IS NOT NULL
                GROUP BY cd3.call_outcome
            ) sub
        )
    ) INTO result
    FROM call_documents cd
    WHERE cd.generated_at >= NOW() - (days_back || ' days')::INTERVAL;

    RETURN COALESCE(result, '{}'::JSONB);
END;
$$;
