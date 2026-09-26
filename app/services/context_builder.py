"""
Context builder service — Step 5: Build Grounding Context.
Constructs a structured text prompt from call signals + retrieved knowledge
to feed into the LLM for grounded reasoning in Step 6.
"""

import logging
from app.models.schemas import CallRiskInput

logger = logging.getLogger("rag.context_builder")


def build_grounding_context(
    payload: CallRiskInput,
    knowledge_chunks: dict,
) -> str:
    """
    Build a structured context string for LLM grounding.

    Combines:
      1. Call signals — NLP insights, risk flags, risk score, call quality
      2. Retrieved knowledge — fraud patterns, compliance rules, risk heuristics

    Args:
        payload: The validated CallRiskInput from the NLP service.
        knowledge_chunks: Dict with fraud_patterns, compliance_docs, risk_heuristics
                          from Step 4 retrieval.

    Returns:
        A formatted string ready to be sent as LLM context.
    """
    logger.info("Building grounding context")

    sections = []

    # ── Section 1: Call Signals ──
    nlp = payload.nlp_insights
    risk = payload.risk_assessment
    signals = payload.risk_signals
    ctx = payload.call_context

    call_section = [
        "=== CALL SIGNALS ===",
        f"Summary: {payload.summary_for_rag}",
        f"Call Language: {ctx.call_language}",
        f"Call Quality: noise={ctx.call_quality.noise_level}, stability={ctx.call_quality.call_stability}, speech={ctx.call_quality.speech_naturalness}",
        f"Speaker Analysis: customer_only={payload.speaker_analysis.customer_only_analysis}, agent_influence={payload.speaker_analysis.agent_influence_detected}",
        f"Intent: {nlp.intent.label} (confidence: {nlp.intent.confidence:.2f}, conditionality: {nlp.intent.conditionality})",
        f"Sentiment: {nlp.sentiment.label} (confidence: {nlp.sentiment.confidence:.2f})",
        f"Obligation Strength: {nlp.obligation_strength}",
        f"Entities: payment_commitment={nlp.entities.payment_commitment}, amount_mentioned={nlp.entities.amount_mentioned}",
        f"Contradictions Detected: {'YES' if nlp.contradictions_detected else 'NO'}",
        f"Audio Flags: {', '.join(signals.audio_trust_flags) if signals.audio_trust_flags else 'none'}",
        f"Behavioral Flags: {', '.join(signals.behavioral_flags) if signals.behavioral_flags else 'none'}",
        f"Risk Score: {risk.risk_score} | Fraud Likelihood: {risk.fraud_likelihood} | Confidence: {risk.confidence:.2f}",
    ]
    sections.append("\n".join(call_section))

    # ── Section 2: Matched Fraud Patterns ──
    fraud_patterns = knowledge_chunks.get("fraud_patterns", [])
    if fraud_patterns:
        fraud_section = ["=== MATCHED FRAUD PATTERNS ==="]
        for i, doc in enumerate(fraud_patterns, 1):
            sim = doc.get("similarity", 0)
            fraud_section.append(f"[{i}] ({sim:.2f}) {doc['title']}")
            fraud_section.append(f"    {doc['content']}")
            fraud_section.append("")
        sections.append("\n".join(fraud_section))
    else:
        sections.append("=== MATCHED FRAUD PATTERNS ===\nNo matching fraud patterns found.")

    # ── Section 3: Compliance Guidance ──
    compliance_docs = knowledge_chunks.get("compliance_docs", [])
    if compliance_docs:
        comp_section = ["=== COMPLIANCE GUIDANCE ==="]
        for i, doc in enumerate(compliance_docs, 1):
            sim = doc.get("similarity", 0)
            comp_section.append(f"[{i}] ({sim:.2f}) {doc['title']}")
            comp_section.append(f"    {doc['content']}")
            comp_section.append("")
        sections.append("\n".join(comp_section))
    else:
        sections.append("=== COMPLIANCE GUIDANCE ===\nNo matching compliance guidance found.")

    # ── Section 4: Risk Heuristics ──
    risk_heuristics = knowledge_chunks.get("risk_heuristics", [])
    if risk_heuristics:
        heuristic_section = ["=== RISK HEURISTICS ==="]
        for i, doc in enumerate(risk_heuristics, 1):
            sim = doc.get("similarity", 0)
            heuristic_section.append(f"[{i}] ({sim:.2f}) {doc['title']}")
            heuristic_section.append(f"    {doc['content']}")
            heuristic_section.append("")
        sections.append("\n".join(heuristic_section))
    else:
        sections.append("=== RISK HEURISTICS ===\nNo matching risk heuristics found.")

    context = "\n\n".join(sections)
    logger.info(f"Context built | {len(context)} chars | {context.count(chr(10))+1} lines")

    return context
