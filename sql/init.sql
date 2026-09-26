-- ============================================
-- Financial Audio Intelligence — RAG Service
-- Database initialization script
-- Run this ONCE in your Supabase SQL Editor
-- ============================================

-- 1. Enable pgvector extension (required for embeddings)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Table: call_analyses
-- Stores each call as an independent risk event with RAG output.
CREATE TABLE IF NOT EXISTS call_analyses (
    call_id             TEXT PRIMARY KEY,
    call_timestamp      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    call_context        JSONB,
    speaker_analysis    JSONB,
    nlp_insights        JSONB,
    risk_signals        JSONB,
    risk_assessment     JSONB,
    summary_for_rag     TEXT,
    rag_output          JSONB,          -- NULL until Step 7 populates it
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Embedding of summary_for_rag for chatbot vector search
-- Stored during main pipeline after Step 3 (embed summary)
ALTER TABLE call_analyses
    ADD COLUMN IF NOT EXISTS summary_embedding vector(1536);

-- Index for time-based lookups
CREATE INDEX IF NOT EXISTS idx_call_analyses_timestamp
    ON call_analyses (call_timestamp DESC);

-- 3. Table: knowledge_embeddings
-- Curated knowledge base for fraud patterns, compliance rules, risk heuristics.
CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    doc_id          TEXT PRIMARY KEY,
    category        TEXT NOT NULL,       -- fraud_pattern | compliance | risk_heuristic
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(1536),        -- OpenAI text-embedding-3-small dimension
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Index for category-filtered queries
CREATE INDEX IF NOT EXISTS idx_knowledge_category
    ON knowledge_embeddings (category);

-- 4. RPC function for vector similarity search (used in Step 4)
-- This allows calling from Supabase client without raw SQL.
CREATE OR REPLACE FUNCTION match_knowledge(
    query_embedding vector(1536),
    match_category TEXT,
    match_limit INT DEFAULT 3
)
RETURNS TABLE (
    doc_id TEXT,
    category TEXT,
    title TEXT,
    content TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        ke.doc_id,
        ke.category,
        ke.title,
        ke.content,
        1 - (ke.embedding <=> query_embedding) AS similarity
    FROM knowledge_embeddings ke
    WHERE ke.category = match_category
    ORDER BY ke.embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;


-- 5. RPC function for chatbot vector search against call_analyses
-- Searches past calls by cosine similarity on summary_embedding
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
