<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=for-the-badge&logo=openai&logoColor=white" />
  <img src="https://img.shields.io/badge/Supabase-pgvector-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white" />
  <img src="https://img.shields.io/badge/Backboard-AI%20Memory-FF6B6B?style=for-the-badge" />
</p>

<h1 align="center">🎙️ Stentor RAG Pipeline</h1>
<h3 align="center">Financial Audio Intelligence — Call-Centric Risk Grounding Engine</h3>

<p align="center">
  A production-grade <strong>Retrieval-Augmented Generation (RAG)</strong> pipeline that ingests financial call analysis data from an upstream NLP service, grounds risk signals against a curated knowledge base of fraud patterns, compliance rules, and risk heuristics — then produces auditor-friendly risk assessments, structured call documents, and exportable PDF reports.
</p>

---

## 📑 Table of Contents

- [Architecture Overview](#-architecture-overview)
- [Tech Stack](#-tech-stack)
- [Core Pipeline — 10-Step Workflow](#-core-pipeline--10-step-workflow)
- [Example End-to-End Flow](#-example-end-to-end-flow)
- [Knowledge Base](#-knowledge-base)
- [Chatbot System](#-chatbot-system)
- [Dashboard & Analytics](#-dashboard--analytics)
- [Backboard AI — Reasoning Audit Trail](#-backboard-ai--reasoning-audit-trail)
- [Call Document Extraction](#-call-document-extraction)
- [API Reference](#-api-reference)
- [Database Schema](#-database-schema)
- [Project Structure](#-project-structure)
- [Setup & Installation](#-setup--installation)
- [Environment Variables](#-environment-variables)

---

## 🏗 Architecture Overview

```
┌─────────────────────┐
│   NLP Service       │  Upstream: audio transcription + NLP analysis
│   (External)        │  Produces: risk signals, intent, sentiment,
└────────┬────────────┘  entities, transcript, risk score
         │
         │  POST /api/v1/analyze-call
         ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Stentor RAG Pipeline                           │
│                                                                    │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌───────────┐  │
│  │ Step 1   │──▶│ Step 2   │──▶│  Step 3      │──▶│ Step 4    │  │
│  │ Validate │   │ Store in │   │  Embed       │   │ Retrieve  │  │
│  │ Payload  │   │ Supabase │   │  Summary     │   │ Knowledge │  │
│  └──────────┘   └──────────┘   │  (OpenAI)    │   │ (pgvector)│  │
│                                └──────────────┘   └─────┬─────┘  │
│                                                         │        │
│  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌────▼──────┐ │
│  │ Step 7   │◀──│ Step 6   │◀──│  Step 5      │◀──│ Fraud     │ │
│  │ Store    │   │ LLM      │   │  Build       │   │ Compliance│ │
│  │ RAG Out  │   │ Reasoning│   │  Grounding   │   │ Heuristic │ │
│  └────┬─────┘   │ (GPT-4o) │   │  Context     │   └───────────┘ │
│       │         └──────────┘   └──────────────┘                  │
│       ▼                                                          │
│  ┌──────────┐   ┌──────────────────────────────────────────────┐ │
│  │ Step 9   │   │          Backboard AI (Steps 5b, 6b)         │ │
│  │ Extract  │   │  Persistent reasoning threads per call       │ │
│  │ Document │   │  Cross-call memory & pattern learning        │ │
│  └────┬─────┘   └──────────────────────────────────────────────┘ │
│       │                                                          │
│       ▼                                                          │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  Outputs: JSON Response, PDF Export, Dashboard Stats   │      │
│  └────────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐    ┌──────────────────────┐
│   Frontend          │    │   Knowledge Chatbot   │
│   Dashboard         │    │   POST /api/v1/chat   │
│   (React/Next.js)   │    │   RAG-powered Q&A     │
└─────────────────────┘    └──────────────────────┘
```

---

## 🛠 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Framework** | FastAPI `0.115.6` | Async REST API with automatic OpenAPI docs |
| **LLM** | OpenAI GPT-4o / GPT-4o-mini | Grounded reasoning, document extraction, chat |
| **Embeddings** | OpenAI `text-embedding-3-small` | 1536-dim vectors for semantic search |
| **Database** | Supabase (PostgreSQL) | Structured storage + Row Level Security |
| **Vector Search** | pgvector + RPC functions | Cosine similarity search via `<=>` operator |
| **Validation** | Pydantic `2.10` | Strict input/output schema validation |
| **AI Memory** | Backboard AI | Per-call reasoning audit trails + cross-call pattern memory |
| **PDF Export** | fpdf2 `2.7+` | Lightweight PDF report generation |
| **HTTP Client** | httpx `0.28` | Async HTTP for Backboard API calls |
| **Config** | python-dotenv | Environment variable management |

---

## 🔄 Core Pipeline — 10-Step Workflow

The main analysis pipeline (`POST /api/v1/analyze-call`) executes 10 sequential steps for every incoming call:

### Step 1 — Validate Payload
Pydantic validates the incoming JSON against `CallRiskInput` schema. The payload includes:
- **Call context** — language, audio quality (noise, stability, speech naturalness)
- **Speaker analysis** — customer-only analysis flag, agent influence detection
- **NLP insights** — intent, sentiment, obligation strength, entities, contradictions
- **Risk signals** — audio trust flags, behavioral flags
- **Risk assessment** — score (0-100), fraud likelihood, confidence
- **Summary** — natural language summary for RAG embedding
- **Conversation** — full transcript as speaker turns

### Step 2 — Store Call Record
Generates a unique `call_id` (format: `call_YYYY_MM_DD_hexhex`) and inserts the full payload into the `call_analyses` table in Supabase. The `rag_output` column is left `NULL` at this stage.

### Step 3 — Embed Summary
Sends `summary_for_rag` to OpenAI's `text-embedding-3-small` model, producing a **1536-dimensional** vector. This embedding is used as the query vector to search the knowledge base.

**Step 3b** — The embedding is also stored in `call_analyses.summary_embedding` for future chatbot vector search over past calls.

### Step 4 — Retrieve Knowledge Chunks
Uses the query embedding to perform **3 parallel cosine similarity searches** via pgvector RPC functions:
- **4A** — Fraud patterns (`fraud_pattern` category, top 3)
- **4B** — Compliance rules (`compliance` category, top 2)
- **4C** — Risk heuristics (`risk_heuristic` category, top 2)

Each search calls the `match_knowledge` RPC:
```sql
SELECT doc_id, title, content,
       1 - (embedding <=> query_embedding) AS similarity
FROM knowledge_embeddings
WHERE category = match_category
ORDER BY embedding <=> query_embedding
LIMIT match_limit;
```

### Step 5 — Build Grounding Context
Assembles a structured text prompt combining:
1. **Call Signals** — all NLP insights, risk flags, risk score
2. **Matched Fraud Patterns** — with similarity scores
3. **Compliance Guidance** — applicable regulations
4. **Risk Heuristics** — behavioral analysis rules

**Step 5b** — A **Backboard AI thread** is created for the call. The call signals and grounding context are logged for audit traceability.

### Step 6 — LLM Grounded Reasoning
Sends the grounding context to **GPT-4o-mini** (or GPT-4o for high-risk calls) with a specialized system prompt. The LLM returns a **structured JSON** response:

```json
{
  "grounded_assessment": "high_risk",
  "explanation": "The customer's conditional payment promise matches [fp_001] ...",
  "recommended_action": "escalate_to_compliance",
  "confidence": 0.87,
  "regulatory_flags": ["RBI_NPA_CLASSIFICATION"],
  "matched_patterns": ["Conditional Promise with Contradiction"]
}
```

The LLM is **constrained** by strict rules:
- Cannot override the upstream risk score
- Cannot extract new intent/sentiment
- Must cite specific matched patterns
- Must use neutral language (no "fraudster", "liar")
- Falls back to `manual_review` when uncertain

**Step 6b** — The LLM reasoning output is logged to the Backboard thread.

### Step 7 — Store RAG Output
Updates the `rag_output` JSONB column in `call_analyses` with the structured reasoning result.

**Step 7b** — Derives initial case status from the risk score:
| Risk Score | Status |
|-----------|--------|
| `< 30` | `resolved` |
| `30–50` | `in_review` |
| `> 50` | `escalated` |

### Step 9 — Extract Call Document
A **second LLM call** extracts comprehensive structured data from the full call context:
- **Financial data** — amounts, payment commitments, EMI details, outstanding balances
- **Entities** — persons, organizations, dates, locations, phone numbers
- **Commitments** — speaker promises with confidence and conditionality
- **Timeline** — chronological event sequence
- **Compliance notes** and **risk flags**
- **Action items** — required next steps

The extracted document is embedded and stored in `call_documents` for semantic search.

### Step 10 — Return Response
Returns the complete analysis:
```json
{
  "call_id": "call_2026_02_09_a1b2c3",
  "call_timestamp": "2026-02-09T14:30:00Z",
  "input_risk_assessment": { "risk_score": 72, "fraud_likelihood": "high", "confidence": 0.85 },
  "rag_output": { "grounded_assessment": "high_risk", "explanation": "...", ... },
  "backboard_thread_id": "thr_abc123",
  "document_generated": true
}
```

---

## 🧪 Example End-to-End Flow

### Scenario: Suspicious Debt Collection Call

**1. NLP service sends analysis →**

```json
POST /api/v1/analyze-call
{
  "call_context": {
    "call_language": "en",
    "call_quality": { "noise_level": "medium", "call_stability": "low", "speech_naturalness": "suspicious" }
  },
  "speaker_analysis": { "customer_only_analysis": true, "agent_influence_detected": false },
  "nlp_insights": {
    "intent": { "label": "promise_to_pay", "confidence": 0.65, "conditionality": "high" },
    "sentiment": { "label": "stressed", "confidence": 0.78 },
    "obligation_strength": "weak",
    "entities": { "payment_commitment": "partial", "amount_mentioned": 5000.0 },
    "contradictions_detected": true
  },
  "risk_signals": {
    "audio_trust_flags": ["low_stability", "unnatural_speech"],
    "behavioral_flags": ["conditional_promise", "contradiction_detected"]
  },
  "risk_assessment": { "risk_score": 72, "fraud_likelihood": "high", "confidence": 0.85 },
  "summary_for_rag": "Customer made a conditional promise to pay ₹5000 with high conditionality. Contradictions detected between stated willingness and behavioral signals. Speech naturalness flagged as suspicious with low call stability.",
  "conversation": [
    { "speaker": "AGENT", "text": "Good morning, I'm calling regarding your overdue payment of ₹15,000." },
    { "speaker": "CUSTOMER", "text": "Yes, I know about it. I'll try to pay something next week maybe." },
    { "speaker": "AGENT", "text": "Can you confirm a specific amount and date?" },
    { "speaker": "CUSTOMER", "text": "Maybe ₹5000, but only if my salary comes through." },
    { "speaker": "AGENT", "text": "You mentioned last month that your salary was already deposited." },
    { "speaker": "CUSTOMER", "text": "That was for other expenses. I can't commit right now." }
  ]
}
```

**2. Pipeline executes →**

```
14:30:01 | STEP 1 | Validated | risk=72 fraud=high
14:30:01 | STEP 2 | Stored in call_analyses
14:30:02 | STEP 3 | Embedded summary | dim=1536
14:30:02 | STEP 4 | Retrieved fraud=3 compliance=2 heuristic=2
14:30:02 | STEP 5 | Context built | 2847 chars
14:30:02 | STEP 5b| Backboard thread created & logged
14:30:04 | STEP 6 | LLM done | assessment=high_risk action=escalate_to_compliance
14:30:04 | STEP 6b| Backboard LLM output logged
14:30:04 | STEP 7 | rag_output stored
14:30:04 | STEP 7b| status=escalated (risk_score=72)
14:30:06 | STEP 9 | Call document extracted | tokens=1247
14:30:06 | DONE   | Pipeline complete
```

**3. Vector retrieval found these matches →**

| # | Pattern | Similarity |
|---|---------|-----------|
| 1 | Conditional Promise with Contradiction | 0.91 |
| 2 | Evasive Response Pattern | 0.84 |
| 3 | Low Call Stability with Suspicious Audio | 0.79 |

**4. LLM grounded reasoning output →**

```json
{
  "grounded_assessment": "high_risk",
  "explanation": "The customer exhibits strong indicators matching pattern [fp_001] 'Conditional Promise with Contradiction'. The payment promise of ₹5,000 is highly conditional ('only if my salary comes through') and directly contradicts the agent's reference to a prior salary deposit. This aligns with documented behavior where 73% of such calls result in non-payment. Additionally, suspicious audio quality (low stability + unnatural speech) raises concerns per [fp_006]. The weak obligation strength and stressed sentiment further corroborate unreliable commitment.",
  "recommended_action": "escalate_to_compliance",
  "confidence": 0.87,
  "regulatory_flags": ["RBI_NPA_CLASSIFICATION", "COLLECTION_PRACTICE_REVIEW"],
  "matched_patterns": ["Conditional Promise with Contradiction", "Evasive Response Pattern", "Low Call Stability with Suspicious Audio"]
}
```

**5. Extracted call document includes →**

```json
{
  "financial_data": {
    "amounts_mentioned": [
      { "value": 15000, "currency": "INR", "context": "overdue payment amount" },
      { "value": 5000, "currency": "INR", "context": "conditional payment promise" }
    ],
    "total_outstanding": 15000,
    "payment_commitments": [
      { "amount": 5000, "due_date": "next week (unspecified)", "type": "partial_payment" }
    ]
  },
  "commitments": [
    {
      "speaker": "CUSTOMER",
      "commitment": "Will pay ₹5000 next week if salary arrives",
      "type": "payment_promise",
      "confidence": 0.35,
      "conditional": true,
      "condition": "Salary must come through first"
    }
  ],
  "call_purpose": "debt_collection",
  "call_outcome": "unresolved",
  "risk_flags": [
    "Contradiction between stated willingness and prior deposit claim",
    "Suspicious audio quality indicators"
  ]
}
```

---

## 📚 Knowledge Base

The knowledge base consists of three curated JSON files in the `knowledge/` directory:

| File | Category | Contents |
|------|----------|----------|
| `fraud_patterns.json` | `fraud_pattern` | 6 documented fraud/risk behavior patterns with severity, risk weights |
| `compliance_rules.json` | `compliance` | Regulatory compliance guidelines (RBI, SEBI, etc.) |
| `risk_heuristics.json` | `risk_heuristic` | Behavioral analysis heuristics with statistical correlations |

**Seeding**: Run `POST /api/v1/knowledge/seed` once. This:
1. Reads each JSON file
2. Embeds every document via OpenAI (`text-embedding-3-small`)
3. Upserts into `knowledge_embeddings` table with the vector

Each knowledge document has:
```json
{
  "doc_id": "fp_001",
  "category": "fraud_pattern",
  "title": "Conditional Promise with Contradiction",
  "content": "When a customer makes a payment promise with high conditionality...",
  "metadata": { "severity": "high", "risk_weight": 0.85 }
}
```

---

## 💬 Chatbot System

The chatbot (`POST /api/v1/chat`) provides RAG-powered Q&A over the knowledge base and call history.

### How It Works

```
User Question
     │
     ▼
┌──────────────┐
│ Embed        │ ── OpenAI text-embedding-3-small
│ Question     │
└──────┬───────┘
       │
       ▼
┌──────────────┐    ┌──────────────────┐
│ Vector Search│───▶│ knowledge_       │  Fraud patterns, compliance, heuristics
│ Knowledge    │    │ embeddings       │
└──────┬───────┘    └──────────────────┘
       │
       ▼
┌──────────────┐    ┌──────────────────┐
│ Vector Search│───▶│ call_analyses    │  Past call records (optional)
│ Calls        │    │ (summary_embed)  │
└──────┬───────┘    └──────────────────┘
       │
       ▼
┌──────────────┐    ┌──────────────────┐
│ Temporal /   │───▶│ Direct DB lookup │  "last 5 calls", "call_2026_..."
│ ID Detection │    │                  │
└──────┬───────┘    └──────────────────┘
       │
       ▼
┌──────────────┐
│ Build Chat   │ ── Knowledge + Calls + History + Question
│ Context      │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ GPT-4o-mini  │ ── Grounded answer with [doc_id] citations
│ Reasoning    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Response     │ ── Answer + Sources + Metadata
└──────────────┘
```

### Smart Query Features

| Feature | Example Query | Behavior |
|---------|--------------|----------|
| **Temporal queries** | `"Show me the last 5 calls"` | Regex-detected → fetches N most recent calls |
| **Call ID lookup** | `"Tell me about call_2026_02_09_a1b2c3"` | Pattern-matched → direct DB lookup |
| **Knowledge search** | `"What is the conditional promise pattern?"` | Vector search across knowledge base |
| **Cross-call memory** | `"What patterns are common this week?"` | Backboard AI memory enrichment |

### Example Chat Request

```json
POST /api/v1/chat
{
  "question": "What fraud patterns involve suspicious audio quality?",
  "filters": {
    "search_knowledge": true,
    "search_calls": false,
    "categories": ["fraud_pattern"],
    "knowledge_limit": 5
  }
}
```

**Response:**
```json
{
  "answer": "Based on the knowledge base, two fraud patterns involve suspicious audio quality:\n\n1. **[fp_003] Third-Party Call Impersonation** — Calls where speech naturalness is flagged as suspicious and audio quality shows anomalies may indicate third-party impersonation...\n\n2. **[fp_006] Low Call Stability with Suspicious Audio** — Calls exhibiting low stability combined with suspicious speech naturalness may indicate manipulated audio or recorded playback...",
  "sources": [
    { "type": "knowledge", "doc_id": "fp_003", "category": "fraud_pattern", "title": "Third-Party Call Impersonation", "similarity": 0.92 },
    { "type": "knowledge", "doc_id": "fp_006", "category": "fraud_pattern", "title": "Low Call Stability with Suspicious Audio", "similarity": 0.89 }
  ],
  "metadata": {
    "knowledge_docs_searched": 2,
    "calls_searched": 0,
    "model": "gpt-4o-mini",
    "tokens_used": 842
  }
}
```

---

## 📊 Dashboard & Analytics

| Endpoint | Description |
|----------|-------------|
| `GET /dashboard/stats` | KPI numbers: total calls, risk distribution, resolution rate, status breakdown |
| `GET /dashboard/recent-activity` | Last N calls with outcomes for the activity timeline |
| `GET /dashboard/top-patterns` | Aggregated fraud pattern frequency across all analyzed calls |
| `GET /dashboard/active-cases` | Top N highest-risk unresolved cases |
| `GET /dashboard/health` | System health: database, knowledge base, embedding service status |
| `GET /dashboard/financial-intelligence` | Aggregated financial data across call documents (commitments, outstanding, breakdowns) |

### Dashboard Stats Response Example

```json
{
  "total_calls": 247,
  "total_calls_today": 12,
  "high_risk_count": 38,
  "medium_risk_count": 94,
  "low_risk_count": 115,
  "avg_risk_score": 41.3,
  "resolution_rate": 68.4,
  "status_breakdown": { "open": 15, "in_review": 42, "escalated": 22, "resolved": 168 }
}
```

---

## 🧠 Backboard AI — Reasoning Audit Trail

Every analyzed call gets a **persistent reasoning thread** in Backboard AI, creating a full audit trail:

```
Thread: call_2026_02_09_a1b2c3
│
├── [CALL SIGNALS]          ← Full NLP payload logged
├── [GROUNDING CONTEXT]     ← Assembled prompt with matched patterns
├── [LLM REASONING OUTPUT]  ← Complete JSON reasoning result
│
└── Query: "Why was this flagged high risk?"
    └── Answer: "Based on the stored context, this call was flagged because..."
```

### Features

| Feature | Endpoint | Description |
|---------|----------|-------------|
| **View audit trail** | `GET /backboard/{call_id}` | Full chain: signals → context → reasoning |
| **Query reasoning** | `POST /backboard/{call_id}/query` | Ask questions about a specific call's analysis |
| **Cross-call memory** | `POST /backboard/memory/query` | Query patterns learned across ALL calls |
| **List all threads** | `GET /backboard/threads/all` | Admin view of all reasoning threads |

### Cross-Call Memory Example

```json
POST /api/v1/backboard/memory/query
{ "question": "What are the most common fraud indicators this month?" }

Response:
{
  "answer": "Based on patterns observed across 47 calls this month, the most frequent indicators are: (1) Conditional promises with contradictions appeared in 23 calls (49%), (2) Evasive response patterns in 18 calls (38%), (3) Suspicious audio quality in 8 calls (17%)...",
  "source": "backboard_memory"
}
```

---

## 📄 Call Document Extraction

After the main pipeline runs, a **second LLM pass** extracts comprehensive structured data from each call:

### Extracted Fields

| Field | Type | Description |
|-------|------|-------------|
| `financial_data` | Object | Amounts, payment commitments, EMI details, outstanding balances, settlement offers |
| `entities` | Object | Persons, organizations, dates, locations, phone numbers, reference numbers |
| `commitments` | Array | Speaker promises with type, confidence, conditionality |
| `call_summary` | String | 3-5 sentence narrative summary |
| `call_purpose` | Enum | `debt_collection`, `account_inquiry`, `complaint`, `fraud_report`, `settlement_negotiation`, etc. |
| `call_outcome` | Enum | `payment_committed`, `escalated`, `unresolved`, `resolved`, `callback_scheduled`, etc. |
| `key_discussion_points` | Array | 3-7 bullet points |
| `compliance_notes` | Array | Regulatory observations |
| `risk_flags` | Array | Behavioral/fraud risk indicators |
| `action_items` | Array | Required next steps |
| `call_timeline` | Array | Chronological events with significance levels |

### Document API

| Endpoint | Description |
|----------|-------------|
| `GET /call/{id}/document` | Full extracted document |
| `GET /call/{id}/document/financial` | Financial data only |
| `GET /call/{id}/document/export?format=pdf` | PDF report download |
| `POST /call/{id}/document/regenerate` | Re-extract with latest model |
| `GET /documents` | Paginated document listing with filters |
| `POST /documents/search` | Semantic search across all documents |

### PDF Report Sections
1. **Executive Summary** — Purpose, outcome, narrative
2. **Financial Data** — Amounts table, commitments, EMI, outstanding
3. **Commitments & Promises** — With confidence scores and conditions
4. **Key Discussion Points** — Bullet-point highlights
5. **Extracted Entities** — Persons, orgs, dates, locations
6. **Compliance & Risk** — Regulatory notes, risk flags
7. **Call Timeline** — Chronological events with significance markers
8. **Action Items** — Required follow-ups

---

## 📡 API Reference

### Core Pipeline
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/analyze-call` | Main 10-step analysis pipeline |
| `POST` | `/api/v1/knowledge/seed` | Seed knowledge base (run once) |
| `GET` | `/api/v1/knowledge/status` | Check knowledge base readiness |

### Call Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/call/{call_id}` | Get single call record |
| `PATCH` | `/api/v1/call/{call_id}/status` | Update case status |
| `GET` | `/api/v1/calls?page=1&limit=10&status=escalated&risk=high_risk` | Paginated listing |

### Chatbot
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/chat` | RAG-powered knowledge chatbot |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/dashboard/stats` | KPI metrics |
| `GET` | `/api/v1/dashboard/recent-activity` | Activity timeline |
| `GET` | `/api/v1/dashboard/top-patterns` | Pattern frequency |
| `GET` | `/api/v1/dashboard/active-cases` | Unresolved high-risk cases |
| `GET` | `/api/v1/dashboard/health` | System health check |
| `GET` | `/api/v1/dashboard/financial-intelligence` | Aggregated financial data |

### Backboard AI
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/backboard/{call_id}` | Reasoning audit trail |
| `POST` | `/api/v1/backboard/{call_id}/query` | Query call reasoning |
| `POST` | `/api/v1/backboard/memory/query` | Cross-call memory query |
| `GET` | `/api/v1/backboard/threads/all` | List all threads |

### Call Documents
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/call/{id}/document` | Full extracted document |
| `GET` | `/api/v1/call/{id}/document/financial` | Financial data only |
| `GET` | `/api/v1/call/{id}/document/export?format=pdf` | Export as PDF/JSON |
| `POST` | `/api/v1/call/{id}/document/regenerate` | Re-extract document |
| `GET` | `/api/v1/documents` | Paginated document listing |
| `POST` | `/api/v1/documents/search` | Semantic search |

### General
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |

---

## 🗄 Database Schema

### `call_analyses` — Core call records
```sql
call_id             TEXT PRIMARY KEY        -- "call_2026_02_09_a1b2c3"
call_timestamp      TIMESTAMPTZ
call_context        JSONB                   -- language, quality
speaker_analysis    JSONB                   -- customer-only, agent influence
nlp_insights        JSONB                   -- intent, sentiment, entities
risk_signals        JSONB                   -- audio/behavioral flags
risk_assessment     JSONB                   -- score, fraud likelihood
summary_for_rag     TEXT                    -- natural language summary
rag_output          JSONB                   -- grounded reasoning result (Step 7)
summary_embedding   vector(1536)            -- for chatbot vector search
status              TEXT                    -- open | in_review | escalated | resolved
backboard_thread_id TEXT                    -- Backboard audit trail link
```

### `knowledge_embeddings` — Curated knowledge base
```sql
doc_id      TEXT PRIMARY KEY    -- "fp_001", "cr_001", "rh_001"
category    TEXT                -- fraud_pattern | compliance | risk_heuristic
title       TEXT                -- human-readable name
content     TEXT                -- full knowledge document text
embedding   vector(1536)       -- OpenAI embedding for similarity search
metadata    JSONB               -- severity, risk_weight, source
```

### `call_documents` — Extracted per-call intelligence
```sql
doc_id                TEXT PRIMARY KEY
call_id               TEXT REFERENCES call_analyses(call_id)
financial_data        JSONB       -- amounts, commitments, EMI, outstanding
entities              JSONB       -- persons, orgs, dates, locations
commitments           JSONB       -- promises with confidence & conditions
call_summary          TEXT        -- narrative summary
call_purpose          TEXT        -- debt_collection, complaint, etc.
call_outcome          TEXT        -- resolved, escalated, etc.
key_discussion_points JSONB
compliance_notes      JSONB
risk_flags            JSONB
action_items          JSONB
call_timeline         JSONB       -- chronological events
doc_embedding         vector(1536) -- for semantic document search
extraction_model      TEXT        -- gpt-4o-mini / gpt-4o
extraction_tokens     INT
```

### RPC Functions (pgvector)
| Function | Purpose |
|----------|---------|
| `match_knowledge(embedding, category, limit)` | Similarity search on knowledge base |
| `match_calls(embedding, limit)` | Similarity search on past calls |
| `match_call_documents(embedding, limit)` | Similarity search on call documents |
| `dashboard_stats()` | Aggregated KPI numbers |
| `top_patterns(limit)` | Pattern frequency aggregation |
| `financial_summary(days_back)` | Financial intelligence aggregation |

---

## 📁 Project Structure

```
Stentor/
│
├── main.py                          # FastAPI app entry point
├── requirements.txt                 # Python dependencies
│
├── app/
│   ├── api/
│   │   └── routes.py                # All API endpoints (30+ routes)
│   │
│   ├── models/
│   │   └── schemas.py               # Pydantic input/output models (286 lines)
│   │
│   ├── services/
│   │   ├── ingestion.py             # Step 2: Store call record
│   │   ├── embedding.py             # Step 3: OpenAI embedding generation
│   │   ├── retrieval.py             # Step 4: Knowledge chunk retrieval
│   │   ├── context_builder.py       # Step 5: Grounding context assembly
│   │   ├── reasoning.py             # Step 6: LLM grounded reasoning
│   │   ├── updater.py               # Step 7: Store RAG output
│   │   ├── seeding.py               # Knowledge base seeding service
│   │   ├── extraction_service.py    # Step 9: Call document extraction
│   │   ├── pdf_generator.py         # PDF report generation (fpdf2)
│   │   ├── backboard_service.py     # Backboard AI integration
│   │   ├── chat_retrieval.py        # Chatbot: vector search + call lookup
│   │   ├── chat_context.py          # Chatbot: context assembly
│   │   └── chat_reasoning.py        # Chatbot: LLM answer generation
│   │
│   ├── db/
│   │   ├── supabase_client.py       # Lazy singleton Supabase client
│   │   └── queries.py               # All database operations (572 lines)
│   │
│   └── utils/
│       ├── id_generator.py          # call_id + timestamp generation
│       └── helpers.py               # Shared utility functions
│
├── knowledge/                       # Curated knowledge base (JSON)
│   ├── fraud_patterns.json          # 6 fraud behavior patterns
│   ├── compliance_rules.json        # Regulatory compliance rules
│   └── risk_heuristics.json         # Behavioral analysis heuristics
│
└── sql/                             # Database migration scripts
    ├── init.sql                     # Initial schema + RPC functions
    ├── migrate_chatbot.sql          # Chatbot vector search migration
    └── migrate_call_documents.sql   # Call document extraction migration
```

---

## ⚡ Setup & Installation

### Prerequisites
- Python 3.11+
- Supabase project with pgvector extension
- OpenAI API key
- (Optional) Backboard AI API key

### 1. Clone & Install

```bash
git clone <repo-url>
cd Stentor
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file:
```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# OpenAI
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-4o-mini
LLM_MODEL_HIGH_RISK=gpt-4o          # Optional: use GPT-4o for high-risk calls

# Backboard AI (Optional)
BACKBOARD_API_KEY=your-backboard-key

# Retrieval Limits (Optional)
FRAUD_PATTERN_RETRIEVAL_LIMIT=3
COMPLIANCE_RETRIEVAL_LIMIT=2
RISK_HEURISTIC_RETRIEVAL_LIMIT=2
```

### 3. Initialize Database

Run the SQL scripts in your Supabase SQL Editor **in order**:
1. `sql/init.sql` — Creates tables + core RPC functions
2. `sql/migrate_chatbot.sql` — Adds chatbot vector search
3. `sql/migrate_call_documents.sql` — Adds document extraction tables

### 4. Start the Server

```bash
uvicorn main:app --reload --port 8000
```

### 5. Seed Knowledge Base

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/seed
```

### 6. Verify

```bash
# Health check
curl http://localhost:8000/health

# Knowledge status
curl http://localhost:8000/api/v1/knowledge/status

# Dashboard health
curl http://localhost:8000/api/v1/dashboard/health
```

---

## 🔐 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | Yes | — | Supabase project URL |
| `SUPABASE_KEY` | Yes | — | Supabase service role key |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model name |
| `LLM_MODEL` | No | `gpt-4o-mini` | Default LLM model |
| `LLM_MODEL_HIGH_RISK` | No | Same as `LLM_MODEL` | LLM for risk_score ≥ 70 |
| `BACKBOARD_API_KEY` | No | — | Backboard AI API key |
| `FRAUD_PATTERN_RETRIEVAL_LIMIT` | No | `3` | Max fraud patterns to retrieve |
| `COMPLIANCE_RETRIEVAL_LIMIT` | No | `2` | Max compliance docs to retrieve |
| `RISK_HEURISTIC_RETRIEVAL_LIMIT` | No | `2` | Max risk heuristics to retrieve |

---

<p align="center">
  Built for <strong>DevSoc'26</strong> — Financial Audio Intelligence meets RAG
</p>
