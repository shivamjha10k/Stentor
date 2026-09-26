"""
Pydantic schemas for the RAG service.
Defines input contract (from NLP service) and output contract (RAG response).
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ============================================================
# INPUT MODELS (NLP Service → RAG Service)
# ============================================================

class CallQuality(BaseModel):
    noise_level: str = Field(..., description="low | medium | high")
    call_stability: str = Field(..., description="low | medium | high")
    speech_naturalness: str = Field(..., description="natural | suspicious")


class CallContext(BaseModel):
    call_language: str
    call_quality: CallQuality


class SpeakerAnalysis(BaseModel):
    customer_only_analysis: bool
    agent_influence_detected: bool


class IntentInsight(BaseModel):
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    conditionality: str = Field(..., description="low | medium | high")


class SentimentInsight(BaseModel):
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class Entities(BaseModel):
    payment_commitment: Optional[str] = None
    amount_mentioned: Optional[float] = None


class NLPInsights(BaseModel):
    intent: IntentInsight
    sentiment: SentimentInsight
    obligation_strength: str = Field(..., description="strong | moderate | weak")
    entities: Entities
    contradictions_detected: bool


class RiskSignals(BaseModel):
    audio_trust_flags: list[str] = Field(default_factory=list)
    behavioral_flags: list[str] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    risk_score: int = Field(..., ge=0, le=100)
    fraud_likelihood: str = Field(..., description="low | medium | high")
    confidence: float = Field(..., ge=0.0, le=1.0)


class ConversationTurn(BaseModel):
    """A single speaker turn in the call transcript."""
    speaker: str = Field(..., description="AGENT | CUSTOMER")
    text: str


class CallRiskInput(BaseModel):
    """Main input schema — the full payload from NLP service."""
    call_context: CallContext
    speaker_analysis: SpeakerAnalysis
    nlp_insights: NLPInsights
    risk_signals: RiskSignals
    risk_assessment: RiskAssessment
    summary_for_rag: str = Field(..., min_length=10)
    conversation: list[ConversationTurn] = Field(default_factory=list, description="Call transcript as speaker turns")


# ============================================================
# OUTPUT MODELS (RAG Service → Caller)
# ============================================================

class RAGOutput(BaseModel):
    grounded_assessment: str = Field(..., description="high_risk | medium_risk | low_risk")
    explanation: str
    recommended_action: str = Field(
        ...,
        description="auto_clear | flag_for_review | manual_review | escalate_to_compliance"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    regulatory_flags: list[str] = Field(default_factory=list)
    matched_patterns: list[str] = Field(default_factory=list)


class CallAnalysisResponse(BaseModel):
    """Final API response returned to the caller."""
    call_id: str
    call_timestamp: datetime
    input_risk_assessment: RiskAssessment
    rag_output: RAGOutput


# ============================================================
# CHAT MODELS (Knowledge Query Chatbot)
# ============================================================

class ChatMessage(BaseModel):
    """A single message in the conversation history."""
    role: str = Field(..., description="user | assistant")
    content: str = Field(..., min_length=1)


class ChatFilters(BaseModel):
    """Controls which data sources the chatbot searches."""
    search_knowledge: bool = True
    search_calls: bool = False
    categories: list[str] = Field(
        default=["fraud_pattern", "compliance", "risk_heuristic"],
        description="Knowledge categories to search",
    )
    knowledge_limit: int = Field(default=5, ge=1, le=10)
    calls_limit: int = Field(default=3, ge=1, le=10)


class ChatRequest(BaseModel):
    """Input schema for the chatbot endpoint."""
    question: str = Field(..., min_length=5)
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    filters: ChatFilters = Field(default_factory=ChatFilters)


class ChatSource(BaseModel):
    """A single source document cited in the chatbot answer."""
    type: str = Field(..., description="knowledge | call")
    doc_id: str
    category: str
    title: str
    similarity: float


class ChatMetadata(BaseModel):
    """Metadata about the chatbot response."""
    knowledge_docs_searched: int = 0
    calls_searched: int = 0
    model: str
    tokens_used: int = 0


class ChatResponse(BaseModel):
    """Output schema for the chatbot endpoint."""
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    metadata: ChatMetadata


# ============================================================
# DASHBOARD MODELS
# ============================================================

class DashboardStats(BaseModel):
    total_calls: int = 0
    total_calls_today: int = 0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0
    avg_risk_score: float = 0.0
    resolution_rate: float = 0.0
    status_breakdown: dict[str, int] = Field(default_factory=dict)


class RecentActivityItem(BaseModel):
    call_id: str
    call_timestamp: datetime
    status: str
    risk_score: int
    fraud_likelihood: str
    grounded_assessment: str
    recommended_action: str
    summary: str


class PatternCount(BaseModel):
    pattern: str
    count: int


class StatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(open|in_review|escalated|resolved)$")


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int


# ============================================================
# CALL DOCUMENT MODELS (Extracted per-call intelligence)
# ============================================================

class AmountMentioned(BaseModel):
    value: float
    currency: str = "INR"
    context: str = ""


class PaymentCommitment(BaseModel):
    amount: float
    due_date: Optional[str] = None
    type: str = "other"


class EMIDetails(BaseModel):
    amount: float
    frequency: str = "monthly"
    remaining: int = 0


class FinancialData(BaseModel):
    amounts_mentioned: list[AmountMentioned] = Field(default_factory=list)
    payment_commitments: list[PaymentCommitment] = Field(default_factory=list)
    account_references: list[str] = Field(default_factory=list)
    transaction_references: list[str] = Field(default_factory=list)
    financial_products: list[str] = Field(default_factory=list)
    total_outstanding: Optional[float] = None
    settlement_offered: Optional[float] = None
    emi_details: Optional[EMIDetails] = None


class ExtractedEntities(BaseModel):
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    reference_numbers: list[str] = Field(default_factory=list)


class CallCommitment(BaseModel):
    speaker: str
    commitment: str
    type: str = "other"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    conditional: bool = False
    condition: Optional[str] = None


class TimelineEvent(BaseModel):
    timestamp_approx: str = "unknown"
    event: str
    speaker: str = "SYSTEM"
    significance: str = "medium"


class CallDocument(BaseModel):
    """Full extracted document for a single call."""
    call_id: str
    generated_at: datetime
    call_summary: str
    call_purpose: str = "other"
    call_outcome: str = "other"
    financial_data: FinancialData = Field(default_factory=FinancialData)
    entities: ExtractedEntities = Field(default_factory=ExtractedEntities)
    commitments: list[CallCommitment] = Field(default_factory=list)
    key_discussion_points: list[str] = Field(default_factory=list)
    compliance_notes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    call_timeline: list[TimelineEvent] = Field(default_factory=list)
    extraction_model: str = "gpt-4o-mini"
    extraction_tokens: int = 0
    extraction_version: str = "v1"


class CallDocumentResponse(BaseModel):
    """API response wrapping a call document."""
    call_id: str
    generated_at: datetime
    document: dict
    extraction_metadata: dict
