"""
Retrieval service — Step 4: Retrieve Knowledge Chunks.
Uses the query embedding from Step 3 to perform semantic search
against the knowledge_embeddings table in Supabase via pgvector.

Retrieves three categories:
  4A — Fraud patterns
  4B — Compliance guidance
  4C — Risk heuristics
"""

import os
import logging
from app.db.queries import search_knowledge

logger = logging.getLogger("rag.retrieval")


def retrieve_knowledge_chunks(query_embedding: list[float]) -> dict:
    """
    Perform semantic search against the curated knowledge base.
    Searches across three categories with configurable limits.

    Args:
        query_embedding: 1536-dim embedding vector from Step 3.

    Returns:
        {
            "fraud_patterns": [ { doc_id, title, content, similarity }, ... ],
            "compliance_docs": [ ... ],
            "risk_heuristics": [ ... ],
        }

    Raises:
        RuntimeError: If any knowledge retrieval fails.
    """
    fraud_limit = int(os.getenv("FRAUD_PATTERN_RETRIEVAL_LIMIT", "3"))
    compliance_limit = int(os.getenv("COMPLIANCE_RETRIEVAL_LIMIT", "2"))
    heuristic_limit = int(os.getenv("RISK_HEURISTIC_RETRIEVAL_LIMIT", "2"))

    try:
        fraud_patterns = search_knowledge(query_embedding, "fraud_pattern", fraud_limit)
        compliance_docs = search_knowledge(query_embedding, "compliance", compliance_limit)
        risk_heuristics = search_knowledge(query_embedding, "risk_heuristic", heuristic_limit)
    except Exception as e:
        logger.error(f"Knowledge retrieval failed: {str(e)}")
        raise RuntimeError(f"Knowledge retrieval failed: {str(e)}")

    logger.info(f"Retrieved: fraud={len(fraud_patterns)} compliance={len(compliance_docs)} heuristic={len(risk_heuristics)}")

    return {
        "fraud_patterns": fraud_patterns,
        "compliance_docs": compliance_docs,
        "risk_heuristics": risk_heuristics,
    }
