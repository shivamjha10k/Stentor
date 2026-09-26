"""
Database query functions for the RAG service.
All Supabase table operations live here.
"""

import logging
from app.db.supabase_client import get_supabase_client

logger = logging.getLogger("rag.queries")


# ============================================================
# call_analyses table operations
# ============================================================

def insert_call_record(
    call_id: str,
    call_timestamp: str,
    call_context: dict,
    speaker_analysis: dict,
    nlp_insights: dict,
    risk_signals: dict,
    risk_assessment: dict,
    summary_for_rag: str,
    conversation: list[dict] | None = None,
    call_language: str | None = None,
) -> dict:
    """
    Insert a new call record into call_analyses.
    rag_output is left NULL — populated later in Step 7 by updater.py.

    Returns: {"inserted": True, "call_id": "...", "table": "call_analyses"}
    Raises: Exception if Supabase insert fails.
    """
    client = get_supabase_client()

    row = {
        "call_id": call_id,
        "call_timestamp": call_timestamp,
        "call_context": call_context,
        "speaker_analysis": speaker_analysis,
        "nlp_insights": nlp_insights,
        "risk_signals": risk_signals,
        "risk_assessment": risk_assessment,
        "summary_for_rag": summary_for_rag,
        "conversation": conversation or [],
        "call_language": call_language or "unknown",
        # rag_output intentionally omitted — NULL until Step 7
    }

    logger.info(f"DB INSERT call_analyses ({call_id})")
    result = client.table("call_analyses").insert(row).execute()

    if not result.data:
        raise RuntimeError(f"Supabase insert returned no data for call_id={call_id}")

    return {
        "inserted": True,
        "call_id": call_id,
        "table": "call_analyses",
    }


def get_call_by_id(call_id: str) -> dict | None:
    """
    Fetch a single call record by call_id.
    Returns the row as a dict, or None if not found.
    """
    client = get_supabase_client()

    result = (
        client.table("call_analyses")
        .select("*")
        .eq("call_id", call_id)
        .execute()
    )

    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def update_rag_output(call_id: str, rag_output: dict) -> dict:
    """
    Update the rag_output column for an existing call record (Step 7).
    Returns: {"updated": True, "call_id": "...", "table": "call_analyses", "field": "rag_output"}
    """
    client = get_supabase_client()

    result = (
        client.table("call_analyses")
        .update({"rag_output": rag_output})
        .eq("call_id", call_id)
        .execute()
    )

    if not result.data:
        raise RuntimeError(f"Supabase update returned no data for call_id={call_id}")

    return {
        "updated": True,
        "call_id": call_id,
        "table": "call_analyses",
        "field": "rag_output",
    }


# ============================================================
# knowledge_embeddings table operations
# ============================================================

def search_knowledge(
    query_embedding: list[float],
    category: str,
    limit: int = 3,
) -> list[dict]:
    """
    Perform vector similarity search against knowledge_embeddings
    using the match_knowledge RPC function defined in init.sql.

    Args:
        query_embedding: 1536-dim query vector from Step 3.
        category: One of 'fraud_pattern', 'compliance', 'risk_heuristic'.
        limit: Max number of results to return.

    Returns:
        List of dicts with doc_id, title, content, similarity.
    """
    client = get_supabase_client()

    logger.info(f"DB RPC match_knowledge (category={category}, limit={limit})")
    result = client.rpc(
        "match_knowledge",
        {
            "query_embedding": query_embedding,
            "match_category": category,
            "match_limit": limit,
        },
    ).execute()

    if not result.data:
        return []

    return result.data


def upsert_knowledge_doc(
    doc_id: str,
    category: str,
    title: str,
    content: str,
    embedding: list[float],
    metadata: dict | None = None,
) -> dict:
    """
    Insert or update a knowledge document with its embedding.
    Used during knowledge base seeding.

    Returns: {"upserted": True, "doc_id": "...", "table": "knowledge_embeddings"}
    """
    client = get_supabase_client()

    row = {
        "doc_id": doc_id,
        "category": category,
        "title": title,
        "content": content,
        "embedding": embedding,
        "metadata": metadata or {},
    }

    result = (
        client.table("knowledge_embeddings")
        .upsert(row)
        .execute()
    )

    if not result.data:
        raise RuntimeError(f"Supabase upsert failed for doc_id={doc_id}")

    return {
        "upserted": True,
        "doc_id": doc_id,
        "table": "knowledge_embeddings",
    }


def get_knowledge_count() -> int:
    """Return total number of documents in knowledge_embeddings."""
    client = get_supabase_client()
    result = client.table("knowledge_embeddings").select("doc_id", count="exact").execute()
    return result.count or 0


# ============================================================
# chat operations (chatbot vector search)
# ============================================================

def update_call_embedding(call_id: str, embedding: list[float]) -> None:
    """
    Store the summary_for_rag embedding in call_analyses.
    Called after Step 3 of the main pipeline so chatbot can vector-search calls.
    """
    client = get_supabase_client()
    logger.info(f"DB UPDATE summary_embedding ({call_id})")
    client.table("call_analyses").update(
        {"summary_embedding": embedding}
    ).eq("call_id", call_id).execute()


def search_calls(
    query_embedding: list[float],
    limit: int = 3,
) -> list[dict]:
    """
    Vector similarity search against call_analyses via match_calls RPC.
    Returns past calls ranked by semantic similarity to the query.
    """
    client = get_supabase_client()
    logger.info(f"DB RPC match_calls (limit={limit})")
    result = client.rpc(
        "match_calls",
        {
            "query_embedding": query_embedding,
            "match_limit": limit,
        },
    ).execute()
    return result.data if result.data else []


# ============================================================
# dashboard operations
# ============================================================

def get_dashboard_stats() -> dict:
    """Call dashboard_stats() RPC — returns all KPI numbers."""
    client = get_supabase_client()
    logger.info("DB RPC dashboard_stats")
    result = client.rpc("dashboard_stats", {}).execute()
    return result.data if result.data else {}


def get_recent_activity(limit: int = 5) -> list[dict]:
    """Fetch last N completed calls for the activity timeline."""
    client = get_supabase_client()
    logger.info(f"DB SELECT recent_activity (limit={limit})")
    result = (
        client.table("call_analyses")
        .select("call_id, call_timestamp, status, summary_for_rag, risk_assessment, rag_output")
        .not_.is_("rag_output", "null")
        .order("call_timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    if not result.data:
        return []

    items = []
    for row in result.data:
        ra = row.get("risk_assessment") or {}
        ro = row.get("rag_output") or {}
        items.append({
            "call_id": row["call_id"],
            "call_timestamp": row["call_timestamp"],
            "status": row.get("status", "open"),
            "risk_score": ra.get("risk_score", 0),
            "fraud_likelihood": ra.get("fraud_likelihood", "unknown"),
            "grounded_assessment": ro.get("grounded_assessment", "unknown"),
            "recommended_action": ro.get("recommended_action", "unknown"),
            "summary": row.get("summary_for_rag", ""),
        })
    return items


def get_top_patterns(limit: int = 10) -> list[dict]:
    """Call top_patterns() RPC — aggregated pattern frequency."""
    client = get_supabase_client()
    logger.info(f"DB RPC top_patterns (limit={limit})")
    result = client.rpc("top_patterns", {"pattern_limit": limit}).execute()
    if not result.data:
        return []
    return [{"pattern": r["pattern"], "count": r["match_count"]} for r in result.data]


def get_active_cases(limit: int = 3) -> tuple[list[dict], int]:
    """
    Fetch unresolved cases sorted by risk score descending.
    Returns (cases_list, total_active_count).
    """
    client = get_supabase_client()
    logger.info(f"DB SELECT active_cases (limit={limit})")

    # Get total active count
    count_result = (
        client.table("call_analyses")
        .select("call_id", count="exact")
        .not_.is_("rag_output", "null")
        .neq("status", "resolved")
        .execute()
    )
    total_active = count_result.count or 0

    # Get cases (fetch more than limit, sort in python by risk_score)
    fetch_limit = max(limit * 3, 20)
    result = (
        client.table("call_analyses")
        .select("call_id, call_timestamp, status, call_context, speaker_analysis, nlp_insights, risk_signals, risk_assessment, rag_output, summary_for_rag")
        .not_.is_("rag_output", "null")
        .neq("status", "resolved")
        .order("call_timestamp", desc=True)
        .limit(fetch_limit)
        .execute()
    )
    if not result.data:
        return [], total_active

    # Sort by risk_score descending
    cases = sorted(
        result.data,
        key=lambda c: (c.get("risk_assessment") or {}).get("risk_score", 0),
        reverse=True,
    )
    return cases[:limit], total_active


def update_backboard_thread_id(call_id: str, thread_id: str) -> None:
    """Store the Backboard thread_id for a call."""
    client = get_supabase_client()
    logger.info(f"DB UPDATE backboard_thread_id ({call_id} → {thread_id[:12]}...)")
    client.table("call_analyses").update(
        {"backboard_thread_id": thread_id}
    ).eq("call_id", call_id).execute()


def get_recent_calls(days: int = 10, limit: int = 5) -> list[dict]:
    """
    Fetch the most recent N calls within the last `days` days.
    Used for temporal chatbot queries like "summarize last 5 records".
    """
    client = get_supabase_client()
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    logger.info(f"DB SELECT recent_calls (days={days}, limit={limit})")
    result = (
        client.table("call_analyses")
        .select("call_id, call_timestamp, status, summary_for_rag, risk_assessment, rag_output, backboard_thread_id")
        .gte("call_timestamp", cutoff)
        .order("call_timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data if result.data else []


def update_call_status(call_id: str, status: str) -> dict | None:
    """Update the status column for a call. Returns updated row or None."""
    client = get_supabase_client()
    logger.info(f"DB UPDATE status ({call_id} → {status})")
    result = (
        client.table("call_analyses")
        .update({"status": status})
        .eq("call_id", call_id)
        .execute()
    )
    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def get_calls_paginated(
    page: int = 1,
    limit: int = 10,
    status_filter: str | None = None,
    risk_filter: str | None = None,
    sort: str = "recent",
) -> tuple[list[dict], int]:
    """
    Paginated call listing with optional filters.
    Returns (calls_list, total_count).
    """
    client = get_supabase_client()
    offset = (page - 1) * limit
    logger.info(f"DB SELECT calls (page={page} limit={limit} status={status_filter} risk={risk_filter} sort={sort})")

    # Build count query
    count_q = client.table("call_analyses").select("call_id", count="exact")
    if status_filter:
        count_q = count_q.eq("status", status_filter)
    if risk_filter:
        count_q = count_q.not_.is_("rag_output", "null")
    count_result = count_q.execute()
    total = count_result.count or 0

    # Build data query
    data_q = (
        client.table("call_analyses")
        .select("call_id, call_timestamp, status, call_context, speaker_analysis, nlp_insights, risk_signals, risk_assessment, rag_output, summary_for_rag")
    )
    if status_filter:
        data_q = data_q.eq("status", status_filter)
    if risk_filter:
        data_q = data_q.not_.is_("rag_output", "null")

    data_q = data_q.order("call_timestamp", desc=True).range(offset, offset + limit - 1)
    result = data_q.execute()
    calls = result.data if result.data else []

    # If risk filter, filter in python (Supabase client can't filter JSONB easily)
    if risk_filter:
        calls = [
            c for c in calls
            if (c.get("rag_output") or {}).get("grounded_assessment") == risk_filter
        ]

    # If sort by risk, re-sort in python
    if sort == "risk":
        calls = sorted(
            calls,
            key=lambda c: (c.get("risk_assessment") or {}).get("risk_score", 0),
            reverse=True,
        )

    return calls, total


# ============================================================
# call_documents table operations
# ============================================================

def insert_call_document(
    doc_id: str,
    call_id: str,
    document_data: dict,
    embedding: list[float] | None = None,
) -> dict:
    """
    Insert or upsert an extracted call document into call_documents table.

    Args:
        doc_id:         Unique document ID (e.g. "cdoc_call_2026_02_11_a1b2c3")
        call_id:        The parent call_id from call_analyses
        document_data:  Dict with all extracted fields
        embedding:      Optional 1536-dim vector for semantic search

    Returns: {"upserted": True, "doc_id": "...", "call_id": "..."}
    """
    client = get_supabase_client()

    row = {
        "doc_id": doc_id,
        "call_id": call_id,
        "financial_data": document_data.get("financial_data", {}),
        "entities": document_data.get("entities", {}),
        "commitments": document_data.get("commitments", []),
        "call_summary": document_data.get("call_summary", "No summary."),
        "call_purpose": document_data.get("call_purpose"),
        "call_outcome": document_data.get("call_outcome"),
        "key_discussion_points": document_data.get("key_discussion_points", []),
        "compliance_notes": document_data.get("compliance_notes", []),
        "risk_flags": document_data.get("risk_flags", []),
        "action_items": document_data.get("action_items", []),
        "call_timeline": document_data.get("call_timeline", []),
        "extraction_model": document_data.get("extraction_model", "gpt-4o-mini"),
        "extraction_tokens": document_data.get("extraction_tokens", 0),
        "extraction_version": document_data.get("extraction_version", "v1"),
    }

    if embedding:
        row["doc_embedding"] = embedding

    logger.info(f"DB UPSERT call_documents ({doc_id})")
    result = client.table("call_documents").upsert(row).execute()

    if not result.data:
        raise RuntimeError(f"Supabase upsert failed for doc_id={doc_id}")

    return {
        "upserted": True,
        "doc_id": doc_id,
        "call_id": call_id,
        "table": "call_documents",
    }


def get_call_document(call_id: str) -> dict | None:
    """
    Fetch the extracted document for a specific call.
    Returns the full row or None if not found.
    """
    client = get_supabase_client()

    result = (
        client.table("call_documents")
        .select("*")
        .eq("call_id", call_id)
        .execute()
    )

    if result.data and len(result.data) > 0:
        return result.data[0]
    return None


def search_call_documents(
    query_embedding: list[float],
    limit: int = 5,
) -> list[dict]:
    """
    Semantic search across all call documents using match_call_documents RPC.
    """
    client = get_supabase_client()
    logger.info(f"DB RPC match_call_documents (limit={limit})")
    result = client.rpc(
        "match_call_documents",
        {
            "query_embedding": query_embedding,
            "match_limit": limit,
        },
    ).execute()
    return result.data if result.data else []


def get_call_documents_paginated(
    page: int = 1,
    limit: int = 10,
    purpose_filter: str | None = None,
    outcome_filter: str | None = None,
) -> tuple[list[dict], int]:
    """
    Paginated listing of call documents with optional filters.
    Returns (docs_list, total_count).
    """
    client = get_supabase_client()
    offset = (page - 1) * limit
    logger.info(f"DB SELECT call_documents (page={page} limit={limit})")

    # Count query
    count_q = client.table("call_documents").select("doc_id", count="exact")
    if purpose_filter:
        count_q = count_q.eq("call_purpose", purpose_filter)
    if outcome_filter:
        count_q = count_q.eq("call_outcome", outcome_filter)
    count_result = count_q.execute()
    total = count_result.count or 0

    # Data query
    data_q = client.table("call_documents").select(
        "doc_id, call_id, generated_at, call_summary, call_purpose, call_outcome, "
        "financial_data, entities, commitments, action_items, extraction_model, extraction_tokens"
    )
    if purpose_filter:
        data_q = data_q.eq("call_purpose", purpose_filter)
    if outcome_filter:
        data_q = data_q.eq("call_outcome", outcome_filter)

    data_q = data_q.order("generated_at", desc=True).range(offset, offset + limit - 1)
    result = data_q.execute()
    docs = result.data if result.data else []

    return docs, total


def get_financial_summary(days: int = 30) -> dict:
    """
    Aggregated financial intelligence across recent call documents.
    Uses the financial_summary RPC function.
    """
    client = get_supabase_client()
    logger.info(f"DB RPC financial_summary (days={days})")
    result = client.rpc("financial_summary", {"days_back": days}).execute()
    return result.data if result.data else {}
