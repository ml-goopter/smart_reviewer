# Smart Reviewer MVP — Backend Specification (Trimmed)

> **Superseded in places by [DECISIONS.md](DECISIONS.md)**, which is authoritative.
> Where this document and that one disagree, that one is correct.

## 1. Scope

The Smart Reviewer backend supports one simple flow:

```text
Merchant URL
   ↓
Create Session
   ↓
Validate Session
   ↓
Load Merchant Context
   ↓
Generate AI Suggestions
   ↓
Select Suggestion
   ↓
Complete → Redirect to Google
```

Backend responsibilities:

* Merchant lookup
* Session creation
* Session validation
* Session expiration
* Merchant context retrieval
* AI suggestion generation
* Suggestion persistence
* Suggestion selection
* Completion tracking
* Google review URL delivery
* Basic rate limiting

No users, no auth, no admin system.

---

## 2. Out of Scope

```text
User accounts
Admin dashboards
Payments
Multi-tenancy
RBAC
Analytics dashboards
Google review syncing
Notifications
Merchant self-service
```

---

## 3. Recommended Python Stack (MVP)

Keep it simple and fast to build:

### Core stack

```text
FastAPI (API framework)
PostgreSQL (database)
SQLAlchemy 2.0 (ORM)
Alembic (migrations)
Pydantic (validation)
Uvicorn (server)
```

### AI layer

```text
OpenAI / Anthropic SDK (direct or wrapped service)
```

### Optional (later)

```text
Redis (rate limiting / caching)
Celery (background jobs if needed later)
```

---

## 4. Architecture

```text
FastAPI Routes
   ↓
Service Layer
   ↓
Repository Layer
   ↓
PostgreSQL
   ↓
AI Provider
```

Keep everything in **one monolith service**.

---

## 5. Core Data Models

```text
merchants
merchant_review_context
smart_review_sessions
smart_review_suggestions
smart_review_events
```

---

## 6. Merchant Model

```text
id
name
category
description
google_review_url
status
created_at
```

Rule:

```text
Session can only be created if:
- merchant exists
- status = ACTIVE
- google_review_url exists
```

---

## 7. Merchant Review Context

```text
merchant_id
business_summary
products
services
menu_items
selling_points
approved_keywords
experience_topics
custom_instructions
is_approved
```

Optional but improves AI quality.

---

## 8. Session Model (SIMPLIFIED)

Removed token hashing entirely.

```text
id
merchant_id
token              ← plain text
status             ← ACTIVE | COMPLETED | EXPIRED
created_at
expires_at

selected_suggestion_id

open_count
generation_count
suggestion_count
```

---

## 9. Session Token (SIMPLIFIED)

### Generate:

```python
import secrets

token = secrets.token_urlsafe(32)
```

### Properties:

```text
- cryptographically secure
- unguessable
- stored in plaintext
- expires via expires_at
```

No hashing, no complexity.

---

## 10. Session Validation

```text
token lookup
   ↓
find session WHERE token = ?
   ↓
check:
   - status == ACTIVE
   - expires_at > now
   - merchant valid
```

---

## 11. Expiration Rule

```text
expires_at is authoritative
```

If expired:

```text
return 410 Gone
```

No background job required.

---

## 12. API Endpoints

### 0. Merchant Entry Redirect

```http
GET /m/{merchantId}
```

Not under `/api` — this is a browser-facing route, the target of the merchant's
permanent QR code. FastAPI validates the merchant, creates a session, and
redirects. The frontend never creates sessions.

```text
302 → /r/{token}        Cache-Control: no-store
```

Merchant unknown, inactive, archived, or missing `google_review_url`:

```text
302 → /unavailable      Cache-Control: no-store
```

Rules:

* **`302`, never `301`/`308`.** A permanent redirect is cached, so the next scan
  of the same QR would skip the API and reuse a dead token.
* **`Cache-Control: no-store`** for the same reason.
* **Never render HTML here.** The SPA owns `/unavailable`.
* All failure causes share one destination — the difference is the merchant's
  private information.
* The customer's IP arrives natively via `X-Real-IP` from nginx, so the create
  rate limit works without any header forwarding.

---

### 1. Create Session

```http
POST /api/review/sessions
```

```json
{
  "merchantId": "uuid"
}
```

Response:

```json
{
  "token": "abc123..."
}
```

---

### 2. Get Session

```http
GET /api/review/sessions/{token}
```

Returns:

```json
{
  "merchant": {
    "name": "Pho 37",
    "category": "Restaurant"
  },
  "suggestions": [],
  "googleReviewUrl": "https://..."
}
```

Does **not** generate suggestions. Validation only — see DECISIONS.md R4.
The client calls `POST /sessions/{token}/suggestions` for the first batch.

---

### 3. Generate Suggestions

```http
POST /api/review/sessions/{token}/suggestions
```

Returns 3 AI suggestions.

---

### 4. Select Suggestion

```http
POST /api/review/sessions/{token}/select
```

```json
{
  "suggestionId": "uuid"
}
```

---

### 5. Complete Session

```http
POST /api/review/sessions/{token}/complete
```

Best-effort only.

---

## 13. AI Suggestion Generation

### Input:

* merchant info
* review context
* optional previous suggestions

### Output:

```json
{
  "suggestions": [
    "text 1",
    "text 2",
    "text 3"
  ]
}
```

Rules:

* up to 3 suggestions per batch (only those that validate are stored — DECISIONS.md R11)
* 20–500 chars
* no HTML
* no URLs unless allowed

---

## 14. Suggestion Rules

```text
Each session:
  multiple generations allowed

Each generation:
  increment generation_number

Store all suggestions
```

---

## 15. Rate Limiting (MVP SIMPLE)

```text
POST session creation: per IP limit
POST generate: per session limit
```

Counted in the database, not in process memory: in-memory counters are
per-worker and per-instance, so `--workers 4` would silently quadruple the
limit. See DECISIONS.md R6.

---

## 16. Events (MINIMAL)

Only track:

```text
SESSION_CREATED
SESSION_OPENED

SUGGESTIONS_GENERATED

SUGGESTION_SELECTED

SESSION_COMPLETED
```

No heavy analytics.

---

## 17. Security Model (SIMPLIFIED)

* token is secret
* expires quickly
* no user accounts
* no auth system
* no hashing needed

Security relies on:

```text
- randomness
- expiration
- rate limiting
```

---

## 18. Database Constraints

```sql
UNIQUE(token)
```

That’s it.

No token_hash.

---

## 19. Key Simplifications Made

Removed:

* ❌ token hashing
* ❌ SHA-256 lookup layer
* ❌ dual token model
* ❌ unnecessary security abstraction
* ❌ complex event system
* ❌ background jobs requirement
* ❌ over-engineered service boundaries

---

## 20. Final Backend Flow

```text
POST /sessions
  → create token
  → store session

GET /sessions/:token
  → validate
  → load merchant
  → return suggestions

POST /suggestions
  → call AI
  → store batch

POST /select
  → update selected_suggestion_id

POST /complete
  → mark completed_at
```

---

## 21. Final Principle

> The token is a temporary capability key, not a long-term credential.

So:

* it is random
* it expires
* it is stored directly
* it is safe enough for MVP

---

