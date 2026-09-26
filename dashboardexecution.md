# Dashboard Execution Plan — "Command Center" Backend

Backend routes, schema changes, and SQL needed to power the frontend dashboard.

---

## Schema Changes

### 1. Add `status` column to `call_analyses`

The dashboard needs a Resolution Rate (% of cases resolved). Currently there's no status tracking on calls. Add a `status` column:

```sql
ALTER TABLE call_analyses
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';
```

**Allowed values:** `open` | `in_review` | `escalated` | `resolved`

**Auto-assignment logic (in the pipeline):**
When `rag_output` is stored (Step 7), derive the initial status from `recommended_action`:

| `recommended_action`       | Initial `status` |
|----------------------------|-------------------|
| `auto_clear`               | `resolved`        |
| `flag_for_review`          | `in_review`       |
| `manual_review`            | `in_review`       |
| `escalate_to_compliance`   | `escalated`       |

Frontend can later PATCH the status to `resolved` when a human closes a case.

### 2. No other table changes needed

The existing `call_analyses` and `knowledge_embeddings` tables have all other required data:
- `risk_assessment->>'risk_score'` — risk score
- `risk_assessment->>'fraud_likelihood'` — risk tier
- `rag_output->>'grounded_assessment'` — grounded risk level
- `rag_output->>'matched_patterns'` — patterns array
- `rag_output->>'recommended_action'` — action taken
- `call_timestamp` — for "today" filtering

---

## SQL Migration

Run in Supabase SQL Editor **once**:

```sql
-- 1. Add status column
ALTER TABLE call_analyses
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'open';

-- 2. Backfill existing rows based on recommended_action
UPDATE call_analyses
SET status = CASE
    WHEN rag_output->>'recommended_action' = 'auto_clear' THEN 'resolved'
    WHEN rag_output->>'recommended_action' = 'escalate_to_compliance' THEN 'escalated'
    WHEN rag_output->>'recommended_action' IN ('flag_for_review', 'manual_review') THEN 'in_review'
    ELSE 'open'
END
WHERE rag_output IS NOT NULL;

-- 3. Index for status-based dashboard queries
CREATE INDEX IF NOT EXISTS idx_call_analyses_status
    ON call_analyses (status);

-- 4. RPC: Dashboard stats (single call returns all KPIs)
CREATE OR REPLACE FUNCTION dashboard_stats()
RETURNS JSON
LANGUAGE plpgsql
AS $$
DECLARE
    result JSON;
BEGIN
    SELECT json_build_object(
        'total_calls', (SELECT COUNT(*) FROM call_analyses),
        'total_calls_today', (
            SELECT COUNT(*) FROM call_analyses
            WHERE call_timestamp::date = CURRENT_DATE
        ),
        'high_risk_count', (
            SELECT COUNT(*) FROM call_analyses
            WHERE rag_output->>'grounded_assessment' = 'high_risk'
        ),
        'medium_risk_count', (
            SELECT COUNT(*) FROM call_analyses
            WHERE rag_output->>'grounded_assessment' = 'medium_risk'
        ),
        'low_risk_count', (
            SELECT COUNT(*) FROM call_analyses
            WHERE rag_output->>'grounded_assessment' = 'low_risk'
        ),
        'avg_risk_score', (
            SELECT ROUND(AVG((risk_assessment->>'risk_score')::NUMERIC), 1)
            FROM call_analyses
            WHERE risk_assessment->>'risk_score' IS NOT NULL
        ),
        'resolution_rate', (
            SELECT ROUND(
                COUNT(*) FILTER (WHERE status = 'resolved')::NUMERIC
                / GREATEST(COUNT(*), 1) * 100,
                1
            )
            FROM call_analyses
        ),
        'status_breakdown', (
            SELECT json_object_agg(status, cnt)
            FROM (
                SELECT status, COUNT(*) AS cnt
                FROM call_analyses
                GROUP BY status
            ) sub
        )
    ) INTO result;
    RETURN result;
END;
$$;

-- 5. RPC: Top matched patterns (aggregated across all calls)
CREATE OR REPLACE FUNCTION top_patterns(pattern_limit INT DEFAULT 10)
RETURNS TABLE (
    pattern TEXT,
    match_count BIGINT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.pattern,
        COUNT(*) AS match_count
    FROM call_analyses ca,
         jsonb_array_elements_text(ca.rag_output->'matched_patterns') AS p(pattern)
    WHERE ca.rag_output IS NOT NULL
      AND ca.rag_output->'matched_patterns' IS NOT NULL
    GROUP BY p.pattern
    ORDER BY match_count DESC
    LIMIT pattern_limit;
END;
$$;
```

---

## New API Routes

All new routes live under `GET /api/v1/dashboard/*`.

---

### Route 1: `GET /api/v1/dashboard/stats`

Returns all KPI numbers for the hero stats row.

**Query:** Calls `dashboard_stats()` RPC.

**Response (200):**

```json
{
  "total_calls": 47,
  "total_calls_today": 12,
  "high_risk_count": 8,
  "medium_risk_count": 22,
  "low_risk_count": 17,
  "avg_risk_score": 54.3,
  "resolution_rate": 36.2,
  "status_breakdown": {
    "open": 5,
    "in_review": 18,
    "escalated": 7,
    "resolved": 17
  }
}
```

**Frontend maps to:**

| Card               | Field                          |
|--------------------|-------------------------------|
| Total Calls        | `total_calls` + `total_calls_today` as subtext |
| High Risk Cases    | `high_risk_count`             |
| Avg Risk Score     | `avg_risk_score`              |
| Resolution Rate    | `resolution_rate` (%)         |

Risk distribution chart uses `high_risk_count`, `medium_risk_count`, `low_risk_count`.

---

### Route 2: `GET /api/v1/dashboard/recent-activity`

Returns the last N calls with their outcomes for the activity timeline.

**Query params:**

| Param  | Type | Default | Description            |
|--------|------|---------|------------------------|
| `limit`| int  | 5       | Number of recent calls (max 20) |

**DB Query:**

```python
client.table("call_analyses")
    .select("call_id, call_timestamp, status, summary_for_rag, risk_assessment, rag_output")
    .not_.is_("rag_output", "null")
    .order("call_timestamp", desc=True)
    .limit(limit)
    .execute()
```

**Response (200):**

```json
{
  "recent_activity": [
    {
      "call_id": "call_2026_02_09_d5de2d",
      "call_timestamp": "2026-02-09T18:30:00+00:00",
      "status": "escalated",
      "risk_score": 78,
      "fraud_likelihood": "high",
      "grounded_assessment": "high_risk",
      "recommended_action": "escalate_to_compliance",
      "summary": "Customer made a conditional repayment promise..."
    }
  ]
}
```

**Frontend maps to:** Timeline entries with icons:
- `escalated` → red alert icon
- `in_review` → yellow review icon
- `resolved` → green check icon
- `open` → grey circle icon

---

### Route 3: `GET /api/v1/dashboard/top-patterns`

Returns aggregated pattern counts across all calls.

**Query params:**

| Param  | Type | Default | Description          |
|--------|------|---------|----------------------|
| `limit`| int  | 10      | Max patterns (max 20)|

**Query:** Calls `top_patterns(limit)` RPC.

**Response (200):**

```json
{
  "patterns": [
    { "pattern": "Conditional Promise with Contradiction", "count": 4 },
    { "pattern": "Evasive Response Pattern", "count": 3 },
    { "pattern": "Emotional Manipulation via Urgency", "count": 1 }
  ]
}
```

**Frontend maps to:** Horizontal pills: `"Conditional Promise × 4"`, `"Evasive Response × 3"`, etc.

---

### Route 4: `GET /api/v1/dashboard/active-cases`

Returns top N highest-risk unresolved call cards (for the Active Cases Preview).

**Query params:**

| Param  | Type | Default | Description             |
|--------|------|---------|-------------------------|
| `limit`| int  | 3       | Number of cases (max 10)|

**DB Query:**

```python
client.table("call_analyses")
    .select("*")
    .not_.is_("rag_output", "null")
    .neq("status", "resolved")
    .order("call_timestamp", desc=True)
    .limit(limit)
    .execute()
```

Then sort in Python by `risk_assessment->risk_score` descending (Supabase doesn't natively sort by JSONB value in the client).

**Response (200):**

```json
{
  "active_cases": [
    {
      "call_id": "call_2026_02_09_d5de2d",
      "call_timestamp": "2026-02-09T18:30:00+00:00",
      "status": "escalated",
      "call_context": { ... },
      "speaker_analysis": { ... },
      "nlp_insights": { ... },
      "risk_signals": { ... },
      "risk_assessment": { "risk_score": 78, "fraud_likelihood": "high", "confidence": 0.81 },
      "rag_output": {
        "grounded_assessment": "high_risk",
        "explanation": "...",
        "recommended_action": "escalate_to_compliance",
        "confidence": 0.88,
        "regulatory_flags": ["..."],
        "matched_patterns": ["..."]
      },
      "summary_for_rag": "..."
    }
  ],
  "total_active": 12
}
```

**Frontend:** Renders top 3 cards using existing card design + "View All Cases →" linking to `/cases`.

---

### Route 5: `PATCH /api/v1/call/{call_id}/status`

Allows frontend to update case status (e.g., mark as resolved after review).

**Request body:**

```json
{
  "status": "resolved"
}
```

**Validation:** Status must be one of `open`, `in_review`, `escalated`, `resolved`.

**Response (200):**

```json
{
  "call_id": "call_2026_02_09_d5de2d",
  "status": "resolved",
  "updated": true
}
```

**Error responses:**

| Status | When                          |
|--------|-------------------------------|
| 404    | Call ID not found              |
| 422    | Invalid status value           |

---

### Route 6: `GET /api/v1/dashboard/health`

System health indicator for the dashboard.

**Response (200):**

```json
{
  "status": "healthy",
  "components": {
    "database": true,
    "knowledge_base": { "ready": true, "doc_count": 16 },
    "embedding_service": true
  }
}
```

**Logic:**
- `database`: try `get_knowledge_count()` — if no exception, `true`
- `knowledge_base.ready`: `doc_count > 0`
- `embedding_service`: try `embed_text("health check")` — if no exception, `true` (cache/skip if called recently)

---

### Route 7: `GET /api/v1/calls`

Paginated call listing for the "Cases" page (existing `/call/{call_id}` fetches a single record — this lists many).

**Query params:**

| Param   | Type   | Default  | Description                                      |
|---------|--------|----------|--------------------------------------------------|
| `page`  | int    | 1        | Page number                                      |
| `limit` | int    | 10       | Results per page (max 50)                         |
| `status`| string | (none)   | Filter by status: `open`, `in_review`, `escalated`, `resolved` |
| `risk`  | string | (none)   | Filter by grounded_assessment: `high_risk`, `medium_risk`, `low_risk` |
| `sort`  | string | `recent` | `recent` (timestamp desc), `risk` (risk_score desc) |

**Response (200):**

```json
{
  "calls": [ ... ],
  "pagination": {
    "page": 1,
    "limit": 10,
    "total": 47,
    "total_pages": 5
  }
}
```

---

## Route Summary Table

| Method  | Endpoint                          | Purpose                          | New? |
|---------|-----------------------------------|----------------------------------|------|
| `GET`   | `/api/v1/dashboard/stats`         | KPI numbers + risk distribution  | NEW  |
| `GET`   | `/api/v1/dashboard/recent-activity`| Timeline of recent outcomes      | NEW  |
| `GET`   | `/api/v1/dashboard/top-patterns`  | Aggregated pattern frequency     | NEW  |
| `GET`   | `/api/v1/dashboard/active-cases`  | Top N highest-risk open cases    | NEW  |
| `GET`   | `/api/v1/dashboard/health`        | System health for status badge   | NEW  |
| `PATCH` | `/api/v1/call/{call_id}/status`   | Update case status               | NEW  |
| `GET`   | `/api/v1/calls`                   | Paginated case listing           | NEW  |
| `GET`   | `/api/v1/call/{call_id}`          | Single call detail               | EXISTS |
| `POST`  | `/api/v1/analyze-call`            | Pipeline (unchanged)             | EXISTS |
| `POST`  | `/api/v1/chat`                    | Chatbot (unchanged)              | EXISTS |
| `GET`   | `/health`                         | Basic health (unchanged)         | EXISTS |

---

## Pipeline Change (Step 7 Update)

When `rag_output` is stored in Step 7 (`updater.py` / `routes.py`), also write the derived `status`:

```python
# In routes.py, after Step 7 (store_rag_output):
ACTION_TO_STATUS = {
    "auto_clear": "resolved",
    "flag_for_review": "in_review",
    "manual_review": "in_review",
    "escalate_to_compliance": "escalated",
}
initial_status = ACTION_TO_STATUS.get(rag_output["recommended_action"], "open")

# Update status in DB
client.table("call_analyses").update({"status": initial_status}).eq("call_id", call_id).execute()
```

---

## New DB Query Functions Needed (`queries.py`)

```
get_dashboard_stats()         → calls dashboard_stats() RPC
get_recent_activity(limit)    → SELECT recent calls with rag_output
get_top_patterns(limit)       → calls top_patterns() RPC
get_active_cases(limit)       → SELECT unresolved calls, sort by risk
update_call_status(call_id, status) → UPDATE status column
get_calls_paginated(page, limit, status_filter, risk_filter, sort) → paginated SELECT
```

---

## Pydantic Schemas Needed (`schemas.py`)

```python
class DashboardStats(BaseModel):
    total_calls: int
    total_calls_today: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    avg_risk_score: float
    resolution_rate: float
    status_breakdown: dict[str, int]

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
    status: str = Field(..., pattern="^(open|in_review|escalated|resolved)$")

class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    total_pages: int

class CallsListResponse(BaseModel):
    calls: list[dict]
    pagination: PaginationMeta

class HealthComponent(BaseModel):
    database: bool
    knowledge_base: dict
    embedding_service: bool

class SystemHealth(BaseModel):
    status: str
    components: HealthComponent
```

---

## Implementation Order

| Phase | Task                                                  | Files Changed                |
|-------|-------------------------------------------------------|------------------------------|
| 1     | Run SQL migration (add status, backfill, RPCs)        | Supabase SQL Editor          |
| 2     | Add `update_call_status` + dashboard query funcs      | `app/db/queries.py`          |
| 3     | Add dashboard Pydantic schemas                        | `app/models/schemas.py`      |
| 4     | Update Step 7 to write initial `status`               | `app/api/routes.py`          |
| 5     | Add dashboard routes (stats, activity, patterns, cases)| `app/api/routes.py`         |
| 6     | Add `PATCH /call/{call_id}/status`                    | `app/api/routes.py`          |
| 7     | Add `GET /calls` paginated listing                    | `app/api/routes.py`          |
| 8     | Add `GET /dashboard/health`                           | `app/api/routes.py`          |
| 9     | Test all routes                                       | Terminal (curl/Invoke-RestMethod) |

---

## CORS

Already configured — `allow_origins=["*"]`. No change needed.

---

## Frontend Route Mapping

| Frontend Route | Backend Source                    |
|----------------|----------------------------------|
| `/` (dashboard) | `GET /dashboard/stats` + `GET /dashboard/recent-activity` + `GET /dashboard/top-patterns` + `GET /dashboard/active-cases` |
| `/cases`       | `GET /calls?page=1&limit=10`     |
| `/cases/:id`   | `GET /call/{call_id}`            |
| `/chat`        | `POST /chat`                     |
