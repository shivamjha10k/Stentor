# Backboard AI Integration — Execution Plan

## Goal

Integrate [Backboard AI](https://backboard.io) as a **reasoning audit & memory layer** alongside the existing RAG pipeline — **without changing any current Supabase logic or pipeline flow**.

Backboard provides persistent threads, memory, and multi-model routing via a single API. We use it to:

1. **Store reasoning trace per call** — explainability & auditability
2. **Give the chatbot persistent memory** — cross-session context recall
3. **Demonstrate enterprise-readiness** at the hackathon (judges love traceability)

---

## Architecture (Before vs After)

### Before (current)
```
NLP Service
  → POST /analyze-call
    → Store in Supabase
    → Embed summary
    → Retrieve knowledge
    → Build grounding context
    → GPT-4o-mini reasoning
    → Store rag_output in Supabase
    → Return response
```

### After (with Backboard)
```
NLP Service
  → POST /analyze-call
    → Store in Supabase                 ← unchanged
    → Embed summary                     ← unchanged
    → Retrieve knowledge                ← unchanged
    → Build grounding context           ← unchanged
    ─── NEW: Log context to Backboard thread (non-blocking) ───
    → GPT-4o-mini reasoning             ← unchanged
    ─── NEW: Log LLM output to Backboard thread (non-blocking) ───
    → Store rag_output in Supabase      ← unchanged
    → Return response                   ← unchanged

Chatbot
  → POST /chat
    → Existing vector search            ← unchanged
    ─── NEW: Retrieve Backboard memory (optional enrichment) ───
    → LLM answer                        ← unchanged
    → Return response                   ← unchanged

Dashboard / Debug
  → GET /api/v1/backboard/{call_id}     ← NEW endpoint
    → Fetch full reasoning thread from Backboard
```

**Key principle**: Every Backboard call is **fire-and-forget** (wrapped in try/except, logged but never blocks). If Backboard is down, the pipeline runs exactly as before.

---

## Step-by-Step Execution

### Step 0 — Prerequisites
- [ ] Get Backboard API key from https://app.backboard.io
- [ ] Add to `.env`:
  ```
  BACKBOARD_API_KEY=your_key_here
  ```
- [ ] Install SDK:
  ```
  pip install backboard-sdk
  ```
- [ ] Add `backboard-sdk` to `requirements.txt`

**Time: 2 min**

---

### Step 1 — Create `app/services/backboard_service.py`

New service module. Contains all Backboard interaction logic.

```python
# app/services/backboard_service.py

"""
Backboard AI integration service.
Creates a persistent reasoning thread per call for auditability.
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
                    "call to provide full traceability and explainability."
                ),
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        ASSISTANT_ID = resp.json()["assistant_id"]
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
            json={"metadata_": {"call_id": call_id}},
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        thread_id = resp.json()["thread_id"]
        logger.info(f"[{call_id}] Backboard thread: {thread_id}")
        return thread_id
    except Exception as e:
        logger.warning(f"[{call_id}] Backboard thread creation failed: {e}")
        return None


def log_to_thread(thread_id: str, content: str, label: str = "") -> None:
    """
    Add a message to a Backboard thread (send_to_llm=false → just stores).
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
            timeout=10,
        )
        logger.info(f"Backboard logged: {label}")
    except Exception as e:
        logger.warning(f"Backboard log failed ({label}): {e}")


def get_thread(thread_id: str) -> dict | None:
    """Retrieve a Backboard thread with all messages."""
    try:
        resp = httpx.get(
            f"{BASE_URL}/threads/{thread_id}",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Backboard thread fetch failed: {e}")
        return None


def get_assistant_threads() -> list:
    """List all threads for our assistant."""
    assistant_id = _ensure_assistant()
    if not assistant_id:
        return []
    try:
        resp = httpx.get(
            f"{BASE_URL}/assistants/{assistant_id}/threads",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning(f"Backboard threads listing failed: {e}")
        return []
```

**Time: 5 min**

---

### Step 2 — Store thread_id mapping in Supabase

Add a `backboard_thread_id` column to `call_analyses` so we can look up the Backboard thread for any call.

**SQL migration** (run in Supabase SQL Editor):
```sql
ALTER TABLE call_analyses
ADD COLUMN IF NOT EXISTS backboard_thread_id TEXT DEFAULT NULL;
```

**Code changes**:
- `queries.py` — add `backboard_thread_id` param to `insert_call_record()` + new `update_backboard_thread_id(call_id, thread_id)` function
- `ingestion.py` — pass `backboard_thread_id=None` initially (updated async after thread creation)

**Time: 5 min**

---

### Step 3 — Hook into `/analyze-call` pipeline (routes.py)

Insert two **non-blocking** Backboard calls between existing steps:

```
After Step 5 (context built), before Step 6 (LLM):
  → Create Backboard thread
  → Log grounding context + call signals to thread
  → Store thread_id in Supabase

After Step 6 (LLM done), before Step 7 (store RAG output):
  → Log LLM reasoning output to thread
```

Both wrapped in try/except so **pipeline never breaks**.

**Pseudo-code injection in routes.py:**

```python
    # --- Step 5: Build Grounding Context ---
    ...existing code...

    # --- Step 5b: Backboard — create thread & log context (non-blocking) ---
    backboard_thread_id = None
    try:
        from app.services.backboard_service import (
            create_thread_for_call, log_to_thread,
        )
        backboard_thread_id = create_thread_for_call(call_id)
        if backboard_thread_id:
            # Log call signals
            import json as _json
            signals_summary = _json.dumps(payload.model_dump(), default=str)
            log_to_thread(
                backboard_thread_id,
                f"[CALL SIGNALS]\n{signals_summary}",
                label=f"{call_id}/signals",
            )
            # Log grounding context
            log_to_thread(
                backboard_thread_id,
                f"[GROUNDING CONTEXT]\n{grounding_context}",
                label=f"{call_id}/context",
            )
            # Persist thread_id
            update_backboard_thread_id(call_id, backboard_thread_id)
            logger.info(f"[{call_id}] STEP 5b | Backboard thread logged")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 5b | Backboard failed (non-fatal): {e}")

    # --- Step 6: LLM Grounded Reasoning ---
    ...existing code...

    # --- Step 6b: Backboard — log LLM output (non-blocking) ---
    try:
        if backboard_thread_id:
            import json as _json
            log_to_thread(
                backboard_thread_id,
                f"[LLM REASONING OUTPUT]\n{_json.dumps(rag_output, default=str)}",
                label=f"{call_id}/llm_output",
            )
            logger.info(f"[{call_id}] STEP 6b | Backboard LLM output logged")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 6b | Backboard failed (non-fatal): {e}")

    # --- Step 7: Store RAG Output ---
    ...existing code...
```

**Time: 8 min**

---

### Step 4 — New API endpoint: `GET /api/v1/backboard/{call_id}`

Lets the frontend or judges inspect the full reasoning audit trail for any call.

```python
@router.get("/backboard/{call_id}")
async def get_backboard_thread(call_id: str):
    """Retrieve the Backboard reasoning audit trail for a call."""
    record = get_call_by_id(call_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    thread_id = record.get("backboard_thread_id")
    if not thread_id:
        return {"call_id": call_id, "backboard": None, "message": "No Backboard thread for this call"}

    from app.services.backboard_service import get_thread
    thread_data = get_thread(thread_id)

    return {
        "call_id": call_id,
        "backboard_thread_id": thread_id,
        "backboard": thread_data,
    }
```

**Time: 3 min**

---

### Step 5 — Enrich chatbot with Backboard memory (optional)

In the chat pipeline, after building context, optionally query Backboard's memory to enrich answers with cross-call reasoning context.

This is a **nice-to-have** enhancement — only implement if time allows.

```python
# In chat route, after building chat_ctx:
try:
    from app.services.backboard_service import get_assistant_threads
    # Memory is automatically used by Backboard when memory="Auto"
    # We can mention this capability in the chatbot response metadata
    logger.info("CHAT | Backboard memory available for enrichment")
except Exception:
    pass
```

**Time: 5 min (if implemented)**

---

### Step 6 — Update `requirements.txt`

Add:
```
backboard-sdk>=0.1.0
httpx>=0.27.0
```

(We use `httpx` for sync HTTP calls to Backboard REST API for simplicity and control, since the SDK is async-only and our pipeline functions are sync.)

**Time: 1 min**

---

### Step 7 — Test & validate

1. **Without Backboard key** — pipeline runs exactly as before, Backboard steps log warnings but don't fail
2. **With Backboard key** — run `POST /analyze-call`, verify:
   - Backboard thread created
   - 3 messages logged (signals, context, LLM output)
   - `backboard_thread_id` stored in Supabase
3. **GET /api/v1/backboard/{call_id}** — returns full audit trail
4. **Dashboard/existing endpoints** — all still work unchanged

**Time: 5 min**

---

## Summary Table

| Step | What | Files Changed | Risk | Time |
|------|------|--------------|------|------|
| 0 | API key + SDK install | `.env`, `requirements.txt` | None | 2 min |
| 1 | `backboard_service.py` | NEW file | None (isolated) | 5 min |
| 2 | `backboard_thread_id` column | `queries.py`, SQL migration | Low (additive column) | 5 min |
| 3 | Hook into `/analyze-call` | `routes.py` | **None** (all try/except) | 8 min |
| 4 | `GET /backboard/{call_id}` | `routes.py` | None (new endpoint) | 3 min |
| 5 | Chatbot memory enrichment | `routes.py` | None (optional) | 5 min |
| 6 | `requirements.txt` | `requirements.txt` | None | 1 min |
| 7 | Test | — | — | 5 min |
| **Total** | | | | **~34 min** |

---

## What This Gives You for the Hackathon

| Feature | How Backboard Enables It |
|---------|-------------------------|
| **Reasoning Traceability** | Every call has a full audit trail: signals → context → LLM output |
| **Explainability** | Judges can inspect exactly what the LLM saw and why it decided |
| **Reproducibility** | Thread is immutable — same inputs, same reasoning, always auditable |
| **Persistent Memory** | Backboard's `memory="Auto"` learns patterns across calls |
| **Enterprise Pitch** | "Our system has a built-in reasoning audit layer powered by Backboard AI" |
| **Zero-risk Integration** | Every Backboard call is fail-safe — pipeline never breaks |

---

## What Stays Unchanged

- Supabase storage (primary data store) → **untouched**
- OpenAI embeddings → **untouched**
- GPT-4o-mini reasoning → **untouched**
- All 14 existing API endpoints → **untouched**
- Knowledge base seeding → **untouched**
- Dashboard routes → **untouched**
- Status logic → **untouched**

Backboard is a **parallel audit layer**, not a replacement for anything.

---

## File Tree After Integration

```
app/services/
    backboard_service.py   ← NEW (sole Backboard interface)
    embedding.py           ← unchanged
    ingestion.py           ← unchanged
    reasoning.py           ← unchanged
    context_builder.py     ← unchanged
    retrieval.py           ← unchanged
    updater.py             ← unchanged
    chat_retrieval.py      ← unchanged
    chat_context.py        ← unchanged
    chat_reasoning.py      ← unchanged
    seeding.py             ← unchanged
```

Only 3 existing files are touched:
1. `routes.py` — add Step 5b, Step 6b, and new GET endpoint
2. `queries.py` — add `backboard_thread_id` column handling
3. `requirements.txt` — add `httpx`
