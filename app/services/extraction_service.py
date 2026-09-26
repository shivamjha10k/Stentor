"""
Extraction service — Step 9: Call Document Extraction.
Takes full call data (transcript + NLP signals + RAG output) and produces
a structured document with financial data, entities, commitments, timeline.
"""

import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger("rag.extraction")

_client: OpenAI | None = None

EXTRACTION_SYSTEM_PROMPT = """You are a financial call document analyst. Your job is to extract
ALL structured data from a call transcript and its analysis signals, producing a comprehensive
call document.

You MUST return a JSON object with these exact keys:

1. "financial_data": {
     "amounts_mentioned": [{"value": float, "currency": str, "context": str}],
     "payment_commitments": [{"amount": float, "due_date": str or null, "type": str}],
     "account_references": [str],
     "transaction_references": [str],
     "financial_products": [str],
     "total_outstanding": float or null,
     "settlement_offered": float or null,
     "emi_details": {"amount": float, "frequency": str, "remaining": int} or null
   }

2. "entities": {
     "persons": [str],
     "organizations": [str],
     "dates": [str],
     "locations": [str],
     "phone_numbers": [str],
     "reference_numbers": [str]
   }

3. "commitments": [
     {
       "speaker": "CUSTOMER" or "AGENT",
       "commitment": str,
       "type": "payment_promise" or "callback_request" or "escalation_request" or "info_request" or "other",
       "confidence": float (0.0-1.0),
       "conditional": bool,
       "condition": str or null
     }
   ]

4. "call_summary": str (3-5 sentence narrative summary)
5. "call_purpose": str (one of: debt_collection, account_inquiry, complaint, fraud_report, general_inquiry, settlement_negotiation, payment_arrangement, other)
6. "call_outcome": str (one of: payment_committed, escalated, unresolved, resolved, callback_scheduled, info_provided, complaint_registered, other)
7. "key_discussion_points": [str] (3-7 bullet points)
8. "compliance_notes": [str] (any regulatory/compliance observations)
9. "risk_flags": [str] (behavioral or fraud risk indicators)
10. "action_items": [str] (next steps required)
11. "call_timeline": [
      {
        "timestamp_approx": str ("early", "mid", or "late"),
        "event": str,
        "speaker": "CUSTOMER" or "AGENT" or "SYSTEM",
        "significance": "high" or "medium" or "low"
      }
    ]

RULES:
- Extract ONLY what is explicitly stated or directly inferable from the transcript
- Do NOT hallucinate financial amounts or dates not mentioned in the data
- If a field has no data, use empty arrays [] or null
- For amounts, always include currency (default "INR" if not specified)
- Mark commitments as conditional if they contain "if", "provided that", etc.
- Be precise with compliance notes — cite specific regulations if applicable
- Return ONLY the JSON object, no markdown fencing or extra text"""


def _get_openai_client() -> OpenAI:
    """Lazy-initialized OpenAI client singleton."""
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set in .env file.")

    _client = OpenAI(api_key=api_key)
    return _client


def _build_extraction_context(
    call_id: str,
    payload: dict,
    rag_output: dict,
) -> str:
    """
    Build the full context string for the extraction LLM call.
    Combines transcript, NLP signals, risk assessment, and RAG output.
    """
    parts = [f"=== CALL ID: {call_id} ===\n"]

    # Call context
    ctx = payload.get("call_context", {})
    parts.append(f"Language: {ctx.get('call_language', 'unknown')}")
    quality = ctx.get("call_quality", {})
    parts.append(f"Call Quality: noise={quality.get('noise_level', '?')}, stability={quality.get('call_stability', '?')}, naturalness={quality.get('speech_naturalness', '?')}")

    # NLP Insights
    nlp = payload.get("nlp_insights", {})
    intent = nlp.get("intent", {})
    sentiment = nlp.get("sentiment", {})
    entities = nlp.get("entities", {})
    parts.append(f"\n--- NLP INSIGHTS ---")
    parts.append(f"Intent: {intent.get('label', '?')} (confidence={intent.get('confidence', '?')}, conditionality={intent.get('conditionality', '?')})")
    parts.append(f"Sentiment: {sentiment.get('label', '?')} (confidence={sentiment.get('confidence', '?')})")
    parts.append(f"Obligation Strength: {nlp.get('obligation_strength', '?')}")
    parts.append(f"Contradictions Detected: {nlp.get('contradictions_detected', False)}")
    if entities.get("payment_commitment"):
        parts.append(f"Payment Commitment: {entities['payment_commitment']}")
    if entities.get("amount_mentioned") is not None:
        parts.append(f"Amount Mentioned (NLP): {entities['amount_mentioned']}")

    # Risk signals
    risk_signals = payload.get("risk_signals", {})
    audio_flags = risk_signals.get("audio_trust_flags", [])
    behavioral_flags = risk_signals.get("behavioral_flags", [])
    if audio_flags:
        parts.append(f"\n--- AUDIO TRUST FLAGS ---\n{', '.join(audio_flags)}")
    if behavioral_flags:
        parts.append(f"\n--- BEHAVIORAL FLAGS ---\n{', '.join(behavioral_flags)}")

    # Risk assessment
    ra = payload.get("risk_assessment", {})
    parts.append(f"\n--- RISK ASSESSMENT ---")
    parts.append(f"Risk Score: {ra.get('risk_score', '?')}/100")
    parts.append(f"Fraud Likelihood: {ra.get('fraud_likelihood', '?')}")
    parts.append(f"Confidence: {ra.get('confidence', '?')}")

    # Summary
    summary = payload.get("summary_for_rag", "")
    if summary:
        parts.append(f"\n--- CALL SUMMARY ---\n{summary}")

    # Transcript
    conversation = payload.get("conversation", [])
    if conversation:
        # Limit to last 60 turns for very long calls
        if len(conversation) > 60:
            conversation = conversation[-60:]
            parts.append(f"\n--- TRANSCRIPT (last 60 of {len(payload.get('conversation', []))} turns) ---")
        else:
            parts.append(f"\n--- FULL TRANSCRIPT ({len(conversation)} turns) ---")
        for turn in conversation:
            speaker = turn.get("speaker", "?")
            text = turn.get("text", "")
            parts.append(f"[{speaker}]: {text}")

    # RAG output (grounding assessment)
    if rag_output:
        parts.append(f"\n--- RAG GROUNDED ASSESSMENT ---")
        parts.append(f"Assessment: {rag_output.get('grounded_assessment', '?')}")
        parts.append(f"Recommended Action: {rag_output.get('recommended_action', '?')}")
        parts.append(f"Explanation: {rag_output.get('explanation', '?')}")
        matched = rag_output.get("matched_patterns", [])
        if matched:
            parts.append(f"Matched Patterns: {', '.join(matched)}")
        reg_flags = rag_output.get("regulatory_flags", [])
        if reg_flags:
            parts.append(f"Regulatory Flags: {', '.join(reg_flags)}")

    return "\n".join(parts)


def _validate_extraction(result: dict) -> dict:
    """Validate and sanitize the LLM extraction output."""

    # Ensure financial_data structure
    fd = result.get("financial_data", {})
    if not isinstance(fd, dict):
        fd = {}
    fd.setdefault("amounts_mentioned", [])
    fd.setdefault("payment_commitments", [])
    fd.setdefault("account_references", [])
    fd.setdefault("transaction_references", [])
    fd.setdefault("financial_products", [])
    fd.setdefault("total_outstanding", None)
    fd.setdefault("settlement_offered", None)
    fd.setdefault("emi_details", None)
    result["financial_data"] = fd

    # Ensure entities structure
    ent = result.get("entities", {})
    if not isinstance(ent, dict):
        ent = {}
    for key in ["persons", "organizations", "dates", "locations", "phone_numbers", "reference_numbers"]:
        ent.setdefault(key, [])
    result["entities"] = ent

    # Ensure lists
    for key in ["commitments", "key_discussion_points", "compliance_notes",
                 "risk_flags", "action_items", "call_timeline"]:
        if not isinstance(result.get(key), list):
            result[key] = []

    # Ensure strings
    result.setdefault("call_summary", "No summary available.")
    result.setdefault("call_purpose", "other")
    result.setdefault("call_outcome", "other")

    # Validate call_purpose
    valid_purposes = {
        "debt_collection", "account_inquiry", "complaint", "fraud_report",
        "general_inquiry", "settlement_negotiation", "payment_arrangement", "other",
    }
    if result["call_purpose"] not in valid_purposes:
        result["call_purpose"] = "other"

    # Validate call_outcome
    valid_outcomes = {
        "payment_committed", "escalated", "unresolved", "resolved",
        "callback_scheduled", "info_provided", "complaint_registered", "other",
    }
    if result["call_outcome"] not in valid_outcomes:
        result["call_outcome"] = "other"

    # Validate commitment confidences
    for c in result["commitments"]:
        if isinstance(c, dict) and "confidence" in c:
            c["confidence"] = max(0.0, min(1.0, float(c["confidence"])))

    return result


def _fallback_extraction(payload: dict) -> dict:
    """Return a minimal extraction when the LLM is unavailable."""
    logger.warning("Returning fallback extraction (LLM unavailable)")
    summary = payload.get("summary_for_rag", "Call summary unavailable.")
    nlp = payload.get("nlp_insights", {})
    entities = nlp.get("entities", {})

    fd = {
        "amounts_mentioned": [],
        "payment_commitments": [],
        "account_references": [],
        "transaction_references": [],
        "financial_products": [],
        "total_outstanding": None,
        "settlement_offered": None,
        "emi_details": None,
    }
    # Use NLP-extracted amount if available
    if entities.get("amount_mentioned") is not None:
        fd["amounts_mentioned"].append({
            "value": float(entities["amount_mentioned"]),
            "currency": "INR",
            "context": "mentioned in call (NLP-extracted)",
        })
    if entities.get("payment_commitment"):
        fd["payment_commitments"].append({
            "amount": float(entities.get("amount_mentioned", 0)),
            "due_date": None,
            "type": str(entities["payment_commitment"]),
        })

    return {
        "financial_data": fd,
        "entities": {"persons": [], "organizations": [], "dates": [], "locations": [], "phone_numbers": [], "reference_numbers": []},
        "commitments": [],
        "call_summary": summary,
        "call_purpose": "other",
        "call_outcome": "other",
        "key_discussion_points": [],
        "compliance_notes": [],
        "risk_flags": [],
        "action_items": ["Manual review required — automated extraction was unavailable"],
        "call_timeline": [],
    }


def extract_call_document(
    call_id: str,
    payload: dict,
    rag_output: dict,
) -> dict:
    """
    Main extraction function — extracts structured data from a call.

    Args:
        call_id:    The call identifier
        payload:    Full call data dict (call_context, nlp_insights, conversation, etc.)
        rag_output: The RAG grounded reasoning output dict

    Returns:
        Dict with all extracted fields + extraction metadata:
        {
            "financial_data": {...},
            "entities": {...},
            "commitments": [...],
            "call_summary": str,
            "call_purpose": str,
            "call_outcome": str,
            "key_discussion_points": [...],
            "compliance_notes": [...],
            "risk_flags": [...],
            "action_items": [...],
            "call_timeline": [...],
            "extraction_model": str,
            "extraction_tokens": int,
        }
    """
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # Use gpt-4o for high-risk calls if available
    ra = payload.get("risk_assessment", {})
    if ra.get("risk_score", 0) >= 70:
        model = os.getenv("LLM_MODEL_HIGH_RISK", model)

    client = _get_openai_client()
    extraction_context = _build_extraction_context(call_id, payload, rag_output)

    logger.info(f"[{call_id}] Extracting call document | model={model} | context={len(extraction_context)} chars")

    last_error = None
    response = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": extraction_context},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"[{call_id}] Extraction attempt 1 failed, retrying: {e}")
            else:
                logger.error(f"[{call_id}] Extraction failed after 2 attempts: {e}")

    if last_error is not None or response is None:
        result = _fallback_extraction(payload)
        result["extraction_model"] = model
        result["extraction_tokens"] = 0
        return result

    raw = response.choices[0].message.content
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    total_tokens = tokens_in + tokens_out

    logger.info(f"[{call_id}] Extraction LLM done | {tokens_in} in / {tokens_out} out tokens")

    # Parse JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[{call_id}] Extraction LLM returned invalid JSON: {raw[:300]}")
        result = _fallback_extraction(payload)
        result["extraction_model"] = model
        result["extraction_tokens"] = total_tokens
        return result

    # Validate & sanitize
    result = _validate_extraction(result)
    result["extraction_model"] = model
    result["extraction_tokens"] = total_tokens

    logger.info(
        f"[{call_id}] Document extracted | "
        f"financial_amounts={len(result['financial_data']['amounts_mentioned'])} "
        f"commitments={len(result['commitments'])} "
        f"entities_persons={len(result['entities']['persons'])} "
        f"timeline_events={len(result['call_timeline'])}"
    )

    return result
