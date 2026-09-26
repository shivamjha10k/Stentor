# Call Document Extraction — Full Execution Plan

> **Goal:** For every analyzed call, automatically extract all financial data, entities, commitments, and key facts from the transcript + NLP signals, then curate a structured document per call that can be viewed, exported (PDF/JSON), and queried.

---

## Architecture Overview

```
                         ┌──────────────────────────┐
                         │   /analyze-call (existing)│
                         └─────────┬────────────────┘
                                   │ After Step 7 (rag_output stored)
                                   ▼
                    ┌──────────────────────────────┐
                    │  NEW Step 9: Call Doc Extract │
                    │  (extraction_service.py)      │
                    └─────────┬────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    ┌─────────────┐  ┌──────────────┐  ┌────────────────┐
    │ Financial    │  │ Entity &     │  │ Compliance &   │
    │ Data Extract │  │ Commitment   │  │ Risk Summary   │
    │              │  │ Extract      │  │ Generation     │
    └──────┬──────┘  └──────┬───────┘  └───────┬────────┘
           │                │                   │
           └────────────────┼───────────────────┘
                            ▼
                ┌───────────────────────┐
                │ call_documents table  │
                │ (Supabase)            │
                └──────────┬────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ GET /doc  │ │ GET /doc │ │ GET /doc │
       │ /{call_id}│ │ /export  │ │ /search  │
       │ (JSON)    │ │ (PDF)    │ │ (query)  │
       └──────────┘ └──────────┘ └──────────┘
```

---

## Phase 1: Database Schema (Day 1)

### 1.1 New Table: `call_documents`

Add to `sql/migrate_call_documents.sql`:

```sql
-- Stores the extracted + curated document for each call
CREATE TABLE IF NOT EXISTS call_documents (
    doc_id              TEXT PRIMARY KEY,           -- "cdoc_<call_id>"
    call_id             TEXT NOT NULL REFERENCES call_analyses(call_id),
    generated_at        TIMESTAMPTZ DEFAULT NOW(),

    -- === FINANCIAL DATA ===
    financial_data      JSONB NOT NULL DEFAULT '{}',
    -- Schema:
    -- {
    --   "amounts_mentioned": [{"value": 5000.00, "currency": "INR", "context": "payment commitment"}],
    --   "payment_commitments": [{"amount": 5000, "due_date": "2026-02-15", "type": "partial_payment"}],
    --   "account_references": ["XXXX-1234", "loan_id_5678"],
    --   "transaction_references": ["TXN20260210001"],
    --   "financial_products": ["personal_loan", "credit_card"],
    --   "total_outstanding": 15000.00,
    --   "settlement_offered": null,
    --   "emi_details": {"amount": 3000, "frequency": "monthly", "remaining": 6}
    -- }

    -- === KEY ENTITIES ===
    entities            JSONB NOT NULL DEFAULT '{}',
    -- Schema:
    -- {
    --   "persons": ["Rahul Sharma"],
    --   "organizations": ["HDFC Bank"],
    --   "dates": ["2026-02-15", "2026-03-01"],
    --   "locations": [],
    --   "phone_numbers": [],
    --   "reference_numbers": ["REF-2026-001"]
    -- }

    -- === COMMITMENTS & PROMISES ===
    commitments         JSONB NOT NULL DEFAULT '[]',
    -- Schema: array of
    -- {
    --   "speaker": "CUSTOMER",
    --   "commitment": "Will pay ₹5000 by Feb 15",
    --   "type": "payment_promise | callback_request | escalation_request | info_request",
    --   "confidence": 0.85,
    --   "conditional": false,
    --   "condition": null
    -- }

    -- === CALL SUMMARY DOCUMENT ===
    call_summary        TEXT NOT NULL,              -- Human-readable narrative summary
    call_purpose        TEXT,                       -- "debt_collection | account_inquiry | complaint | ..."
    call_outcome        TEXT,                       -- "payment_committed | escalated | unresolved | ..."
    key_discussion_points JSONB DEFAULT '[]',       -- ["customer disputed late fee", "agent offered settlement"]

    -- === RISK & COMPLIANCE NOTES ===
    compliance_notes    JSONB DEFAULT '[]',          -- ["FDCPA: agent did not identify as debt collector"]
    risk_flags          JSONB DEFAULT '[]',          -- ["contradictory_statements", "third_party_influence"]
    action_items        JSONB DEFAULT '[]',          -- ["follow_up_call_feb_15", "send_settlement_letter"]

    -- === TIMELINE ===
    call_timeline       JSONB DEFAULT '[]',
    -- Schema: array of
    -- {
    --   "timestamp_approx": "00:30",
    --   "event": "Customer acknowledged debt",
    --   "speaker": "CUSTOMER",
    --   "significance": "high"
    -- }

    -- === METADATA ===
    extraction_model    TEXT DEFAULT 'gpt-4o-mini',
    extraction_tokens   INT DEFAULT 0,
    extraction_version  TEXT DEFAULT 'v1',
    doc_embedding       vector(1536),               -- For semantic search across documents

    UNIQUE(call_id)
);

CREATE INDEX IF NOT EXISTS idx_call_documents_call_id ON call_documents(call_id);
CREATE INDEX IF NOT EXISTS idx_call_documents_generated_at ON call_documents(generated_at DESC);
```

### 1.2 RPC for Document Search

```sql
-- Semantic search across call documents
CREATE OR REPLACE FUNCTION match_call_documents(
    query_embedding vector(1536),
    match_limit INT DEFAULT 5
)
RETURNS TABLE (
    doc_id TEXT,
    call_id TEXT,
    call_summary TEXT,
    call_purpose TEXT,
    call_outcome TEXT,
    financial_data JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cd.doc_id,
        cd.call_id,
        cd.call_summary,
        cd.call_purpose,
        cd.call_outcome,
        cd.financial_data,
        1 - (cd.doc_embedding <=> query_embedding) AS similarity
    FROM call_documents cd
    WHERE cd.doc_embedding IS NOT NULL
    ORDER BY cd.doc_embedding <=> query_embedding
    LIMIT match_limit;
END;
$$;
```

---

## Phase 2: Extraction Service (Day 1-2)

### 2.1 New File: `app/services/extraction_service.py`

This is the core LLM-powered extraction engine. It takes the full call data (transcript + NLP signals + RAG output) and produces the structured document.

**LLM Prompt Strategy:** Single structured extraction call with JSON mode.

```python
# app/services/extraction_service.py

EXTRACTION_SYSTEM_PROMPT = """You are a financial call document analyst. Your job is to extract
ALL structured data from a call transcript and its analysis signals, producing a comprehensive
call document.

You MUST return a JSON object with these exact keys:

1. "financial_data": {
     "amounts_mentioned": [{"value": float, "currency": str, "context": str}],
     "payment_commitments": [{"amount": float, "due_date": str|null, "type": str}],
     "account_references": [str],
     "transaction_references": [str],
     "financial_products": [str],
     "total_outstanding": float|null,
     "settlement_offered": float|null,
     "emi_details": {"amount": float, "frequency": str, "remaining": int}|null
   }

2. "entities": {
     "persons": [str],
     "organizations": [str],
     "dates": [str],         // ISO format YYYY-MM-DD
     "locations": [str],
     "phone_numbers": [str],
     "reference_numbers": [str]
   }

3. "commitments": [
     {
       "speaker": "CUSTOMER"|"AGENT",
       "commitment": str,      // exact quote or paraphrase
       "type": "payment_promise"|"callback_request"|"escalation_request"|"info_request"|"other",
       "confidence": float,    // 0.0-1.0
       "conditional": bool,
       "condition": str|null
     }
   ]

4. "call_summary": str          // 3-5 sentence narrative summary
5. "call_purpose": str          // one of: debt_collection, account_inquiry, complaint, fraud_report, general_inquiry, settlement_negotiation, payment_arrangement, other
6. "call_outcome": str          // one of: payment_committed, escalated, unresolved, resolved, callback_scheduled, info_provided, complaint_registered, other
7. "key_discussion_points": [str]  // 3-7 bullet points
8. "compliance_notes": [str]    // any regulatory/compliance observations
9. "risk_flags": [str]          // behavioral or fraud risk indicators
10. "action_items": [str]       // next steps required
11. "call_timeline": [
      {
        "timestamp_approx": str,   // "early"|"mid"|"late" or "00:30" if inferable
        "event": str,
        "speaker": "CUSTOMER"|"AGENT"|"SYSTEM",
        "significance": "high"|"medium"|"low"
      }
    ]

RULES:
- Extract ONLY what is explicitly stated or directly inferable from the transcript
- Do NOT hallucinate financial amounts or dates
- If a field has no data, use empty arrays [] or null
- For amounts, always include currency (default "INR" if not specified)
- Mark commitments as conditional if they contain "if", "provided that", etc.
- Be precise with compliance notes — cite specific regulations if applicable
- Return ONLY the JSON object, no markdown or extra text
"""
```

**Function flow:**

```python
def extract_call_document(call_id: str, payload: dict, rag_output: dict) -> dict:
    """
    Main extraction function.

    Args:
        call_id:     The call identifier
        payload:     Full call data (call_context, nlp_insights, conversation, etc.)
        rag_output:  The RAG grounded reasoning output from Step 6

    Returns:
        Complete extracted document dict matching call_documents schema
    """
    # 1. Build extraction context from transcript + signals
    # 2. Call LLM with EXTRACTION_SYSTEM_PROMPT
    # 3. Parse & validate JSON response
    # 4. Return structured document
```

### 2.2 Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **LLM Model** | `gpt-4o-mini` (default), `gpt-4o` for high-risk calls | Cost efficiency; 4o for complex cases |
| **Single vs Multi-call** | Single LLM call with full context | Transcript + signals fit in 128k context |
| **Extraction trigger** | Automatic after Step 7 in pipeline | Every call gets a document |
| **Retry strategy** | 2 attempts, fallback to partial doc | Same pattern as existing `reasoning.py` |
| **Async** | No (sync like existing pipeline) | Keeps consistency with current architecture |

---

## Phase 3: Database Queries (Day 2)

### 3.1 Add to `app/db/queries.py`

```python
# New functions needed:

def insert_call_document(doc_id, call_id, document_data, embedding=None) -> dict
    """Insert extracted document into call_documents table."""

def get_call_document(call_id) -> dict | None
    """Fetch the curated document for a specific call."""

def search_call_documents(query_embedding, limit=5) -> list[dict]
    """Semantic search across all call documents."""

def get_call_documents_paginated(page, limit, filters) -> tuple[list, int]
    """Paginated listing of call documents with optional filters."""

def get_financial_summary_across_calls(days=30) -> dict
    """Aggregate financial data across recent calls (for dashboard)."""
```

---

## Phase 4: API Endpoints (Day 2-3)

### 4.1 New Endpoints in `app/api/routes.py`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/call/{call_id}/document` | Get the full curated document for a call |
| `GET` | `/api/v1/call/{call_id}/document/financial` | Get only the financial extraction |
| `GET` | `/api/v1/call/{call_id}/document/export` | Export document as PDF or JSON |
| `POST` | `/api/v1/call/{call_id}/document/regenerate` | Re-extract document (if transcript updated) |
| `GET` | `/api/v1/documents` | Paginated list of all call documents |
| `POST` | `/api/v1/documents/search` | Semantic search across all call documents |
| `GET` | `/api/v1/documents/financial-summary` | Aggregated financial data across calls |

### 4.2 Endpoint Details

#### `GET /api/v1/call/{call_id}/document`

**Response:**
```json
{
  "call_id": "call_2026_02_11_a1b2c3",
  "generated_at": "2026-02-11T10:30:00Z",
  "document": {
    "call_summary": "Customer Rahul Sharma called regarding overdue personal loan EMI of ₹3,000. Customer acknowledged the outstanding amount of ₹15,000 and committed to making a partial payment of ₹5,000 by February 15, 2026. Agent offered a settlement option which the customer said they would consider.",
    "call_purpose": "debt_collection",
    "call_outcome": "payment_committed",

    "financial_data": {
      "amounts_mentioned": [
        {"value": 3000.0, "currency": "INR", "context": "monthly EMI amount"},
        {"value": 15000.0, "currency": "INR", "context": "total outstanding"},
        {"value": 5000.0, "currency": "INR", "context": "partial payment commitment"}
      ],
      "payment_commitments": [
        {"amount": 5000, "due_date": "2026-02-15", "type": "partial_payment"}
      ],
      "account_references": ["LOAN-2024-5678"],
      "transaction_references": [],
      "financial_products": ["personal_loan"],
      "total_outstanding": 15000.0,
      "settlement_offered": 12000.0,
      "emi_details": {"amount": 3000, "frequency": "monthly", "remaining": 6}
    },

    "entities": {
      "persons": ["Rahul Sharma"],
      "organizations": ["HDFC Bank"],
      "dates": ["2026-02-15"],
      "locations": [],
      "phone_numbers": [],
      "reference_numbers": ["LOAN-2024-5678"]
    },

    "commitments": [
      {
        "speaker": "CUSTOMER",
        "commitment": "Will pay ₹5,000 by February 15",
        "type": "payment_promise",
        "confidence": 0.85,
        "conditional": false,
        "condition": null
      },
      {
        "speaker": "AGENT",
        "commitment": "Will send settlement offer letter via email",
        "type": "other",
        "confidence": 0.95,
        "conditional": false,
        "condition": null
      }
    ],

    "key_discussion_points": [
      "Customer acknowledged ₹15,000 outstanding on personal loan",
      "Monthly EMI of ₹3,000 overdue for 2 months",
      "Customer committed to ₹5,000 partial payment by Feb 15",
      "Agent offered one-time settlement at ₹12,000",
      "Customer will consider settlement and call back"
    ],

    "compliance_notes": [
      "Agent properly identified themselves and the purpose of the call",
      "No threatening language used"
    ],

    "risk_flags": [
      "payment_commitment_conditional",
      "history_of_missed_payments"
    ],

    "action_items": [
      "Follow up on ₹5,000 payment after Feb 15",
      "Send settlement offer letter via email",
      "Schedule callback for settlement decision"
    ],

    "call_timeline": [
      {"timestamp_approx": "early", "event": "Agent identified purpose of call", "speaker": "AGENT", "significance": "medium"},
      {"timestamp_approx": "early", "event": "Customer acknowledged outstanding debt", "speaker": "CUSTOMER", "significance": "high"},
      {"timestamp_approx": "mid", "event": "Payment commitment of ₹5,000 by Feb 15", "speaker": "CUSTOMER", "significance": "high"},
      {"timestamp_approx": "mid", "event": "Settlement offer of ₹12,000 proposed", "speaker": "AGENT", "significance": "high"},
      {"timestamp_approx": "late", "event": "Customer agreed to consider settlement", "speaker": "CUSTOMER", "significance": "medium"}
    ]
  },

  "extraction_metadata": {
    "model": "gpt-4o-mini",
    "tokens_used": 1847,
    "version": "v1"
  }
}
```

#### `GET /api/v1/call/{call_id}/document/export?format=pdf`

Generates a formatted PDF using a template:
- **Header:** Call ID, Date, Risk Level badge
- **Section 1:** Executive Summary (call_summary)
- **Section 2:** Financial Data (table format)
- **Section 3:** Commitments & Promises
- **Section 4:** Key Discussion Points
- **Section 5:** Compliance & Risk Notes
- **Section 6:** Call Timeline
- **Section 7:** Action Items
- **Footer:** Generated by Stentor RAG Pipeline, extraction model info

---

## Phase 5: Pipeline Integration (Day 3)

### 5.1 Wire into `analyze-call` Pipeline

Add as **Step 9** after Step 8 (return response), running as a non-blocking post-processing step:

```python
# In routes.py analyze_call():

# --- Step 8: Return Final Response ---
response = { ... }

# --- Step 9: Extract Call Document (non-blocking) ---
try:
    from app.services.extraction_service import extract_call_document
    doc_result = extract_call_document(
        call_id=call_id,
        payload=payload.model_dump(),
        rag_output=rag_output,
        conversation=payload.conversation,
    )
    logger.info(f"[{call_id}] STEP 9 | Call document extracted | {doc_result['tokens_used']} tokens")
    response["document_generated"] = True
except Exception as e:
    logger.warning(f"[{call_id}] STEP 9 | Document extraction failed (non-fatal): {e}")
    response["document_generated"] = False

return response
```

### 5.2 Option: Background Extraction via `/document/regenerate`

For calls that were analyzed before this feature existed, expose a regeneration endpoint:

```
POST /api/v1/call/{call_id}/document/regenerate
```

This reads the call data from `call_analyses`, runs the extraction, and stores/updates the document.

---

## Phase 6: PDF Export Service (Day 3-4)

### 6.1 New File: `app/services/pdf_generator.py`

Use **`reportlab`** or **`fpdf2`** (lightweight, no system deps):

```python
# app/services/pdf_generator.py

from fpdf import FPDF

def generate_call_document_pdf(call_id: str, document: dict, call_data: dict) -> bytes:
    """
    Generate a formatted PDF for a call document.

    Returns: PDF file as bytes
    """
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, f"Call Analysis Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Call ID: {call_id}", ln=True)
    pdf.cell(0, 8, f"Date: {document['generated_at']}", ln=True)
    pdf.ln(5)

    # ... sections for each data block ...

    return pdf.output()
```

### 6.2 Add `fpdf2` to `requirements.txt`

```
fpdf2>=2.7.0
```

---

## Phase 7: Pydantic Models (Day 2)

### 7.1 Add to `app/models/schemas.py`

```python
# === CALL DOCUMENT MODELS ===

class AmountMentioned(BaseModel):
    value: float
    currency: str = "INR"
    context: str

class PaymentCommitment(BaseModel):
    amount: float
    due_date: Optional[str] = None
    type: str

class EMIDetails(BaseModel):
    amount: float
    frequency: str
    remaining: int

class FinancialData(BaseModel):
    amounts_mentioned: list[AmountMentioned] = []
    payment_commitments: list[PaymentCommitment] = []
    account_references: list[str] = []
    transaction_references: list[str] = []
    financial_products: list[str] = []
    total_outstanding: Optional[float] = None
    settlement_offered: Optional[float] = None
    emi_details: Optional[EMIDetails] = None

class ExtractedEntities(BaseModel):
    persons: list[str] = []
    organizations: list[str] = []
    dates: list[str] = []
    locations: list[str] = []
    phone_numbers: list[str] = []
    reference_numbers: list[str] = []

class CallCommitment(BaseModel):
    speaker: str
    commitment: str
    type: str
    confidence: float = Field(ge=0.0, le=1.0)
    conditional: bool = False
    condition: Optional[str] = None

class TimelineEvent(BaseModel):
    timestamp_approx: str
    event: str
    speaker: str
    significance: str = "medium"

class CallDocument(BaseModel):
    call_id: str
    generated_at: datetime
    call_summary: str
    call_purpose: str
    call_outcome: str
    financial_data: FinancialData
    entities: ExtractedEntities
    commitments: list[CallCommitment] = []
    key_discussion_points: list[str] = []
    compliance_notes: list[str] = []
    risk_flags: list[str] = []
    action_items: list[str] = []
    call_timeline: list[TimelineEvent] = []
    extraction_model: str = "gpt-4o-mini"
    extraction_tokens: int = 0
    extraction_version: str = "v1"

class CallDocumentResponse(BaseModel):
    call_id: str
    generated_at: datetime
    document: CallDocument
    extraction_metadata: dict
```

---

## Phase 8: Dashboard Integration (Day 4)

### 8.1 New Dashboard Widget: Financial Intelligence Panel

Add to the existing dashboard:

- **Financial Summary Card**: Total amounts committed, average outstanding, settlement rate
- **Recent Documents Table**: Last N call documents with quick financial highlights
- **Entity Frequency**: Most mentioned organizations, persons, products

### 8.2 New Endpoint

```
GET /api/v1/dashboard/financial-intelligence
```

```json
{
  "period": "last_30_days",
  "total_payment_commitments": 145000.0,
  "avg_outstanding": 18500.0,
  "commitments_kept_rate": 0.62,
  "top_financial_products": [
    {"product": "personal_loan", "count": 45},
    {"product": "credit_card", "count": 32}
  ],
  "top_commitment_types": [
    {"type": "payment_promise", "count": 67},
    {"type": "callback_request", "count": 23}
  ],
  "documents_generated": 156
}
```

---

## File-by-File Implementation Checklist

| # | File | Action | Description |
|---|------|--------|-------------|
| 1 | `sql/migrate_call_documents.sql` | **CREATE** | New table + RPC functions |
| 2 | `app/models/schemas.py` | **EDIT** | Add CallDocument models |
| 3 | `app/services/extraction_service.py` | **CREATE** | Core LLM extraction logic |
| 4 | `app/services/pdf_generator.py` | **CREATE** | PDF export service |
| 5 | `app/db/queries.py` | **EDIT** | Add document CRUD + search queries |
| 6 | `app/api/routes.py` | **EDIT** | Add document endpoints + Step 9 in pipeline |
| 7 | `requirements.txt` | **EDIT** | Add `fpdf2` |

---

## Implementation Order (Recommended)

```
Day 1 (Foundation):
  ├── 1. Write SQL migration → run in Supabase
  ├── 2. Add Pydantic models to schemas.py
  └── 3. Build extraction_service.py (LLM prompt + parsing)

Day 2 (Core):
  ├── 4. Add DB queries (insert, get, search)
  ├── 5. Wire Step 9 into analyze-call pipeline
  └── 6. Add GET /call/{id}/document endpoint

Day 3 (Export & Search):
  ├── 7. Build PDF generator
  ├── 8. Add export endpoint
  ├── 9. Add document search endpoint
  └── 10. Add regenerate endpoint

Day 4 (Polish):
  ├── 11. Dashboard financial intelligence endpoint
  ├── 12. Backfill existing calls (run regenerate on old call_ids)
  └── 13. Testing & edge cases
```

---

## Cost Estimation (per call)

| Component | Tokens (est.) | Cost (gpt-4o-mini) |
|-----------|--------------|---------------------|
| Extraction prompt (system) | ~800 | — |
| Call transcript + signals (input) | ~2,000-5,000 | ~$0.0006-$0.0015 |
| Structured output (output) | ~1,500-2,500 | ~$0.0009-$0.0015 |
| Embedding for doc search | 1 embed call | ~$0.00002 |
| **Total per call** | | **~$0.002-$0.003** |

For 1,000 calls/day: **~$2-3/day** on gpt-4o-mini.

---

## Edge Cases to Handle

1. **Empty transcript**: If `conversation` is empty, extract from `summary_for_rag` only
2. **No financial data**: Return empty financial_data object (don't fail)
3. **Multiple currencies**: Store each with its currency code
4. **Ambiguous dates**: Use ISO format, mark confidence
5. **Very long transcripts**: Truncate to last 50 turns if > 100 turns
6. **Re-extraction**: Upsert pattern — don't duplicate documents
7. **LLM hallucination guard**: Cross-validate extracted amounts against `nlp_insights.entities.amount_mentioned`

---

## How to Explain to Judges

> "Every call that flows through our pipeline automatically generates a structured intelligence document. The system uses GPT-4o-mini to extract all financial data — amounts mentioned, payment commitments, EMI details, account references — along with entities, compliance observations, and a timeline of key events. Each document is stored with a vector embedding so you can semantically search across all call documents. You can export any call's document as a formatted PDF for audit trails or compliance reporting. The extraction costs under $0.003 per call, making it viable at scale."

**Key selling points:**
- **Zero manual effort** — fully automatic extraction on every call
- **Structured data** — not just a summary, but queryable financial fields
- **Searchable** — semantic search across all extracted documents
- **Exportable** — PDF reports for compliance/audit
- **Cost-effective** — $2-3/day for 1,000 calls
- **Backfillable** — can regenerate documents for historical calls
