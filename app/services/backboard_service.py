"""
Backboard AI integration service.
Creates a persistent reasoning thread per call for auditability & memory.
All functions are non-blocking — failures log warnings but never raise.
"""

import os
import logging
import httpx

logger = logging.getLogger("rag.backboard")

BASE_URL = "https://app.backboard.io/api"
ASSISTANT_ID: str | None = None   # cached after first boot


def _headers() -> dict:
    key = os.getenv("BACKBOARD_API_KEY", "")
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _ensure_assistant() -> str | None:
    """Create or reuse the Stentor assistant (one-time)."""
    global ASSISTANT_ID
    if ASSISTANT_ID:
        return ASSISTANT_ID
    try:
        resp = httpx.post(
            f"{BASE_URL}/assistants",
            json={
                "name": "Stentor RAG Auditor",
                "system_prompt": (
                    "You are a reasoning audit assistant for a financial call "
                    "risk analysis pipeline. You store grounding context, "
                    "retrieved knowledge, and LLM reasoning output for each "
                    "call to provide full traceability and explainability. "
                    "When asked about past calls, summarize the reasoning "
                    "chain and highlight risk patterns."
                ),
            },
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        ASSISTANT_ID = data.get("assistant_id") or data.get("id")
        logger.info(f"Backboard assistant created: {ASSISTANT_ID}")
        return ASSISTANT_ID
    except Exception as e:
        logger.warning(f"Backboard assistant creation failed: {e}")
        return None


def create_thread_for_call(call_id: str) -> str | None:
    """
    Create a Backboard thread for a call.
    Returns thread_id or None on failure.
    """
    assistant_id = _ensure_assistant()
    if not assistant_id:
        return None
    try:
        resp = httpx.post(
            f"{BASE_URL}/assistants/{assistant_id}/threads",
            json={"metadata_": {"call_id": call_id, "source": "Stentor_rag"}},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        thread_id = data.get("thread_id") or data.get("id")
        logger.info(f"[{call_id}] Backboard thread: {thread_id}")
        return thread_id
    except Exception as e:
        logger.warning(f"[{call_id}] Backboard thread creation failed: {e}")
        return None


def log_to_thread(thread_id: str, content: str, label: str = "") -> None:
    """
    Add a message to a Backboard thread (send_to_llm=false — just stores).
    Uses memory=Auto so Backboard learns cross-call patterns.
    """
    if not thread_id:
        return
    try:
        httpx.post(
            f"{BASE_URL}/threads/{thread_id}/messages",
            headers={"X-API-Key": os.getenv("BACKBOARD_API_KEY", "")},
            data={
                "content": content,
                "send_to_llm": "false",
                "stream": "false",
                "memory": "Auto",
            },
            timeout=15,
        )
        logger.info(f"Backboard logged: {label}")
    except Exception as e:
        logger.warning(f"Backboard log failed ({label}): {e}")


def query_thread(thread_id: str, question: str) -> str | None:
    """
    Send a question to a Backboard thread and get an LLM-powered answer.
    Uses send_to_llm=true so Backboard reasons over the stored context.
    Returns the assistant's answer text or None on failure.
    """
    if not thread_id:
        return None
    try:
        resp = httpx.post(
            f"{BASE_URL}/threads/{thread_id}/messages",
            headers={"X-API-Key": os.getenv("BACKBOARD_API_KEY", "")},
            data={
                "content": question,
                "send_to_llm": "true",
                "stream": "false",
                "memory": "Auto",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        # Extract the assistant reply
        if isinstance(data, dict):
            return data.get("content") or data.get("message") or str(data)
        return str(data)
    except Exception as e:
        logger.warning(f"Backboard query failed: {e}")
        return None


def get_thread(thread_id: str) -> dict | None:
    """Retrieve a Backboard thread with all messages (full audit trail)."""
    try:
        resp = httpx.get(
            f"{BASE_URL}/threads/{thread_id}",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Backboard thread fetch failed: {e}")
        return None


def get_thread_messages(thread_id: str) -> list:
    """Get all messages in a Backboard thread."""
    try:
        resp = httpx.get(
            f"{BASE_URL}/threads/{thread_id}/messages",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("messages", data.get("data", []))
    except Exception as e:
        logger.warning(f"Backboard messages fetch failed: {e}")
        return []


def get_assistant_threads() -> list:
    """List all threads for our assistant."""
    assistant_id = _ensure_assistant()
    if not assistant_id:
        return []
    try:
        resp = httpx.get(
            f"{BASE_URL}/assistants/{assistant_id}/threads",
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("threads", data.get("data", []))
    except Exception as e:
        logger.warning(f"Backboard threads listing failed: {e}")
        return []


def query_memory(question: str) -> str | None:
    """
    Query Backboard's cross-call memory via assistant-level context.
    Creates a temporary thread, asks the question (Backboard uses memory=Auto
    which includes learned patterns from ALL previous threads), and returns the answer.
    Useful for chatbot temporal queries like "summarize last 5 calls".
    """
    assistant_id = _ensure_assistant()
    if not assistant_id:
        return None
    try:
        # Create a temporary query thread
        resp = httpx.post(
            f"{BASE_URL}/assistants/{assistant_id}/threads",
            json={"metadata_": {"purpose": "memory_query"}},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        temp_thread_id = data.get("thread_id") or data.get("id")
        if not temp_thread_id:
            return None

        # Send question with send_to_llm=true + memory=Auto
        answer = query_thread(temp_thread_id, question)
        return answer
    except Exception as e:
        logger.warning(f"Backboard memory query failed: {e}")
        return None
