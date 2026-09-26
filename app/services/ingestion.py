"""
Ingestion service — Step 2: Store Call Record.
Takes validated payload + generated call_id/timestamp → inserts into call_analyses.
"""

import logging
from datetime import datetime
from app.models.schemas import CallRiskInput
from app.db.queries import insert_call_record

logger = logging.getLogger("rag.ingestion")


def store_call_record(
    call_id: str,
    call_timestamp: datetime,
    payload: CallRiskInput,
) -> dict:
    """
    Store the validated call data into Supabase call_analyses table.
    rag_output is left NULL — will be populated after Step 7.

    Args:
        call_id: Auto-generated call identifier (e.g., "call_2026_02_09_a1b2c3")
        call_timestamp: UTC timestamp when the call was received
        payload: Validated Pydantic model from Step 1

    Returns:
        {"inserted": True, "call_id": "...", "table": "call_analyses"}

    Raises:
        RuntimeError: If Supabase insert fails
    """
    logger.info(f"Inserting {call_id} into call_analyses")

    result = insert_call_record(
        call_id=call_id,
        call_timestamp=call_timestamp.isoformat(),
        call_context=payload.call_context.model_dump(),
        speaker_analysis=payload.speaker_analysis.model_dump(),
        nlp_insights=payload.nlp_insights.model_dump(),
        risk_signals=payload.risk_signals.model_dump(),
        risk_assessment=payload.risk_assessment.model_dump(),
        summary_for_rag=payload.summary_for_rag,
        conversation=[turn.model_dump() for turn in payload.conversation],
        call_language=payload.call_context.call_language,
    )

    return result
