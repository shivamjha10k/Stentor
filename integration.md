# Integration Guide

Two services integrate with the RAG Pipeline:

1. **NLP Service** → sends call analysis data → `POST /api/v1/analyze-call`
2. **Frontend Chatbot** → sends user questions → `POST /api/v1/chat`

---

## 1. NLP Service Integration

The NLP service processes raw call audio and sends structured risk signals to the RAG pipeline for grounding against the knowledge base.

### Endpoint

```
POST http://<RAG_HOST>:8000/api/v1/analyze-call
Content-Type: application/json
```

### Expected Input from NLP Service

```json
{
  "call_context": {
    "call_language": "Are you seeing this one? OK. Index.Gsfile. Yeah. There you go. Yeah. This is. Personalized form. I'm not getting this. hinglish",
    "call_quality": {
      "noise_level": "medium",
      "call_stability": "low",
      "speech_naturalness": "suspicious"
    }
  },
  "speaker_analysis": {
    "customer_only_analysis": true,
    "agent_influence_detected": false
  },
  "nlp_insights": {
    "intent": {
      "label": "repayment_promise",
      "confidence": 0.6,
      "conditionality": "high"
    },
    "sentiment": {
      "label": "stressed",
      "confidence": 0.82
    },
    "obligation_strength": "weak",
    "entities": {
      "payment_commitment": "next_week",
      "amount_mentioned": null
    },
    "contradictions_detected": true
  },
  "risk_signals": {
    "audio_trust_flags": ["low_call_stability", "unnatural_speech_pattern"],
    "behavioral_flags": ["conditional_commitment", "evasive_responses", "statement_contradiction"]
  },
  "risk_assessment": {
    "risk_score": 78,
    "fraud_likelihood": "high",
    "confidence": 0.81
  },
  "summary_for_rag": "Customer made a conditional repayment promise, showed stress, and contradicted earlier statements, which aligns with known high-risk call patterns."
}
```

### Field Reference

| Field | Type | Required | Allowed Values |
|---|---|---|---|
| `call_context.call_language` | string | YES | any language string |
| `call_context.call_quality.noise_level` | string | YES | `low`, `medium`, `high` |
| `call_context.call_quality.call_stability` | string | YES | `low`, `medium`, `high` |
| `call_context.call_quality.speech_naturalness` | string | YES | `natural`, `suspicious` |
| `speaker_analysis.customer_only_analysis` | bool | YES | `true`, `false` |
| `speaker_analysis.agent_influence_detected` | bool | YES | `true`, `false` |
| `nlp_insights.intent.label` | string | YES | e.g. `repayment_promise`, `dispute`, `inquiry` |
| `nlp_insights.intent.confidence` | float | YES | 0.0 – 1.0 |
| `nlp_insights.intent.conditionality` | string | YES | `low`, `medium`, `high` |
| `nlp_insights.sentiment.label` | string | YES | e.g. `cooperative`, `stressed`, `angry`, `neutral` |
| `nlp_insights.sentiment.confidence` | float | YES | 0.0 – 1.0 |
| `nlp_insights.obligation_strength` | string | YES | `strong`, `moderate`, `weak` |
| `nlp_insights.entities.payment_commitment` | string | NO | e.g. `tomorrow`, `next_week`, `null` |
| `nlp_insights.entities.amount_mentioned` | float | NO | e.g. `5000`, `null` |
| `nlp_insights.contradictions_detected` | bool | YES | `true`, `false` |
| `risk_signals.audio_trust_flags` | string[] | YES | e.g. `["low_call_stability", "unnatural_speech_pattern"]` |
| `risk_signals.behavioral_flags` | string[] | YES | e.g. `["conditional_commitment", "evasive_responses"]` |
| `risk_assessment.risk_score` | int | YES | 0 – 100 |
| `risk_assessment.fraud_likelihood` | string | YES | `low`, `medium`, `high` |
| `risk_assessment.confidence` | float | YES | 0.0 – 1.0 |
| `summary_for_rag` | string | YES | Min 10 chars. Human-readable summary of the call. |

### Response from RAG (200 OK)

```json
{
  "call_id": "call_2026_02_09_a1b2c3",
  "call_timestamp": "2026-02-09T12:00:00+00:00",
  "input_risk_assessment": {
    "risk_score": 78,
    "fraud_likelihood": "high",
    "confidence": 0.81
  },
  "rag_output": {
    "grounded_assessment": "high_risk",
    "explanation": "The call signals match the 'Conditional Promise with Contradiction' fraud pattern (fp_001). The customer's conditional repayment promise with high conditionality, combined with stressed sentiment and detected contradictions, strongly aligns with known high-risk indicators.",
    "recommended_action": "escalate_to_compliance",
    "confidence": 0.88,
    "regulatory_flags": ["RBI verbal commitment recording required"],
    "matched_patterns": ["Conditional Promise with Contradiction", "Evasive Response Pattern"]
  }
}
```

### Response Fields

| Field | Type | Values |
|---|---|---|
| `call_id` | string | Auto-generated, format `call_YYYY_MM_DD_hexhex` |
| `call_timestamp` | ISO 8601 | UTC timestamp |
| `rag_output.grounded_assessment` | string | `high_risk`, `medium_risk`, `low_risk` |
| `rag_output.recommended_action` | string | `auto_clear`, `flag_for_review`, `manual_review`, `escalate_to_compliance` |
| `rag_output.confidence` | float | 0.0 – 1.0 |
| `rag_output.regulatory_flags` | string[] | Compliance concerns (empty if none) |
| `rag_output.matched_patterns` | string[] | Knowledge base patterns that matched |

### Error Responses

| Status | When |
|---|---|
| 422 | Invalid or missing fields in payload |
| 500 | Embedding, LLM, or DB failure |
| 503 | Knowledge base not seeded yet |

---

## 2. Frontend Chatbot Integration

The frontend sends user questions and receives grounded answers from the knowledge base and past call history.

### Endpoint

```
POST http://<RAG_HOST>:8000/api/v1/chat
Content-Type: application/json
```

### Basic Request (Minimal)
Participants in the airport, please go and get your attendance. And he start being stealing. Because the translator. Is successful. Cortana. Sing. But now? Hey, Cortana. Play. Majority of them. Please go on. Yes, she. Xbox. I repeat, is going really funny. Who has not given the attention here? Please go and do it right now. Hey, Cortana. My friend. You are very important. Thank you for your time. Hey, Cortana. Hey, Cortana. Click on the middle. Accept dates. With HD on Valentine's. I. Stiffness and demand. Setting. S. Hey Cortana, play me. This is what you think of this is. Next series. Know how much this is your attendance. Do you know about? Doing this. I'll be back soon to get some. I got to talk to me. Take me to. The three of my friends. Thank you. So we have. Now you know it. The mural. Not today. Competition. Blackboard. MOPWNL 2394 24. Double 98159767. 9162. And adding to all the groups. Are there somebody else? But what was convenient by what come here? Yeah. Name. Theme team Ferrari. Please. Hello, I repeat. I repeat this, any organizing committee member left to scan the ID. Hi, Babu. I repeat. Hello. Hello. My name. Yeah. So. Meeting. Yeah. Because a team member. Feed it. Design. So design we did in Pigment Design 1435. 30. Cortana. Hello. Hello. Once again, this is back and getting the one. Again. And. Hey, Cortana. Which is better than Indian? Battery. I used to work through Ajit. Hey. Rejects to meet you. I explained. Hi, I'm. Hey, Cortana. Awesome. Change. Or. Specially doing the. Reduction. You may go to the discord under the important resources tab, you will find a google link that google link as a data center for both the problems for. Kyle, please listen to me. The sponsor have just now given me the data set and this will be the only data set that we will be testing your project on. Please look into it. I promise it's not something which is Diwali chop your main problem. It is a very basic data set. Actually it is the real data set that we are working with. Please follow it. Hot food. I mean sorry people who are using output trap. May I have your attention please on. Discord under the Important Resources tab. We have uploaded the data set. Client participants. Participants, I'm repeating again the data set for both the problems for hot food has been uploading as digital dry Glen through the Discord trouble. Participants and repeated for one last time. Again, the data set plugin required for the Hot Food challenge has been uploaded on Discord. Find me, follow that. Whatever what we are working on, you're gonna get away the same. You just need to use the data set that has been provided to you. It should not be very difficult. You just have to change few parameters. It is very very doable. We receive the data, we share the data set to you as soon as we research, receive them from the sponsors. Call Salman. No. Hello. Problem that you were following had a has now a excel sheet gateways data set so all the OCR based ideas will not be required here. That being said it also makes your task a little more easier. Media. Yeah. Thanks and friends not familiar. Most of them. Hello. From the sea for the homes to give a few thousand. Weeks to that, another thing don't. People have chosen the first challenge who are dealing with audio files. When you run the audio files, some of you have complained that only the dark 20 seconds of it play. Now there are two options. What is that audio? I consider the last 20 of them 20 seconds of that. So you can you can still whatever you're working. And we try to consider that as well, just because we also feel that the audio may not be substantially good enough, even the 20 seconds. But if you don't work with the 22nd, that will also have a weightage if you're not able to do that. And if you feel that that 22nd is not good enough for your model, you can continue working on whatever you're doing. We are making this arrangement because I know it's a little late for you for us to share the data set with you. So we're OK with that, but the second job no PR ideas. Will be accepted. You'll have to use the extra sheets that are given that is primarily your data set. Say. Thank you. Both. Actually. Political actions. ITE logic Explorer. We've been putting it for 7.3. Straight out. Of the pictures. When we first made. Perfect. And you know. Maybe we can make it to Christmas. Christmas. Have you ever? Maybe church steps? After not eating us getting back says i'm sad you can lose Jesus. Hey, hey, sorry, give me second. Send. It has to be. Where did that end? I'm there as soon as I.      
```json
{
  "question": "What are the indicators of conditional promise fraud?"
}
```

### Full Request (All Options)

```json
{
  "question": "Which fraud patterns involve contradictions?",
  "conversation_history": [
    {
      "role": "user",
      "content": "What are the main fraud patterns?"
    },
    {
      "role": "assistant",
      "content": "The knowledge base contains six fraud patterns including conditional promises, emotional manipulation, and evasive responses."
    }
  ],
  "filters": {
    "search_knowledge": true,
    "search_calls": true,
    "categories": ["fraud_pattern", "compliance", "risk_heuristic"],
    "knowledge_limit": 5,
    "calls_limit": 3
  }
}
```

### Field Reference

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `question` | string | YES | — | Min 5 chars. The user's question. |
| `conversation_history` | array | NO | `[]` | Previous messages for multi-turn context. |
| `conversation_history[].role` | string | YES (if history sent) | — | `user` or `assistant` |
| `conversation_history[].content` | string | YES (if history sent) | — | Message text |
| `filters.search_knowledge` | bool | NO | `true` | Search knowledge base (fraud patterns, compliance, heuristics) |
| `filters.search_calls` | bool | NO | `false` | Search past call analyses via vector similarity |
| `filters.categories` | string[] | NO | all three | `fraud_pattern`, `compliance`, `risk_heuristic` |
| `filters.knowledge_limit` | int | NO | `5` | Max knowledge docs to retrieve (1–10) |
| `filters.calls_limit` | int | NO | `3` | Max past calls to retrieve (1–10) |
Presented Cortana. Some of the files. But the point is why? For the digital. Passport. Blockchain. Plus. Hey, Cortana, Cybersec networking. Cyber network. Cyber sex. Networking, then it's AI. Miss network. Planetary. Agitech or Space Tech? Automated sustainability. Also you guys can search and if you like some other idea then let us know. So database access. What are you doing? NGR, NGR, OK. So expected for me to dwell. You have been a little bit sure of me. Living just. A little bit of reason if you would be anything. Meri and I'm happy about my team. I see a city. I Yeah, I see that I've been starting. Either of. Request you can send. No requests. 0.8. Or. Purchase. Baby. Plus one, honestly. Is anybody in office self payment time? For latency. Fake banana. Yeah, we business with right now maybe something. What's up with you? Facebook. Browser. The question I've matched. Now skip 6. Need to go to. 
### Response (200 OK)

```json
{
  "answer": "The 'Conditional Promise with Contradiction' pattern (fp_001) is triggered when a customer makes a payment promise with high conditionality and then contradicts prior statements. Historical data shows 73% of such calls result in non-payment.",
  "sources": [
    {
      "type": "knowledge",
      "doc_id": "fp_001",
      "category": "fraud_pattern",
      "title": "Conditional Promise with Contradiction",
      "similarity": 0.92
    },
    {
      "type": "call",
      "doc_id": "call_2026_02_09_d5de2d",
      "category": "call_analysis",
      "title": "Risk=15 | low",
      "similarity": 0.57
    }
  ],
  "metadata": {
    "knowledge_docs_searched": 5,
    "calls_searched": 1,
    "model": "gpt-4o-mini",
    "tokens_used": 942
  }
}
```

### Response Fields

| Field | Type | Description |
|---|---|---|
| `answer` | string | Grounded answer citing specific documents |
| `sources` | array | Documents used to generate the answer |
| `sources[].type` | string | `knowledge` (from knowledge base) or `call` (from past calls) |
| `sources[].doc_id` | string | Document or call ID |
| `sources[].category` | string | `fraud_pattern`, `compliance`, `risk_heuristic`, or `call_analysis` |
| `sources[].similarity` | float | Cosine similarity score (0–1, higher = more relevant) |
| `metadata.knowledge_docs_searched` | int | Number of knowledge docs retrieved |
| `metadata.calls_searched` | int | Number of past calls retrieved |
| `metadata.model` | string | LLM model used |
| `metadata.tokens_used` | int | Total tokens consumed |

### Frontend Implementation Notes

1. **Store conversation history client-side** — send it with each request for multi-turn
2. **Cap history at 10 messages** — the server truncates beyond that
3. **`search_calls` is OFF by default** — enable it only when user asks about past calls
4. **Sources are clickable** — use `doc_id` to link to knowledge doc or `call_id` to open call detail via `GET /api/v1/call/{call_id}`
5. **Similarity scores** — display as relevance percentage (e.g. `0.92` → `92% match`)

### Error Responses

| Status | When |
|---|---|
| 422 | Question too short (<5 chars) or invalid filters |
| 503 | Knowledge base not seeded |

---

## Other Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health check → `{"status": "ok"}` |
| `POST` | `/api/v1/knowledge/seed` | Seed knowledge base (run once) |
| `GET` | `/api/v1/knowledge/status` | Check knowledge doc count |
| `GET` | `/api/v1/call/{call_id}` | Fetch a specific call record |
