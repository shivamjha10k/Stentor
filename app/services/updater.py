"""
Updater service — Step 7: Store RAG Output.
Updates the rag_output column in call_analyses after LLM reasoning.
"""

import logging
from app.db.queries import update_rag_output

logger = logging.getLogger("rag.updater")


def store_rag_output(call_id: str, rag_output: dict) -> dict:
    """
    Persist the LLM grounded reasoning output back to the call record.

    Args:
        call_id: The call identifier.
        rag_output: The structured RAG output dict from Step 6.

    Returns:
        {"updated": True, "call_id": "...", "table": "call_analyses", "field": "rag_output"}

    Raises:
        RuntimeError: If the Supabase update fails.
    """
    logger.info(f"Storing rag_output for {call_id}")

    result = update_rag_output(call_id=call_id, rag_output=rag_output)

    logger.info(f"rag_output stored for {call_id} | assessment={rag_output.get('grounded_assessment')}")
    return result
