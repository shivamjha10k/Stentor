"""
API routes for the RAG service.
Steps 1-9: Full pipeline from validation to grounded assessment + document extraction.
"""

import logging
import math
import json as _json
import re
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from app.models.schemas import (
    CallRiskInput, CallAnalysisResponse,
    ChatRequest, ChatResponse, ChatSource, ChatMetadata,
    DashboardStats, RecentActivityItem, PatternCount, StatusUpdate, PaginationMeta,
    CallDocumentResponse,
)
from app.utils.id_generator import generate_call_id, generate_call_timestamp
from app.services.ingestion import store_call_record
from app.services.embedding import embed_text
from app.services.retrieval import retrieve_knowledge_chunks
from app.services.context_builder import build_grounding_context
from app.services.reasoning import run_grounded_reasoning
from app.services.updater import store_rag_output
from app.services.seeding import seed_knowledge_base
from app.services.chat_retrieval import retrieve_for_chat, extract_call_ids, lookup_calls_by_id
from app.services.chat_context import build_chat_context
from app.services.chat_reasoning import run_chat_reasoning
from app.services.extraction_service import extract_call_document
from app.services.pdf_generator import generate_call_document_pdf
from app.services.backboard_service import (
    create_thread_for_call, log_to_thread, get_thread,
    get_thread_messages, get_assistant_threads, query_memory, query_thread,
)
from app.db.queries import (
    get_call_by_id, get_knowledge_count, update_call_embedding,
    get_dashboard_stats, get_recent_activity, get_top_patterns,
    get_active_cases, update_call_status, get_calls_paginated,
    update_backboard_thread_id, get_recent_calls,
    insert_call_document, get_call_document, search_call_documents,
    get_call_documents_paginated, get_financial_summary,
)

def status_from_risk_score(score: int) -> str:
    """Derive initial case status from NLP risk_score."""
    if score < 30:
        return "resolved"
    elif score <= 50:
        return "in_review"
    else:
        return "escalated"

logger = logging.getLogger("rag.routes")

router = APIRouter(prefix="/api/v1", tags=["RAG Pipeline"])


@router.post("/analyze-call")
async def analyze_call(payload: CallRiskInput):
    """
    Main pipeline endpoint.
    Receives structured risk JSON from NLP service,
    grounds it against knowledge base, returns assessment.

    Current implementation: Step 1 (Receive & Validate) only.
    Steps 2-8 will be wired in as services are built.
    """

    # --- Pre-check: Knowledge base must be seeded ---
    try:
        kb_count = get_knowledge_count()
    except Exception:
        kb_count = 0
    if kb_count == 0:
        raise HTTPException(
            status_code=503,
            detail="Knowledge base is empty. Run POST /api/v1/knowledge/seed first.",
        )

    # --- Step 1: Receive & Validate ---
    # Pydantic already validated the payload at this point.
    # If we reached here, the input is valid.

    call_id = generate_call_id()
    call_timestamp = generate_call_timestamp()

    logger.info(f"[{call_id}] STEP 1 | Validated | risk={payload.risk_assessment.risk_score} fraud={payload.risk_assessment.fraud_likelihood}")

    # --- Step 2: Store Call Record ---
    try:
        ingestion_result = store_call_record(
            call_id=call_id,
            call_timestamp=call_timestamp,
            payload=payload,
        )
        logger.info(f"[{call_id}] STEP 2 | Stored in {ingestion_result['table']}")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 2 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store call record: {str(e)}",
        )

    # --- Step 3: Embed summary_for_rag ---
    try:
        query_embedding = embed_text(payload.summary_for_rag)
        logger.info(f"[{call_id}] STEP 3 | Embedded summary | dim={len(query_embedding)}")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 3 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to embed summary: {str(e)}",
        )

    # --- Step 3b: Store embedding for chatbot vector search ---
    try:
        update_call_embedding(call_id, query_embedding)
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 3b | Embedding storage failed (non-fatal): {str(e)}")

    # --- Step 4: Retrieve Knowledge Chunks ---
    try:
        knowledge_chunks = retrieve_knowledge_chunks(query_embedding)
        logger.info(f"[{call_id}] STEP 4 | Retrieved fraud={len(knowledge_chunks['fraud_patterns'])} compliance={len(knowledge_chunks['compliance_docs'])} heuristic={len(knowledge_chunks['risk_heuristics'])}")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 4 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve knowledge: {str(e)}",
        )

    # --- Step 5: Build Grounding Context ---
    try:
        grounding_context = build_grounding_context(
            payload=payload,
            knowledge_chunks=knowledge_chunks,
        )
        logger.info(f"[{call_id}] STEP 5 | Context built | {len(grounding_context)} chars")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 5 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build grounding context: {str(e)}",
        )

    # --- Step 5b: Backboard — create thread & log context (non-blocking) ---
    backboard_thread_id = None
    try:
        backboard_thread_id = create_thread_for_call(call_id)
        if backboard_thread_id:
            # Log call signals
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
            logger.info(f"[{call_id}] STEP 5b | Backboard thread created & logged")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 5b | Backboard failed (non-fatal): {e}")

    # --- Step 6: LLM Grounded Reasoning ---
    try:
        rag_output = run_grounded_reasoning(grounding_context)
        logger.info(f"[{call_id}] STEP 6 | LLM done | assessment={rag_output['grounded_assessment']} action={rag_output['recommended_action']}")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 6 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"LLM reasoning failed: {str(e)}",
        )

    # --- Step 6b: Backboard — log LLM output (non-blocking) ---
    try:
        if backboard_thread_id:
            log_to_thread(
                backboard_thread_id,
                f"[LLM REASONING OUTPUT]\n{_json.dumps(rag_output, default=str)}",
                label=f"{call_id}/llm_output",
            )
            logger.info(f"[{call_id}] STEP 6b | Backboard LLM output logged")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 6b | Backboard failed (non-fatal): {e}")

    # --- Step 7: Store RAG Output ---
    try:
        update_result = store_rag_output(call_id=call_id, rag_output=rag_output)
        logger.info(f"[{call_id}] STEP 7 | rag_output stored")
    except Exception as e:
        logger.error(f"[{call_id}] STEP 7 | FAILED: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store RAG output: {str(e)}",
        )

    # --- Step 7b: Set initial status from risk_score ---
    try:
        initial_status = status_from_risk_score(payload.risk_assessment.risk_score)
        update_call_status(call_id, initial_status)
        logger.info(f"[{call_id}] STEP 7b | status={initial_status} (risk_score={payload.risk_assessment.risk_score})")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 7b | Status update failed (non-fatal): {str(e)}")

    # --- Step 9: Extract Call Document (non-fatal) ---
    document_generated = False
    try:
        doc_data = extract_call_document(
            call_id=call_id,
            payload=payload.model_dump(),
            rag_output=rag_output,
        )
        # Embed the call summary for document search
        try:
            doc_embedding = embed_text(doc_data.get("call_summary", ""))
        except Exception:
            doc_embedding = None
        # Store the document
        doc_id = f"cdoc_{call_id}"
        insert_call_document(
            doc_id=doc_id,
            call_id=call_id,
            document_data=doc_data,
            embedding=doc_embedding,
        )
        document_generated = True
        logger.info(f"[{call_id}] STEP 9 | Call document extracted | tokens={doc_data.get('extraction_tokens', 0)}")
    except Exception as e:
        logger.warning(f"[{call_id}] STEP 9 | Document extraction failed (non-fatal): {e}")

    # --- Step 10: Return Final Response ---
    logger.info(f"[{call_id}] DONE | Pipeline complete")
    return {
        "call_id": call_id,
        "call_timestamp": call_timestamp.isoformat(),
        "input_risk_assessment": payload.risk_assessment.model_dump(),
        "rag_output": rag_output,
        "backboard_thread_id": backboard_thread_id,
        "document_generated": document_generated,
    }


@router.post("/knowledge/seed")
async def seed_knowledge():
    """
    Seed the knowledge base from JSON files in knowledge/ directory.
    Embeds each document and upserts into knowledge_embeddings table.
    Run ONCE before using the pipeline.
    """
    logger.info("Seeding knowledge base...")
    try:
        result = seed_knowledge_base()
        logger.info(f"Seeded {result['documents_processed']} docs | {result['by_category']}")
    except Exception as e:
        logger.error(f"Seeding failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge seeding failed: {str(e)}",
        )
    return result


@router.get("/knowledge/status")
async def knowledge_status():
    """Check how many documents are in the knowledge base."""
    try:
        count = get_knowledge_count()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check knowledge base: {str(e)}",
        )
    return {"knowledge_documents": count, "ready": count > 0}


@router.get("/call/{call_id}")
async def get_call(call_id: str):
    """
    Get a single call analysis by call_id.
    Returns the full call record including rag_output (if available).
    """
    logger.info(f"Fetching call: {call_id}")
    try:
        record = get_call_by_id(call_id)
    except Exception as e:
        logger.error(f"DB error fetching {call_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}",
        )

    if record is None:
        logger.warning(f"Call not found: {call_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Call not found: {call_id}",
        )

    return record


# ============================================================
# Chatbot Endpoint
# ============================================================

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Knowledge query chatbot.
    Accepts a natural language question, searches knowledge base + call history
    via vector similarity, and returns a grounded answer with citations.
    """
    # --- Pre-check: Knowledge base must be seeded ---
    if request.filters.search_knowledge:
        try:
            kb_count = get_knowledge_count()
        except Exception:
            kb_count = 0
        if kb_count == 0:
            raise HTTPException(
                status_code=503,
                detail="Knowledge base is empty. Run POST /api/v1/knowledge/seed first.",
            )

    logger.info(f"CHAT | Question: {request.question[:80]}...")

    # --- Detect temporal query (e.g., "last 5 calls", "past 10 days") ---
    temporal_calls = []
    backboard_memory_answer = None
    temporal_match = re.search(
        r'(?:last|past|recent)\s+(\d+)\s*(?:calls?|records?|cases?|days?|analyses?)',
        request.question,
        re.IGNORECASE,
    )
    if temporal_match:
        num = int(temporal_match.group(1))
        # Determine if it's days-based or count-based
        is_days = bool(re.search(r'days?', temporal_match.group(0), re.IGNORECASE))
        if is_days:
            temporal_calls = get_recent_calls(days=num, limit=10)
        else:
            temporal_calls = get_recent_calls(days=90, limit=num)
        logger.info(f"CHAT | Temporal query detected: fetched {len(temporal_calls)} calls")

        # Query Backboard memory for cross-call insights
        try:
            backboard_memory_answer = query_memory(request.question)
            if backboard_memory_answer:
                logger.info("CHAT | Backboard memory enrichment retrieved")
        except Exception as e:
            logger.warning(f"CHAT | Backboard memory query failed (non-fatal): {e}")

    # --- Detect call IDs in question for direct lookup ---
    mentioned_call_ids = extract_call_ids(request.question)
    direct_lookups = []
    if mentioned_call_ids:
        direct_lookups = lookup_calls_by_id(mentioned_call_ids)
        logger.info(f"CHAT | Direct call lookup: {len(direct_lookups)}/{len(mentioned_call_ids)} found")

    # --- Step 1: Embed the question ---
    try:
        query_embedding = embed_text(request.question)
        logger.info(f"CHAT | Embedded question | dim={len(query_embedding)}")
    except Exception as e:
        logger.error(f"CHAT | Embedding failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to embed question: {str(e)}")

    # --- Step 2: Retrieve relevant documents ---
    try:
        retrieved = retrieve_for_chat(
            query_embedding=query_embedding,
            search_knowledge_flag=request.filters.search_knowledge,
            search_calls_flag=request.filters.search_calls,
            categories=request.filters.categories,
            knowledge_limit=request.filters.knowledge_limit,
            calls_limit=request.filters.calls_limit,
        )
        logger.info(f"CHAT | Retrieved knowledge={len(retrieved['knowledge_docs'])} calls={len(retrieved['call_docs'])}")
    except Exception as e:
        logger.error(f"CHAT | Retrieval failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {str(e)}")

    # Merge direct lookups into call_docs (avoid duplicates)
    existing_call_ids = {c.get("call_id") for c in retrieved["call_docs"]}
    for lookup in direct_lookups:
        if lookup["call_id"] not in existing_call_ids:
            retrieved["call_docs"].append(lookup)

    # --- Step 3: Build chat context ---
    history_dicts = [msg.model_dump() for msg in request.conversation_history]

    # Merge temporal calls into call_docs if any
    if temporal_calls:
        existing_ids = {c.get("call_id") for c in retrieved["call_docs"]}
        for tc in temporal_calls:
            if tc["call_id"] not in existing_ids:
                ra = tc.get("risk_assessment") or {}
                ro = tc.get("rag_output") or {}
                retrieved["call_docs"].append({
                    "call_id": tc["call_id"],
                    "risk_score": ra.get("risk_score", 0),
                    "fraud_likelihood": ra.get("fraud_likelihood", "unknown"),
                    "grounded_assessment": ro.get("grounded_assessment", "pending"),
                    "summary_for_rag": tc.get("summary_for_rag", ""),
                    "similarity": 1.0,  # direct temporal fetch
                })

    chat_ctx = build_chat_context(
        question=request.question,
        knowledge_docs=retrieved["knowledge_docs"],
        call_docs=retrieved["call_docs"],
        conversation_history=history_dicts,
    )

    # Append Backboard memory insight if available
    if backboard_memory_answer:
        chat_ctx += f"\n\n=== BACKBOARD AI MEMORY INSIGHT ===\n{backboard_memory_answer}\n"

    # --- Step 4: LLM answer generation ---
    try:
        llm_result = run_chat_reasoning(chat_ctx)
        logger.info(f"CHAT | LLM done | {llm_result['tokens_used']} tokens")
    except Exception as e:
        logger.error(f"CHAT | LLM failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"LLM reasoning failed: {str(e)}")

    # --- Step 5: Build sources list ---
    sources = []
    referenced_ids = set(llm_result.get("source_ids", []))

    for doc in retrieved["knowledge_docs"]:
        sources.append(ChatSource(
            type="knowledge",
            doc_id=doc.get("doc_id", ""),
            category=doc.get("category", ""),
            title=doc.get("title", ""),
            similarity=round(doc.get("similarity", 0), 4),
        ))

    for call in retrieved["call_docs"]:
        sources.append(ChatSource(
            type="call",
            doc_id=call.get("call_id", ""),
            category="call_analysis",
            title=f"Risk={call.get('risk_score', '?')} | {call.get('fraud_likelihood', '?')}",
            similarity=round(call.get("similarity", 0), 4),
        ))

    # --- Step 6: Return response ---
    return ChatResponse(
        answer=llm_result["answer"],
        sources=sources,
        metadata=ChatMetadata(
            knowledge_docs_searched=len(retrieved["knowledge_docs"]),
            calls_searched=len(retrieved["call_docs"]),
            model=llm_result["model"],
            tokens_used=llm_result["tokens_used"],
        ),
    )


# ============================================================
# Dashboard Endpoints
# ============================================================

@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats():
    """KPI numbers for the hero stats row + risk distribution."""
    try:
        stats = get_dashboard_stats()
    except Exception as e:
        logger.error(f"DASHBOARD | stats failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")

    return DashboardStats(
        total_calls=stats.get("total_calls", 0),
        total_calls_today=stats.get("total_calls_today", 0),
        high_risk_count=stats.get("high_risk_count", 0),
        medium_risk_count=stats.get("medium_risk_count", 0),
        low_risk_count=stats.get("low_risk_count", 0),
        avg_risk_score=stats.get("avg_risk_score") or 0.0,
        resolution_rate=stats.get("resolution_rate") or 0.0,
        status_breakdown=stats.get("status_breakdown") or {},
    )


@router.get("/dashboard/recent-activity")
async def dashboard_recent_activity(
    limit: int = Query(default=5, ge=1, le=20),
):
    """Last N calls with outcomes for the activity timeline."""
    try:
        items = get_recent_activity(limit)
    except Exception as e:
        logger.error(f"DASHBOARD | recent-activity failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch recent activity: {str(e)}")
    return {"recent_activity": items}


@router.get("/dashboard/top-patterns")
async def dashboard_top_patterns(
    limit: int = Query(default=10, ge=1, le=20),
):
    """Aggregated pattern frequency across all calls."""
    try:
        patterns = get_top_patterns(limit)
    except Exception as e:
        logger.error(f"DASHBOARD | top-patterns failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch patterns: {str(e)}")
    return {"patterns": patterns}


@router.get("/dashboard/active-cases")
async def dashboard_active_cases(
    limit: int = Query(default=3, ge=1, le=10),
):
    """Top N highest-risk unresolved cases."""
    try:
        cases, total_active = get_active_cases(limit)
    except Exception as e:
        logger.error(f"DASHBOARD | active-cases failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch active cases: {str(e)}")
    return {"active_cases": cases, "total_active": total_active}


@router.get("/dashboard/health")
async def dashboard_health():
    """System health indicator for dashboard status badge."""
    db_ok = False
    kb_count = 0
    embedding_ok = False

    # Check database
    try:
        kb_count = get_knowledge_count()
        db_ok = True
    except Exception:
        pass

    # Check embedding service
    try:
        embed_text("health check")
        embedding_ok = True
    except Exception:
        pass

    overall = "healthy" if (db_ok and kb_count > 0 and embedding_ok) else "degraded"
    return {
        "status": overall,
        "components": {
            "database": db_ok,
            "knowledge_base": {"ready": kb_count > 0, "doc_count": kb_count},
            "embedding_service": embedding_ok,
        },
    }


# ============================================================
# Case Management Endpoints
# ============================================================

@router.patch("/call/{call_id}/status")
async def patch_call_status(call_id: str, body: StatusUpdate):
    """Update case status (e.g., mark as resolved after review)."""
    logger.info(f"PATCH status | {call_id} → {body.status}")

    # Check call exists
    existing = get_call_by_id(call_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    try:
        update_call_status(call_id, body.status)
    except Exception as e:
        logger.error(f"PATCH status failed for {call_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update status: {str(e)}")

    return {"call_id": call_id, "status": body.status, "updated": True}


@router.get("/calls")
async def list_calls(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    status: str | None = Query(default=None),
    risk: str | None = Query(default=None),
    sort: str = Query(default="recent"),
):
    """Paginated call listing with optional filters."""
    # Validate filter values
    valid_statuses = {"open", "in_review", "escalated", "resolved"}
    if status and status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {valid_statuses}")

    valid_risks = {"high_risk", "medium_risk", "low_risk"}
    if risk and risk not in valid_risks:
        raise HTTPException(status_code=422, detail=f"Invalid risk. Allowed: {valid_risks}")

    try:
        calls, total = get_calls_paginated(
            page=page, limit=limit,
            status_filter=status, risk_filter=risk, sort=sort,
        )
    except Exception as e:
        logger.error(f"GET /calls failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch calls: {str(e)}")

    total_pages = math.ceil(total / limit) if total > 0 else 1
    return {
        "calls": calls,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
        },
    }


# ============================================================
# Backboard AI — Reasoning Audit & Memory Endpoints
# ============================================================

@router.get("/backboard/threads/all")
async def list_all_backboard_threads():
    """
    List all Backboard reasoning threads (for admin/debug view).
    Each thread corresponds to one analyzed call.
    """
    threads = get_assistant_threads()
    return {
        "total_threads": len(threads),
        "threads": threads,
    }


@router.post("/backboard/memory/query")
async def query_backboard_memory(body: dict):
    """
    Query Backboard's cross-call memory.
    Backboard's memory layer learns patterns across ALL analyzed calls.

    Body: {"question": "What are the most common fraud patterns in the last week?"}
    """
    question = body.get("question")
    if not question:
        raise HTTPException(status_code=422, detail="'question' field is required")

    answer = query_memory(question)
    if answer is None:
        raise HTTPException(status_code=502, detail="Backboard memory query failed")

    return {
        "question": question,
        "answer": answer,
        "source": "backboard_memory",
    }


@router.get("/backboard/{call_id}")
async def get_backboard_audit_trail(call_id: str):
    """
    Retrieve the full Backboard reasoning audit trail for a call.
    Shows the complete chain: call signals → grounding context → LLM output.
    """
    record = get_call_by_id(call_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    thread_id = record.get("backboard_thread_id")
    if not thread_id:
        return {
            "call_id": call_id,
            "backboard_thread_id": None,
            "backboard": None,
            "message": "No Backboard audit trail for this call (processed before Backboard integration)",
        }

    thread_data = get_thread(thread_id)
    messages = get_thread_messages(thread_id)

    return {
        "call_id": call_id,
        "backboard_thread_id": thread_id,
        "thread": thread_data,
        "messages": messages,
        "audit_trail_available": True,
    }


@router.post("/backboard/{call_id}/query")
async def query_backboard_thread(call_id: str, body: dict):
    """
    Ask a question about a specific call's reasoning via Backboard.
    The LLM has full context of the call signals, grounding context, and reasoning output.

    Body: {"question": "Why was this call flagged as high risk?"}
    """
    question = body.get("question")
    if not question:
        raise HTTPException(status_code=422, detail="'question' field is required")

    record = get_call_by_id(call_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    thread_id = record.get("backboard_thread_id")
    if not thread_id:
        raise HTTPException(
            status_code=404,
            detail="No Backboard thread for this call. Cannot query reasoning.",
        )

    answer = query_thread(thread_id, question)
    if answer is None:
        raise HTTPException(status_code=502, detail="Backboard query failed")

    return {
        "call_id": call_id,
        "question": question,
        "answer": answer,
        "backboard_thread_id": thread_id,
    }


# ============================================================
# Call Document Extraction Endpoints
# ============================================================

@router.get("/call/{call_id}/document")
async def get_call_doc(call_id: str):
    """
    Get the full extracted document for a specific call.
    Includes financial data, entities, commitments, timeline, etc.
    """
    # Verify call exists
    call_record = get_call_by_id(call_id)
    if not call_record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    doc = get_call_document(call_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"No document for call {call_id}. Use POST /call/{call_id}/document/regenerate to generate one.",
        )

    return {
        "call_id": call_id,
        "generated_at": doc.get("generated_at"),
        "document": {
            "call_summary": doc.get("call_summary"),
            "call_purpose": doc.get("call_purpose"),
            "call_outcome": doc.get("call_outcome"),
            "financial_data": doc.get("financial_data", {}),
            "entities": doc.get("entities", {}),
            "commitments": doc.get("commitments", []),
            "key_discussion_points": doc.get("key_discussion_points", []),
            "compliance_notes": doc.get("compliance_notes", []),
            "risk_flags": doc.get("risk_flags", []),
            "action_items": doc.get("action_items", []),
            "call_timeline": doc.get("call_timeline", []),
        },
        "extraction_metadata": {
            "model": doc.get("extraction_model", "unknown"),
            "tokens_used": doc.get("extraction_tokens", 0),
            "version": doc.get("extraction_version", "v1"),
        },
    }


@router.get("/call/{call_id}/document/financial")
async def get_call_financial_data(call_id: str):
    """
    Get only the financial extraction for a specific call.
    Useful for quick financial data lookups.
    """
    call_record = get_call_by_id(call_id)
    if not call_record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    doc = get_call_document(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No document for call {call_id}")

    return {
        "call_id": call_id,
        "financial_data": doc.get("financial_data", {}),
        "commitments": doc.get("commitments", []),
        "action_items": doc.get("action_items", []),
    }


@router.get("/call/{call_id}/document/export")
async def export_call_document(
    call_id: str,
    format: str = Query(default="json", pattern=r"^(json|pdf)$"),
):
    """
    Export a call document as JSON or PDF.
    Query param: ?format=json (default) or ?format=pdf
    """
    call_record = get_call_by_id(call_id)
    if not call_record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    doc = get_call_document(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"No document for call {call_id}")

    if format == "pdf":
        try:
            pdf_bytes = generate_call_document_pdf(
                call_id=call_id,
                document=doc,
                call_data=call_record,
            )
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="call_report_{call_id}.pdf"',
                },
            )
        except Exception as e:
            logger.error(f"PDF generation failed for {call_id}: {e}")
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    # Default: JSON export
    return {
        "call_id": call_id,
        "generated_at": doc.get("generated_at"),
        "call_summary": doc.get("call_summary"),
        "call_purpose": doc.get("call_purpose"),
        "call_outcome": doc.get("call_outcome"),
        "financial_data": doc.get("financial_data", {}),
        "entities": doc.get("entities", {}),
        "commitments": doc.get("commitments", []),
        "key_discussion_points": doc.get("key_discussion_points", []),
        "compliance_notes": doc.get("compliance_notes", []),
        "risk_flags": doc.get("risk_flags", []),
        "action_items": doc.get("action_items", []),
        "call_timeline": doc.get("call_timeline", []),
        "extraction_metadata": {
            "model": doc.get("extraction_model"),
            "tokens_used": doc.get("extraction_tokens", 0),
            "version": doc.get("extraction_version", "v1"),
        },
    }


@router.post("/call/{call_id}/document/regenerate")
async def regenerate_call_document(call_id: str):
    """
    (Re)generate the extracted document for a call.
    Useful for calls processed before document extraction was added,
    or to re-extract after improvements to the extraction prompt.
    """
    call_record = get_call_by_id(call_id)
    if not call_record:
        raise HTTPException(status_code=404, detail=f"Call not found: {call_id}")

    rag_output = call_record.get("rag_output")
    if not rag_output:
        raise HTTPException(
            status_code=422,
            detail=f"Call {call_id} has no RAG output yet. Run analysis first.",
        )

    # Build payload dict from call record
    payload = {
        "call_context": call_record.get("call_context", {}),
        "speaker_analysis": call_record.get("speaker_analysis", {}),
        "nlp_insights": call_record.get("nlp_insights", {}),
        "risk_signals": call_record.get("risk_signals", {}),
        "risk_assessment": call_record.get("risk_assessment", {}),
        "summary_for_rag": call_record.get("summary_for_rag", ""),
        "conversation": call_record.get("conversation", []),
    }

    try:
        doc_data = extract_call_document(
            call_id=call_id,
            payload=payload,
            rag_output=rag_output,
        )
    except Exception as e:
        logger.error(f"Document extraction failed for {call_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    # Embed document summary for search
    try:
        doc_embedding = embed_text(doc_data.get("call_summary", ""))
    except Exception:
        doc_embedding = None

    # Store / upsert
    doc_id = f"cdoc_{call_id}"
    try:
        insert_call_document(
            doc_id=doc_id,
            call_id=call_id,
            document_data=doc_data,
            embedding=doc_embedding,
        )
    except Exception as e:
        logger.error(f"Document storage failed for {call_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to store document: {str(e)}")

    return {
        "call_id": call_id,
        "doc_id": doc_id,
        "regenerated": True,
        "extraction_tokens": doc_data.get("extraction_tokens", 0),
        "call_purpose": doc_data.get("call_purpose"),
        "call_outcome": doc_data.get("call_outcome"),
        "financial_amounts_found": len(doc_data.get("financial_data", {}).get("amounts_mentioned", [])),
        "commitments_found": len(doc_data.get("commitments", [])),
    }


@router.get("/documents")
async def list_documents(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    purpose: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
):
    """Paginated listing of all call documents with optional filters."""
    try:
        docs, total = get_call_documents_paginated(
            page=page, limit=limit,
            purpose_filter=purpose, outcome_filter=outcome,
        )
    except Exception as e:
        logger.error(f"GET /documents failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch documents: {str(e)}")

    total_pages = math.ceil(total / limit) if total > 0 else 1
    return {
        "documents": docs,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": total_pages,
        },
    }


@router.post("/documents/search")
async def search_documents(body: dict):
    """
    Semantic search across all call documents.
    Body: {"query": "calls with payment commitments over 10000", "limit": 5}
    """
    query = body.get("query")
    if not query:
        raise HTTPException(status_code=422, detail="'query' field is required")

    limit = body.get("limit", 5)

    try:
        query_embedding = embed_text(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed query: {str(e)}")

    try:
        results = search_call_documents(query_embedding, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    return {
        "query": query,
        "results": results,
        "total_results": len(results),
    }


@router.get("/dashboard/financial-intelligence")
async def dashboard_financial_intelligence(
    days: int = Query(default=30, ge=1, le=365),
):
    """
    Aggregated financial intelligence across call documents.
    Shows total commitments, outstanding amounts, purpose/outcome breakdowns.
    """
    try:
        summary = get_financial_summary(days=days)
    except Exception as e:
        logger.error(f"DASHBOARD | financial-intelligence failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch financial summary: {str(e)}")

    return {
        "period_days": days,
        "summary": summary,
    }
