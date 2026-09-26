"""
Chat retrieval service — searches knowledge base + call history
using vector similarity for the chatbot endpoint.
Also supports direct call_id lookup when user asks about a specific call.
"""

import re
import logging
from app.db.queries import search_knowledge, search_calls, get_call_by_id

logger = logging.getLogger("rag.chat_retrieval")

# Matches call IDs like call_2026_02_09_a1b2c3
CALL_ID_PATTERN = re.compile(r"call_\d{4}_\d{2}_\d{2}_[a-f0-9]{6}")


def extract_call_ids(text: str) -> list[str]:
    """Extract call_id patterns from user's question."""
    return list(set(CALL_ID_PATTERN.findall(text)))


def lookup_calls_by_id(call_ids: list[str]) -> list[dict]:
    """
    Direct DB lookup for specific call IDs.
    Returns call records formatted for chat context.
    """
    results = []
    for cid in call_ids:
        try:
            record = get_call_by_id(cid)
            if record:
                results.append({
                    "call_id": record.get("call_id", cid),
                    "call_timestamp": record.get("call_timestamp", ""),
                    "summary_for_rag": record.get("summary_for_rag", ""),
                    "risk_score": record.get("risk_assessment", {}).get("risk_score", 0) if isinstance(record.get("risk_assessment"), dict) else 0,
                    "fraud_likelihood": record.get("risk_assessment", {}).get("fraud_likelihood", "unknown") if isinstance(record.get("risk_assessment"), dict) else "unknown",
                    "grounded_assessment": record.get("rag_output", {}).get("grounded_assessment", "pending") if isinstance(record.get("rag_output"), dict) else "pending",
                    "similarity": 1.0,  # exact match
                    "_lookup": True,  # flag: this was a direct lookup, not vector search
                    "_full_record": record,  # include full record for LLM context
                })
                logger.info(f"Direct lookup found: {cid}")
            else:
                logger.warning(f"Direct lookup miss: {cid}")
        except Exception as e:
            logger.warning(f"Direct lookup failed for {cid}: {str(e)}")
    return results


def retrieve_for_chat(
    query_embedding: list[float],
    search_knowledge_flag: bool = True,
    search_calls_flag: bool = False,
    categories: list[str] | None = None,
    knowledge_limit: int = 5,
    calls_limit: int = 3,
) -> dict:
    """
    Retrieve relevant documents for chatbot context.

    Args:
        query_embedding: 1536-dim vector of the user's question.
        search_knowledge_flag: Whether to search knowledge_embeddings.
        search_calls_flag: Whether to search past call_analyses.
        categories: Knowledge categories to search.
        knowledge_limit: Max knowledge docs per category.
        calls_limit: Max call records to retrieve.

    Returns:
        {
            "knowledge_docs": [ { doc_id, category, title, content, similarity }, ... ],
            "call_docs": [ { call_id, call_timestamp, summary_for_rag, risk_score, ... }, ... ],
        }
    """
    if categories is None:
        categories = ["fraud_pattern", "compliance", "risk_heuristic"]

    knowledge_docs = []
    call_docs = []

    # --- Knowledge base vector search ---
    if search_knowledge_flag:
        for cat in categories:
            try:
                results = search_knowledge(query_embedding, cat, knowledge_limit)
                knowledge_docs.extend(results)
            except Exception as e:
                logger.warning(f"Knowledge search failed for {cat}: {str(e)}")

        # Sort all knowledge docs by similarity descending, take top N
        knowledge_docs.sort(key=lambda d: d.get("similarity", 0), reverse=True)
        knowledge_docs = knowledge_docs[:knowledge_limit]
        logger.info(f"Knowledge search: {len(knowledge_docs)} docs retrieved")

    # --- Call history vector search ---
    if search_calls_flag:
        try:
            call_docs = search_calls(query_embedding, calls_limit)
            logger.info(f"Call search: {len(call_docs)} calls retrieved")
        except Exception as e:
            logger.warning(f"Call search failed: {str(e)}")

    return {
        "knowledge_docs": knowledge_docs,
        "call_docs": call_docs,
        "direct_lookups": [],  # populated by route when call IDs detected
    }
