"""
Chat reasoning service — sends the chatbot context to GPT-4o-mini
and returns a grounded answer with source citations.
Uses a chatbot-specific system prompt different from the risk grounding prompt.
"""

import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger("rag.chat_reasoning")

_client: OpenAI | None = None

CHAT_SYSTEM_PROMPT = """You are a financial compliance knowledge assistant. You answer questions
about fraud patterns, compliance rules, risk heuristics, and call analysis
data by grounding your answers in retrieved knowledge documents.

RULES:
- Answer ONLY based on the provided retrieved knowledge and call data
- If the retrieved documents don't contain the answer, say "I don't have enough information in the knowledge base to answer that."
- Cite specific document titles and IDs (e.g. [fp_001]) when referencing knowledge
- Use clear, professional language appropriate for compliance teams
- Do NOT invent patterns or rules not present in the knowledge base
- Do NOT use accusatory language ("fraudster", "liar", "criminal")
- When discussing call records, reference them by call_id
- Keep answers concise but thorough — aim for 2-4 paragraphs max
- If the question is ambiguous, ask for clarification

You MUST return a JSON object with:
- answer: your grounded response text citing specific documents
- source_ids: array of doc_id or call_id strings you referenced in the answer

Return ONLY the JSON object, no markdown fencing or extra text."""


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


def run_chat_reasoning(chat_context: str) -> dict:
    """
    Send chat context to the LLM and return the answer.

    Args:
        chat_context: Structured context from chat_context.py.

    Returns:
        {
            "answer": str,
            "source_ids": [str, ...],
            "model": str,
            "tokens_used": int,
        }

    Raises:
        RuntimeError: If LLM call fails after retry.
    """
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    client = _get_openai_client()

    logger.info(f"Chat LLM call | {model} | {len(chat_context)} chars context")

    last_error = None
    response = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                    {"role": "user", "content": chat_context},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                logger.warning(f"Chat LLM attempt 1 failed, retrying: {str(e)}")
            else:
                logger.error(f"Chat LLM failed after 2 attempts: {str(e)}")

    if last_error is not None:
        return _fallback_chat_response()

    raw = response.choices[0].message.content
    tokens_used = response.usage.prompt_tokens + response.usage.completion_tokens

    logger.info(f"Chat LLM responded | {tokens_used} tokens")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Chat LLM returned invalid JSON: {raw[:200]}")
        return {
            "answer": raw,  # Return raw text as answer if not valid JSON
            "source_ids": [],
            "model": model,
            "tokens_used": tokens_used,
        }

    return {
        "answer": result.get("answer", raw),
        "source_ids": result.get("source_ids", []),
        "model": model,
        "tokens_used": tokens_used,
    }


def _fallback_chat_response() -> dict:
    """Return a fallback when the LLM is unavailable."""
    logger.warning("Returning fallback chat response (LLM unavailable)")
    return {
        "answer": "I'm sorry, the knowledge assistant is temporarily unavailable. Please try again in a moment.",
        "source_ids": [],
        "model": "fallback",
        "tokens_used": 0,
    }
