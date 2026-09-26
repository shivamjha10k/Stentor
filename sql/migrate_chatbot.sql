-- =============================================
-- MIGRATION: Add chatbot vector search support
-- Run this in Supabase SQL Editor
-- =============================================

-- 1. Add summary_embedding column to call_analyses
ALTER TABLE call_analyses
    ADD COLUMN IF NOT EXISTS summary_embedding vector(1536);

-- 2. RPC function for chatbot vector search against call_analyses
CREATE OR REPLACE FUNCTION match_calls(
    query_embedding vector(1536),
    match_limit INT DEFAULT 3
)
RETURNS TABLE (
    call_id TEXT,
    call_timestamp TIMESTAMPTZ,
    summary_for_rag TEXT,
    risk_score INT,
    fraud_likelihood TEXT,
    grounded_assessment TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ca.call_id,
        ca.call_timestamp,
        ca.summary_for_rag,
        (ca.risk_assessment->>'risk_score')::INT,
        ca.risk_assessment->>'fraud_likelihood',
        ca.rag_output->>'grounded_assessment',
        1 - (ca.summary_embedding <=> query_embedding) AS similarity
    FROM call_analyses ca
    WHERE ca.rag_output IS NOT NULL
      AND ca.summary_embedding IS NOT NULL
    ORDER BY ca.summary_embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;
