"""
Chat context builder — assembles retrieved knowledge, call history,
conversation history, and the current question into a structured
prompt for the chatbot LLM.
"""

import logging

logger = logging.getLogger("rag.chat_context")

MAX_HISTORY_MESSAGES = 10


def build_chat_context(
    question: str,
    knowledge_docs: list[dict],
    call_docs: list[dict],
    conversation_history: list[dict],
) -> str:
    """
    Build a structured context string for the chatbot LLM.

    Args:
        question: The user's current question.
        knowledge_docs: Retrieved knowledge documents from vector search.
        call_docs: Retrieved call records from vector search.
        conversation_history: Previous messages [{role, content}, ...].

    Returns:
        A formatted context string ready for the LLM.
    """
    sections = []

    # --- Section 1: Retrieved Knowledge ---
    if knowledge_docs:
        lines = ["=== RETRIEVED KNOWLEDGE ==="]
        for i, doc in enumerate(knowledge_docs, 1):
            sim = doc.get("similarity", 0)
            cat = doc.get("category", "unknown")
            title = doc.get("title", "Untitled")
            content = doc.get("content", "")
            doc_id = doc.get("doc_id", "?")
            lines.append(f"[{i}] ({cat}, sim={sim:.2f}) [{doc_id}] {title}")
            lines.append(f"    {content}")
            lines.append("")
        sections.append("\n".join(lines))

    # --- Section 2: Call History ---
    if call_docs:
        lines = ["=== MATCHED CALL ANALYSES ==="]
        for i, call in enumerate(call_docs, 1):
            cid = call.get("call_id", "?")
            risk = call.get("risk_score", "?")
            fraud = call.get("fraud_likelihood", "?")
            assessment = call.get("grounded_assessment", "pending")
            sim = call.get("similarity", 0)
            summary = call.get("summary_for_rag", "")
            is_direct = call.get("_lookup", False)
            lookup_tag = " [DIRECT LOOKUP]" if is_direct else ""

            lines.append(f"[{i}] {cid} | risk={risk} | fraud={fraud} | assessment={assessment} | sim={sim:.2f}{lookup_tag}")
            lines.append(f"    Summary: {summary}")

            # If this is a direct lookup, include richer details
            if is_direct and "_full_record" in call:
                rec = call["_full_record"]
                if isinstance(rec.get("rag_output"), dict):
                    rag = rec["rag_output"]
                    lines.append(f"    Explanation: {rag.get('explanation', 'N/A')}")
                    lines.append(f"    Action: {rag.get('recommended_action', 'N/A')}")
                    lines.append(f"    Confidence: {rag.get('confidence', 'N/A')}")
                    patterns = rag.get("matched_patterns", [])
                    if patterns:
                        lines.append(f"    Matched Patterns: {', '.join(patterns)}")
                    flags = rag.get("regulatory_flags", [])
                    if flags:
                        lines.append(f"    Regulatory Flags: {', '.join(flags)}")
                if isinstance(rec.get("nlp_insights"), dict):
                    nlp = rec["nlp_insights"]
                    lines.append(f"    Intent: {nlp.get('intent', {}).get('label', '?')} (confidence={nlp.get('intent', {}).get('confidence', '?')})")
                    lines.append(f"    Sentiment: {nlp.get('sentiment', {}).get('label', '?')}")

            lines.append("")
        sections.append("\n".join(lines))

    # --- Section 3: Conversation History (last N messages) ---
    history = conversation_history[-MAX_HISTORY_MESSAGES:]
    if history:
        lines = ["=== CONVERSATION HISTORY ==="]
        for msg in history:
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        lines.append("")
        sections.append("\n".join(lines))

    # --- Section 4: Current Question ---
    sections.append(f"=== CURRENT QUESTION ===\n{question}")

    context = "\n\n".join(sections)
    logger.info(f"Chat context built | {len(context)} chars | knowledge={len(knowledge_docs)} calls={len(call_docs)} history={len(history)}")
    return context
