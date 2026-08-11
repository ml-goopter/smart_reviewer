# Smart Reviewer MVP — Frontend / Backend API Contracts

> **Superseded in places by [DECISIONS.md](DECISIONS.md)**, which is authoritative.
> Where this document and that one disagree, that one is correct.

## Scope

This document defines the API contract between the Smart Reviewer Web App frontend and backend for the MVP.

The frontend is a Vite SPA with two routes:

```text
/r/:token
/unavailable
```

`/m/:merchantId` is served by **FastAPI**, not the frontend. It creates the
session and redirects. See DECISIONS.md "Architecture revision".

```text
GET /m/:merchantId
  → 302 /r/:token        Cache-Control: no-store
  → 302 /unavailable     merchant unavailable, any cause
```

The API surface contains five endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/m/:merchantId` | **Browser-facing.** Create a session and redirect to it |
| `POST` | `/api/review/sessions` | Create a new session for a merchant (called internally by the route above) |
| `GET` | `/api/review/sessions/:token` | Validate/load a session and return the Google review URL |
| `POST` | `/api/review/sessions/:token/suggestions` | Generate another suggestion batch |
| `POST` | `/api/review/sessions/:token/select` | Record the selected suggestion |
| `POST` | `/api/review/sessions/:token/complete` | Best-effort session update before leaving for Google |

---

# 1. Create Review Session

**Endpoint**

```http
POST /api/review/sessions
```

| Item | Contract |
|---|---|
| Purpose | Create a temporary review session for a merchant |
| Authentication | None |
| Request body | `{ "merchantId": "uuid" }` |
| Success status | `201 Created` |
| Success response | `{ "token": "secure-session-token" }` |
| Backend validates | Merchant exists, is active, and has a Google review URL |
| Backend creates | `smart_review_sessions` record |
| Backend generates | Cryptographically secure session token |
| Backend stores | The token directly (plaintext). See DECISIONS.md R2 |
| Backend sets | `expires_at`, `status = ACTIVE` |
| Called by | `GET /m/:merchantId`, server-side. The SPA never calls this |
| Rate limiting | Required |

## Request

```json
{
  "merchantId": "8e09301f-f928-43d5-9f60-d1287ab98f01"
}
```

## Success Response

```json
{
  "token": "Ks92MxD7yP..."
}
```

## Error Contract

| Status | Meaning | Frontend Behavior |
|---|---|---|
| `400` | Invalid merchant ID format | Show unavailable-link state |
| `404` | Merchant does not exist | Show unavailable-link state |
| `409` | Merchant cannot create sessions | Show unavailable-link state |
| `429` | Rate limited | Show retryable error |
| `500` | Unexpected backend failure | Show generic error |

The public UI should not reveal whether the merchant is inactive, archived, missing a Google URL, or otherwise unavailable.

---

# 2. Validate / Load Review Session

**Endpoint**

```http
GET /api/review/sessions/:token
```

| Item | Contract |
|---|---|
| Purpose | Validate the session and load the complete public Reviewer state |
| Authentication | Session token |
| Request body | None |
| Success status | `200 OK` |
| Backend validates | Token, session status, expiration, disabled state, merchant availability |
| Merchant resolution | From `smart_review_sessions.merchant_id` |
| Backend may record | `SESSION_OPENED` |
| Response contains | Public merchant data, expiry, suggestions, Google review URL |
| Frontend action | Render Reviewer experience |
| Merchant ID required after this point | No |

## Success Response

```json
{
  "merchant": {
    "name": "Pho 37",
    "category": "Vietnamese Restaurant"
  },
  "session": {
    "expiresAt": "2026-08-08T06:59:00Z"
  },
  "suggestions": [
    {
      "id": "suggestion_uuid_1",
      "text": "The food was delicious and the service was friendly."
    },
    {
      "id": "suggestion_uuid_2",
      "text": "Really enjoyed the meal and welcoming atmosphere."
    },
    {
      "id": "suggestion_uuid_3",
      "text": "Great Vietnamese food with generous portions."
    }
  ],
  "cappedLanguages": [],
  "googleReviewUrl": "https://..."
}
```

`cappedLanguages` lists the languages whose generation allowance is already
spent. A session outlives the tab, so the frontend cannot track this itself;
without it a reload offers a Generate More that can only fail.

Both fields count *claimed* slots, and the cap is claimed before the provider
is called — so a generation in flight elsewhere already reads as spent, and a
slot refunded after a provider failure stays listed until the next load. The
pessimistic direction is deliberate: the alternative is offering a slot another
request is holding.

## Public Response Must Not Include

```text
merchant_id
google_place_id
session token
AI system prompt
AI credentials
internal merchant metadata
database-only fields
internal error details
```

`googleReviewUrl` is intentionally returned here so the frontend does not need another blocking API call when the customer chooses to continue to Google.

## Error Contract

| Status | Meaning | Frontend Behavior |
|---|---|---|
| `404` | Invalid or unknown session | Show invalid-session state |
| `410` | Expired or disabled session | Show invalid-session state |
| `429` | Rate limited | Show retryable error |
| `500` | Backend failure | Show generic error |

The frontend may use the same public message for `404` and `410`.

---

# 3. Generate More Suggestions

**Endpoint**

```http
POST /api/review/sessions/:token/suggestions
```

| Item | Contract |
|---|---|
| Purpose | Generate another batch of AI-assisted review suggestions |
| Authentication | Session token |
| Request body | Empty |
| Success status | `201 Created` |
| Backend validates | Session exists, is active, not expired, and not disabled |
| Backend loads | Merchant review context |
| Backend creates | New `smart_review_suggestions` rows |
| Backend increments | Generation number / generation count |
| Frontend action | Replace currently displayed suggestion batch |
| Rate limiting | Required |

## Request

```json
{}
```

## Success Response

```json
{
  "suggestions": [
    {
      "id": "suggestion_uuid_4",
      "text": "Really enjoyed the food and friendly service."
    },
    {
      "id": "suggestion_uuid_5",
      "text": "The atmosphere was welcoming and the meal was great."
    },
    {
      "id": "suggestion_uuid_6",
      "text": "Had a great experience and would visit again."
    }
  ],
  "capReached": false
}
```

`capReached` reports whether this language's allowance is spent *counting this
batch*. The cap is server-side state, so without it the frontend discovers the
limit only from the request that fails on it — one press after the button
should have gone.

## Error Contract

| Status | Meaning | Frontend Behavior |
|---|---|---|
| `404` | Invalid session | Show invalid-session state |
| `410` | Session expired or disabled | Show invalid-session state |
| `429` | Too many generation requests | Keep current suggestions and allow retry |
| `502` / `503` | AI provider unavailable | Keep current suggestions and allow retry |
| `500` | Unexpected backend error | Keep current suggestions and show generic error |

Existing suggestions remain usable when generation fails.

---

# 4. Select Suggestion

**Endpoint**

```http
POST /api/review/sessions/:token/select
```

| Item | Contract |
|---|---|
| Purpose | Record which generated suggestion the customer selected |
| Authentication | Session token |
| Request body | `{ "suggestionId": "uuid" }` |
| Success status | `200 OK` |
| Backend validates | Session validity |
| Backend validates | Suggestion exists |
| Backend validates | Suggestion belongs to this exact session |
| Backend updates | `selected_suggestion_id` if stored on the session |
| Backend may record | `SUGGESTION_SELECTED` |
| Clipboard action | None |
| Frontend action | Load suggestion into editable review field |

## Request

```json
{
  "suggestionId": "suggestion_uuid_1"
}
```

## Success Response

```json
{
  "selected": true
}
```

The backend does not need to return the suggestion text because the frontend already has it.

## Error Contract

| Status | Meaning | Frontend Behavior |
|---|---|---|
| `400` | Missing or invalid suggestion ID | Keep suggestions screen |
| `404` | Session or suggestion unavailable | Show generic error |
| `409` | Suggestion does not belong to session | Do not open editor |
| `410` | Session expired or disabled | Show invalid-session state |
| `500` | Backend failure | Keep suggestions screen and allow retry |

## Security Rule

The backend must enforce:

```text
suggestion.session_id === currentSession.id
```

A valid suggestion ID from a different session must never be accepted.

Selecting a suggestion does **not** copy anything to the clipboard.

---

# 5. Complete Review Session

**Endpoint**

```http
POST /api/review/sessions/:token/complete
```

| Item | Contract |
|---|---|
| Purpose | Best-effort update immediately before the customer leaves for Google |
| Authentication | Session token |
| Request body | Optional selected suggestion ID and copy outcome |
| Success status | `204 No Content` |
| Backend validates | Session token when request reaches the server |
| Backend may update | `completed_at`, session completion state |
| Backend may record | `SESSION_COMPLETED`, `REVIEW_COPIED`, or equivalent analytics |
| Google URL returned | No |
| Redirect dependency | None |
| Frontend behavior | Fire request without waiting for response, then redirect immediately |
| Failure behavior | Must not block the customer from reaching Google |

## Request — Suggestion Selected

```json
{
  "suggestionId": "suggestion_uuid_1",
  "reviewCopied": true
}
```

## Request — Suggestions Skipped

```json
{
  "reviewCopied": false
}
```

## Success Response

```http
204 No Content
```

No response body is required.

## Frontend Requirement

Use a navigation-safe request such as:

```ts
fetch(`/api/review/sessions/${token}/complete`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    suggestionId: selectedSuggestionId,
    reviewCopied: true
  }),
  keepalive: true
})
```

or `navigator.sendBeacon()` where appropriate.

The frontend must **not await this request before redirecting**.

## Error Contract

Because this is a best-effort request, backend errors do not produce a customer-facing blocking state.

If the request fails or is cancelled:

```text
Customer still proceeds to Google.
```

---

# Continue to Google Frontend Contract

The Google destination is already available from the session-validation response:

```ts
googleReviewUrl
```

When the customer clicks **Continue to Google Reviews**:

```text
Current editor text
        ↓
Attempt clipboard copy
        ↓
Fire POST /complete using keepalive/sendBeacon
        ↓
Immediately navigate to googleReviewUrl
```

Recommended implementation:

```ts
async function continueToGoogle() {
  let reviewCopied = false

  if (reviewText) {
    try {
      await navigator.clipboard.writeText(reviewText)
      reviewCopied = true
    } catch {
      showClipboardFallback()
      return
    }
  }

  fetch(`/api/review/sessions/${token}/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      suggestionId: selectedSuggestionId,
      reviewCopied
    }),
    keepalive: true
  })

  window.location.href = googleReviewUrl
}
```

If the customer skips suggestions:

```text
No review text
      ↓
No clipboard action
      ↓
Fire /complete
      ↓
Navigate to googleReviewUrl
```

---

# Final API Summary

| Method | Endpoint | Request | Response |
|---|---|---|---|
| `POST` | `/api/review/sessions` | `merchantId` | `token` |
| `GET` | `/api/review/sessions/:token` | — | Merchant + session + suggestions + `googleReviewUrl` |
| `POST` | `/api/review/sessions/:token/suggestions` | `{}` | New suggestions |
| `POST` | `/api/review/sessions/:token/select` | `suggestionId` | `{ selected: true }` |
| `POST` | `/api/review/sessions/:token/complete` | Optional `suggestionId`, `reviewCopied` | `204 No Content` |

---

# Frontend / Backend Ownership

| Responsibility | Frontend | Backend |
|---|---:|---:|
| Read merchant ID from permanent URL | | ✓ |
| Create session | | ✓ |
| Redirect scan to the session URL | | ✓ |
| Generate secure session token | | ✓ |
| Store token | | ✓ |
| Validate session | | ✓ |
| Resolve merchant from session | | ✓ |
| Return Google review URL | | ✓ |
| Display merchant | ✓ | |
| Generate AI suggestions | | ✓ |
| Display suggestions | ✓ | |
| Select suggestion UI | ✓ | |
| Validate suggestion belongs to session | | ✓ |
| Edit review text | ✓ | |
| Reset review text | ✓ | |
| Copy current review text | ✓ | |
| Fire completion update | ✓ | |
| Persist completion update if received | | ✓ |
| Redirect to already-returned Google URL | ✓ | |
| Submit Google review | | |

---

# Key Contract Rules

1. `merchantId` is used only to create a new session.
2. After creation, the session token is authoritative.
3. The backend resolves the merchant from the session.
4. The validated-session response includes `googleReviewUrl`.
5. Selecting a suggestion does not copy text.
6. Review edits and Reset behavior remain frontend-only state.
7. Clipboard copy occurs only when the customer clicks **Continue to Google Reviews**.
8. `/complete` is best-effort and must never block the Google redirect.
9. The frontend never supplies or modifies the Google destination URL.
10. Google review submission remains entirely under the customer's control.
