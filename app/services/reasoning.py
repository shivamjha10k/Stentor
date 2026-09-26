"""
Reasoning service — Step 6: LLM Grounded Reasoning.
Sends the grounding context to OpenAI GPT-4o/4o-mini and parses
the structured JSON response (RAGOutput).
"""

import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger("rag.reasoning")

_client: OpenAI | None = None

SYSTEM_PROMPT = """You are a financial risk grounding assistant. Your role is to interpret
call-level risk signals by grounding them against known fraud patterns,
compliance rules, and risk heuristics.

You MUST return a JSON object with:
- grounded_assessment: one of "high_risk", "medium_risk", "low_risk"
- explanation: human-readable, auditor-friendly narrative explaining WHY
  the signals match or don't match known patterns. Cite specific patterns.
- recommended_action: one of "auto_clear", "flag_for_review", "manual_review",
  "escalate_to_compliance"
- confidence: float 0.0–1.0 representing grounding confidence
- regulatory_flags: array of regulatory concerns (empty if none)
- matched_patterns: array of pattern names that matched

RULES:
- You MUST NOT override the risk score from the NLP service
- You MUST NOT extract new intent, sentiment, or entities
- You MUST NOT use accusatory language ("fraudster", "liar", "criminal")
- You MUST use terms like: "high-risk indicators", "unreliable commitment",
  "requires verification", "fraud-adjacent pattern"
- If signals are ambiguous, say so and recommend manual review
- If no patterns match, state that clearly and lower confidence
- Base your reasoning ONLY on the provided signals and retrieved knowledge
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


def run_grounded_reasoning(grounding_context: str) -> dict:
    """
    Send the grounding context to the LLM and parse the structured response.

    Args:
        grounding_context: The full context string from Step 5.

    Returns:
        Dict matching RAGOutput schema:
        {
            "grounded_assessment": "high_risk" | "medium_risk" | "low_risk",
            "explanation": str,
            "recommended_action": str,
            "confidence": float,
            "regulatory_flags": list[str],
            "matched_patterns": list[str],
        }

    Raises:
        RuntimeError: If LLM call fails or response cannot be parsed.
    """
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    client = _get_openai_client()

    logger.info(f"Calling {model} with {len(grounding_context)} chars context")

    last_error = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": grounding_context},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"LLM attempt 1 failed, retrying: {str(e)}")
            else:
                logger.error(f"LLM failed after 2 attempts: {str(e)}")

    if last_error is not None:
        return _fallback_assessment()

    # noinspection PyUnboundLocalVariable

    raw = response.choices[0].message.content
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens

    logger.info(f"LLM responded | {tokens_in} in / {tokens_out} out tokens")

    # Parse JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {raw[:200]}")
        raise RuntimeError(f"LLM returned invalid JSON: {str(e)}")

    # Validate required keys
    required_keys = [
        "grounded_assessment",
        "explanation",
        "recommended_action",
        "confidence",
        "regulatory_flags",
        "matched_patterns",
    ]
    missing = [k for k in required_keys if k not in result]
    if missing:
        logger.error(f"LLM response missing keys: {missing}")
        raise RuntimeError(f"LLM response missing required keys: {missing}")

    # Validate enum values
    valid_assessments = {"high_risk", "medium_risk", "low_risk"}
    valid_actions = {"auto_clear", "flag_for_review", "manual_review", "escalate_to_compliance"}

    if result["grounded_assessment"] not in valid_assessments:
        logger.warning(f"Invalid assessment '{result['grounded_assessment']}', defaulting to 'high_risk'")
        result["grounded_assessment"] = "high_risk"

    if result["recommended_action"] not in valid_actions:
        logger.warning(f"Invalid action '{result['recommended_action']}', defaulting to 'manual_review'")
        result["recommended_action"] = "manual_review"

    # Clamp confidence
    result["confidence"] = max(0.0, min(1.0, float(result["confidence"])))

    # Ensure lists
    if not isinstance(result["regulatory_flags"], list):
        result["regulatory_flags"] = []
    if not isinstance(result["matched_patterns"], list):
        result["matched_patterns"] = []

    return result


def _fallback_assessment() -> dict:
    """Return a safe fallback when LLM is unavailable after retry."""
    logger.warning("Returning fallback assessment (LLM unavailable)")
    return {
        "grounded_assessment": "high_risk",
        "explanation": "Automated grounding was unavailable. This call has been flagged for manual review as a precaution. A human assessor should evaluate the risk signals directly.",
        "recommended_action": "manual_review",
        "confidence": 0.0,
        "regulatory_flags": [],
        "matched_patterns": [],
    }
