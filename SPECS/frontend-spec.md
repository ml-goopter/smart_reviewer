# Smart Reviewer MVP — Frontend Specification

> **Superseded in places by [DECISIONS.md](DECISIONS.md)**, which is authoritative.
> Where this document and that one disagree, that one is correct.
>
> **The stack changed.** This app is a **Vite SPA**, not Next.js, and it no
> longer creates the session — FastAPI serves `/m/:merchantId` and redirects.
> See "Architecture revision" in DECISIONS.md, and §7-§8 and §41-§45 below.

## 1. Scope

The Smart Reviewer MVP contains **one public frontend application only**:

**Smart Reviewer Web App**

There is no Admin Portal, Sales Portal, merchant dashboard, or authenticated frontend in the MVP.

The frontend supports two stages:

1. **Merchant Entry**

   * Identify which merchant the customer is visiting.
   * Create a new temporary review session.

2. **Review Session**

   * Validate the temporary session.
   * Load the correct merchant.
   * Generate review-writing suggestions.
   * Let the customer select and edit a suggestion.
   * Copy the final text when the customer continues.
   * Redirect to the merchant's official Google review page.

The source requirements define the Smart Reviewer Web App as customer-facing, mobile-first, fast, simple, accessible, and secure.

---

# 2. MVP Routes

The SPA has two routes:

```text id="ej3rqq"
/r/:token        the reviewer experience
/unavailable     merchant cannot be reviewed
```

`/m/:merchantId` is **not** a frontend route. FastAPI serves it and responds
with `302 → /r/:token`, or `302 → /unavailable`. The SPA never sees it, and
never calls `POST /api/review/sessions`.

## Merchant Entry

```text id="wzjfvz"
/m/:merchantId
```

Purpose:

```text id="1p4mmf"
Permanent merchant link
        ↓
Identify merchant
        ↓
Create review session
        ↓
Redirect to /r/:token
```

This URL can be encoded into a permanent QR code.

Example:

```text id="gch5gp"
https://review.goopter.com/m/8e09301f-f928-43d5-9f60-d1287ab98f01
```

---

## Review Session

```text id="ryilhp"
/r/:token
```

Purpose:

```text id="8wtr5p"
Temporary secure session
        ↓
Validate
        ↓
Load merchant
        ↓
Reviewer experience
```

Example:

```text id="zrwexq"
https://review.goopter.com/r/Ks92MxD7yP...
```

---

# 3. Merchant ID vs Session Token

The two identifiers have different responsibilities.

```text id="lj8bws"
merchantId
    ↓
Identifies WHICH merchant
Used to CREATE a session
Not treated as authentication

session token
    ↓
Identifies THIS temporary review session
Cryptographically unpredictable
Expiring
Used for the actual review experience
```

The merchant ID may safely be visible in the permanent URL.

The backend must never treat possession of `merchantId` alone as authorization to access an existing review session.

---

# 4. Permanent Merchant QR Code

Each merchant receives a permanent URL:

```text id="8glnuf"
https://review.goopter.com/m/{merchantId}
```

That URL may be encoded in:

```text id="b16l5f"
QR code
Table display
Counter card
Sticker
Receipt
Printed material
```

The QR code should **not** contain an expiring session token.

Correct:

```text id="4yz4e7"
QR
 ↓
/m/merchant-uuid
 ↓
Create fresh session
```

Avoid:

```text id="ngcqo6"
QR
 ↓
/r/temporary-session-token
 ↓
Eventually expires
```

---

# 5. Complete Customer Flow

```text id="50ccg3"
Customer scans merchant QR
        ↓
/m/:merchantId
        ↓
Validate merchant
        ↓
Create temporary review session
        ↓
Receive secure token
        ↓
Navigate to /r/:token
        ↓
Validate session
        ↓
Load merchant
        ↓
Show review suggestions
        ↓
Customer selects suggestion
        ↓
Open review editor
        ↓
Customer edits if desired
        │
        ├── Reset to original suggestion
        │
        ↓
Continue to Google
        ↓
Copy CURRENT editor text
        ↓
Record redirect
        ↓
Open Google review page
        ↓
Customer independently submits review
```

The source requirements similarly define the intended flow as session validation, merchant-context loading, suggestions, customer selection, and continuation to Google's official review page.

---

# 6. Application States

Recommended frontend states:

```ts id="99biz3"
type ReviewerState =
  | 'creating-session'
  | 'loading'
  | 'suggestions'
  | 'generating'
  | 'selected'
  | 'redirecting'
  | 'clipboard-error'
  | 'invalid'
  | 'error'
```

---

# 7-8. Merchant Entry (moved to the backend)

`/m/:merchantId` is handled by FastAPI. There is no frontend page, no spinner,
and no `POST /api/review/sessions` call anywhere in the SPA.

```text
customer scans QR
        ↓
GET /m/:merchantId                    (nginx → FastAPI)
        ↓
validate merchant, create session
        ↓
302 → /r/:token       Cache-Control: no-store
```

This removes the whole class of problems the old client-side version had:
double session creation under React Strict Mode, a spinner flash on every scan,
and a flow that broke without JavaScript. It also means the customer's IP
reaches the rate limiter natively instead of being forwarded by hand.

An unavailable merchant redirects to `/unavailable` — see §9.

# 9. Invalid Merchant

FastAPI redirects to `/unavailable` when:

```text id="wfl6un"
merchantId does not exist
merchant is inactive
merchant is archived
merchant cannot receive reviews
```

All four produce the same destination. The SPA renders this route as a static
page with no API call — it has no token and nothing to load:

```text id="8ku4k5"
This review link is no longer available.

Please ask the business for assistance.
```

Do not expose:

```text id="hhztjv"
Merchant database status
Database errors
Internal validation details
Stack traces
```

---

# 10. Session Creation Abuse Protection

No longer a frontend concern: the SPA never creates sessions. One scan is one
`GET /m/:merchantId`, and the backend rate-limits creation per IP.

The frontend *does* still have to prevent duplicate **generation** requests —
see §19. Each one costs money and consumes a cap slot.

---

# 11. Review Session Route

Route:

```text id="d2i4f0"
/r/:token
```

When loaded:

```http id="lmo1e5"
GET /api/review/sessions/:token
```

---

# 12. Session Token Authority

Once the session exists, the session token becomes authoritative.

Do not send the merchant ID around with every Reviewer API request.

Use:

```text id="9bhs9c"
/r/:token
      ↓
session
      ↓
merchant_id
      ↓
merchant
```

Not:

```text id="yk5dks"
token + merchantId
      ↓
frontend decides merchant
```

This prevents a customer from changing the merchant identifier after the session has been created.

---

# 13. Public Session Response

Example:

```json id="2ath3i"
{
  "merchant": {
    "name": "Pho 37",
    "category": "Vietnamese Restaurant"
  },
  "session": {
    "expiresAt": "2026-08-07T23:59:00Z"
  },
  "suggestions": [
    {
      "id": "a1",
      "text": "The food was delicious and the service was friendly."
    },
    {
      "id": "a2",
      "text": "Really enjoyed the meal and welcoming atmosphere."
    },
    {
      "id": "a3",
      "text": "Great Vietnamese food with generous portions."
    }
  ]
}
```

Do not expose:

```text id="lbov54"
merchant_id
google_place_id
session token
merchant internal metadata
AI system prompts
AI credentials
database fields
```

---

# 14. Loading State

There is no server rendering, so `/r/:token` boots as an empty shell and must
show this while the first fetch is in flight. A white screen here is the most
likely thing to make someone abandon, because it is the first thing they see
after scanning. Show the merchant's name as soon as the session resolves — do
**not** wait for suggestions.

While `/r/:token` is being validated:

```text id="ka5ne3"
┌───────────────────────────────┐
│                               │
│            Goopter            │
│                               │
│   Preparing your review...    │
│                               │
│              ◌                │
│                               │
└───────────────────────────────┘
```

Backend validation remains authoritative.

---

# 15. Suggestions Screen

Example mobile UI:

```text id="w7ejec"
┌────────────────────────────────┐
│                                │
│             Pho 37             │
│      Vietnamese Restaurant     │
│                                │
│     How was your experience?   │
│                                │
│ Here are a few ideas to help   │
│ you write your review.         │
│                                │
├────────────────────────────────┤
│                                │
│ The food was delicious and the │
│ service was friendly and fast. │
│                                │
│      [ Use This Review ]       │
│                                │
├────────────────────────────────┤
│                                │
│ Great Vietnamese food with     │
│ generous portions and a        │
│ welcoming atmosphere.          │
│                                │
│      [ Use This Review ]       │
│                                │
├────────────────────────────────┤
│                                │
│ Really enjoyed the meal and    │
│ would happily come back.       │
│                                │
│      [ Use This Review ]       │
│                                │
├────────────────────────────────┤
│                                │
│ [ Generate More Suggestions ]  │
│                                │
│ Prefer to write your own?      │
│                                │
│      [ Write Your Own ]        │
│                                │
└────────────────────────────────┘
```

The source requirements call for several suggestions, **Use This Review**, and **Generate More Suggestions** controls.

---

# 16. Authenticity Message

Display a short notice:

```text id="ja6x88"
Only use wording that reflects your genuine experience.
You can edit any suggestion before posting.
```

The customer must remain fully in control of what they ultimately submit.

---

# 17. Suggestion Component

```tsx id="wgmgvj"
<ReviewSuggestionCard />
```

Props:

```ts id="ddlb5c"
type ReviewSuggestionCardProps = {
  suggestion: {
    id: string
    text: string
  }

  onSelect: (id: string) => void
}
```

Display:

```text id="n4hwzk"
┌───────────────────────────────┐
│                               │
│ Suggestion text               │
│                               │
│ [ Use This Review ]           │
│                               │
└───────────────────────────────┘
```

AI-generated content must render as plain text.

---

# 18. Generate More Suggestions

Button:

```text id="0tuwke"
Generate More Suggestions
```

API:

```http id="fvxm8k"
POST /api/review/sessions/:token/suggestions
```

No request body is required:

```json id="4fqen5"
{}
```

Response:

```json id="gttkuy"
{
  "suggestions": [
    {
      "id": "b1",
      "text": "..."
    },
    {
      "id": "b2",
      "text": "..."
    },
    {
      "id": "b3",
      "text": "..."
    }
  ]
}
```

---

# 19. Generating State

While generating:

```text id="sf4ptq"
[ Generating... ]
```

Rules:

```text id="au7c23"
Keep existing suggestions visible
Disable repeated clicks
Allow only one generation request at a time
Show lightweight progress feedback
```

When successful, replace the currently displayed suggestion batch.

Previous generations remain stored in the backend.

---

# 20. Suggestion Generation Failure

Display:

```text id="8p1v78"
We couldn't generate new suggestions right now.

[ Try Again ]

You can still write your own review.

Continue to Google →
```

AI availability must never prevent the customer from reaching Google.

---

# 21. Select Suggestion

When the customer chooses:

```text id="g9y6fq"
Use This Review
```

call:

```http id="odkkfp"
POST /api/review/sessions/:token/select
```

Request:

```json id="rus7yo"
{
  "suggestionId": "a1"
}
```

Backend validates:

```text id="ck52mh"
Session remains valid
Suggestion exists
Suggestion belongs to session
```

After success:

```text id="unm957"
Set selected suggestion
        ↓
Load suggestion into editor
        ↓
Open selected state
```

**Do not copy anything to the clipboard at this point.**

---

# 22. Selected Review Screen

```text id="aw5o1v"
┌────────────────────────────────┐
│                                │
│        Make it your own        │
│                                │
│ You can edit this suggestion   │
│ before continuing to Google.   │
│                                │
│ ┌────────────────────────────┐ │
│ │ The food was delicious and│ │
│ │ the service was friendly. │ │
│ └────────────────────────────┘ │
│                                │
│ [ Reset ]                      │
│                                │
│ [ Continue to Google Reviews ] │
│                                │
└────────────────────────────────┘
```

There is no:

```text id="4j4oya"
Copy
Copy Again
```

button.

---

# 23. Review Editor

Component:

```tsx id="nsw07d"
<SelectedReviewEditor />
```

Props:

```ts id="mve6q9"
type SelectedReviewEditorProps = {
  originalText: string
  value: string
  onChange: (value: string) => void
  onReset: () => void
}
```

Local state:

```ts id="6lprsd"
const [originalText, setOriginalText] = useState('')
const [reviewText, setReviewText] = useState('')
```

When selected:

```ts id="vu6f5q"
setOriginalText(suggestion.text)
setReviewText(suggestion.text)
```

---

# 24. Editing

The customer can freely modify the suggestion.

Example:

```text id="cb7hi8"
Original:

The food was delicious and the service was friendly.

Edited:

The beef pho was delicious and our server was
really friendly.
```

For MVP, edited review text remains local browser state.

It does not need to be stored in the database.

---

# 25. Reset

The editor contains:

```text id="sr85sw"
Reset
```

Reset restores the currently selected suggestion:

```ts id="dbnb4t"
setReviewText(originalText)
```

Behavior:

```text id="7zo6oz"
Does NOT generate AI text
Does NOT select another suggestion
Does NOT call backend
Does NOT leave the editor
```

If:

```text id="n2ol6w"
reviewText === originalText
```

the Reset button may be disabled.

---

# 26. Continue to Google

Primary action:

```text id="ci988p"
Continue to Google Reviews
```

This performs:

```text id="8pj68k"
Copy current reviewText
        ↓
Record redirect
        ↓
Get Google review URL
        ↓
Navigate to Google
```

The copied value must always be the **current editor value**.

Not necessarily the original AI suggestion.

---

# 27. Clipboard Behavior

On click:

```ts id="64ndpg"
await navigator.clipboard.writeText(reviewText)
```

Then call:

```http id="w7g2st"
POST /api/review/sessions/:token/complete
```

Response:

```json id="kjgm9h"
{
  "url": "https://..."
}
```

Then:

```ts id="bsdhq5"
window.location.href = response.url
```

---

# 28. Redirect Sequence

Recommended implementation:

```text id="35mx7s"
Customer clicks Continue
        ↓
Disable button
        ↓
Attempt clipboard copy
        ↓
If successful:
   record redirect
        ↓
navigate to Google
```

Temporary UI:

```text id="ro9b1h"
✓ Review copied

Opening Google...
```

---

# 29. Clipboard Failure

If clipboard access fails, do not immediately redirect.

Display:

```text id="d5exmo"
We couldn't copy your review automatically.

Select and copy the text below, then continue.

┌───────────────────────────────┐
│ Current review text           │
└───────────────────────────────┘

[ Continue to Google ]
```

The customer can manually copy the text.

The second Continue action redirects without requiring clipboard success.

---

# 30. Skip Suggestions

Customers may completely ignore the AI suggestions.

From the suggestions page:

```text id="gcs750"
Prefer to write your own review?

[ Write Your Own ]
```

Flow:

```text id="naz067"
No selected suggestion
        ↓
No clipboard operation
        ↓
Record GOOGLE_REVIEW_CLICKED
        ↓
Open Google review page
```

---

# 31. Google Redirect API

```http id="dzkeol"
POST /api/review/sessions/:token/complete
```

Optional request:

```json id="m68dkj"
{
  "suggestionId": "a1"
}
```

If the customer skipped suggestions:

```json id="0dc0um"
{}
```

The backend:

```text id="z8vnwe"
Validates session
      ↓
Loads merchant from session
      ↓
Records redirect event
      ↓
Returns merchant.google_review_url
```

The frontend must not submit a Google URL supplied by the browser.

---

# 32. Google Boundary

Smart Reviewer ends when the customer reaches Google's review interface.

The application must not:

```text id="4g30yl"
Choose a star rating
Submit the review
Interact with customer's Google account
Impersonate the reviewer
Automatically submit anything to Google
Use unauthorized techniques to populate Google fields
```

These restrictions are explicitly required by the source specification.

---

# 33. Invalid / Expired Session

For:

```text id="cbbm7k"
Unknown token
Expired session
Disabled session
Unavailable merchant
Invalid session
```

show:

```text id="t3vauc"
┌───────────────────────────────┐
│                               │
│   This review session is      │
│   no longer available.        │
│                               │
│   Please scan the business's  │
│   review QR code again.       │
│                               │
└───────────────────────────────┘
```

This is preferable to saying "ask for a new session" because scanning the permanent `/m/:merchantId` QR creates one automatically.

Do not expose why validation failed.

---

# 34. General Error State

For temporary application/network errors:

```text id="b4uu48"
Something went wrong.

Please try again.

[ Try Again ]
```

Do not expose:

```text id="oqv50g"
HTTP error codes
Backend exceptions
Database errors
Stack traces
Internal IDs
```

---

# 35. Mobile Requirements

Primary target widths:

```text id="ypn6qm"
375px
390px
430px
```

Requirements:

```text id="x35tc9"
Single-column layout
16px+ body text
Large touch targets
Full-width primary actions
No horizontal scrolling
No hover-dependent interactions
No navigation menu
No customer account UI
No unnecessary modals
```

---

# 36. Desktop Behavior

Desktop uses the same interface centered on screen.

```text id="6x6g26"
┌─────────────────────────────────────────────┐
│                                             │
│           ┌─────────────────────┐           │
│           │                     │           │
│           │   Reviewer App      │           │
│           │                     │           │
│           │   max-width 480px   │           │
│           │                     │           │
│           └─────────────────────┘           │
│                                             │
└─────────────────────────────────────────────┘
```

Recommended:

```css id="vkbjts"
max-width: 480px;
margin: 0 auto;
```

---

# 37. Components

Recommended MVP components:

```text id="brp722"
ReviewerPage

MerchantEntryLoader

ReviewerHeader
MerchantIdentity

ReviewSuggestionList
ReviewSuggestionCard
GenerateMoreButton

SelectedReviewEditor
ResetButton
GoogleReviewButton

LoadingState
InvalidState
ErrorState

Button
Textarea
Spinner
Toast
```

No large design system is required.

---

# 38. Frontend API Surface

The SPA calls four endpoints. `POST /api/review/sessions` is **not** among
them — FastAPI calls it internally when serving `/m/:merchantId`.

## Load Session

```http id="irk023"
GET /api/review/sessions/:token
```

---

## Generate Suggestions

```http id="9rjvso"
POST /api/review/sessions/:token/suggestions
```

---

## Select Suggestion

```http id="q2o46h"
POST /api/review/sessions/:token/select
```

```json id="bhfe6l"
{
  "suggestionId": "suggestion_uuid"
}
```

---

## Continue to Google

```http id="0drybb"
POST /api/review/sessions/:token/complete
```

Fired with `keepalive` and **never awaited**. The redirect to Google must not
wait on it. `googleReviewUrl` already arrived with the session.

---

# 39. Frontend State Management

Do not use Redux.

Recommended:

```text id="mbw91c"
TanStack Query
    → backend/server state

React useState
    → current review editor
    → selected suggestion
    → UI state
```

Example:

```ts id="uxk0o8"
const [selectedSuggestionId, setSelectedSuggestionId] =
  useState<string | null>(null)

const [originalText, setOriginalText] =
  useState('')

const [reviewText, setReviewText] =
  useState('')
```

---

# 40. Public Types

```ts id="zu1ge8"
type ReviewSuggestion = {
  id: string
  text: string
}

type PublicMerchant = {
  name: string
  category?: string
}

type PublicReviewSession = {
  merchant: PublicMerchant
  expiresAt: string
  suggestions: ReviewSuggestion[]
}

type CreateSessionResponse = {
  token: string
}
```

---

# 41. Recommended Frontend Stack

```text id="v909yu"
Vite
React + TypeScript
Tailwind CSS
a tiny router (or none — see below)
```

The app is roughly 900 lines across two routes with no shared server state, so
it needs very little. TanStack Query and Zod were in the original recommendation
and are **not** used: there is nothing to cache, invalidate, or refetch, and the
API response shapes are covered by TypeScript types plus a defensive check on
the one field that matters.

Routing is two static paths and one param. `react-router` is fine; so is
reading `location.pathname` directly. Do not add a framework for this.

No need for:

```text id="9cc31d"
Redux
Server-side rendering
Admin framework
Authentication frontend
Complex form framework
Client-side database
Offline synchronization
```

Build output is static files. nginx serves them with an SPA fallback:

```nginx
location /api/ { proxy_pass http://api; }
location /m/   { proxy_pass http://api; }   # redirect only
location /     { try_files $uri /index.html; }
```

---

# 42. Security Rules

## Merchant Entry

`merchantId` is public but must only be used to request creation of a session.

```text id="zc3p6c"
merchantId
    ≠ authentication
```

## Review Session

The secure token becomes authoritative.

```text id="byzin9"
token
  ↓
session
  ↓
merchant
```

Additional rules:

```text id="83laq8"
Never expose the session token beyond the URL it arrives in

Never use merchantId from the browser
after session creation

Never allow browser to choose Google destination

Never store session token in localStorage

Render AI output as plain text

Rate-limit session creation

Rate-limit AI generation

Prevent duplicate submissions
```

The source requirements also specifically call for secure session tokens, expiration, server-side validation, rate limiting, API authorization, input validation, bot protection, and no exposure of sensitive merchant information.

---

# 43. Privacy

Do not collect customer:

```text id="9q8nw8"
Name
Email
Phone
Google account
GPS location
Advertising identifiers
Device fingerprint
```

Potential MVP operational data:

```text id="72x4oj"
Session events
Timestamp
User agent where useful
Privacy-preserving browser/session identifier
```

Avoid invasive fingerprinting and unnecessary personal information, consistent with the source requirements.

---

# 44. Core Events

Recommended event types:

```text id="sdij9f"
SESSION_CREATED
SESSION_OPENED
SUGGESTIONS_GENERATED
SUGGESTION_SELECTED
SESSION_COMPLETED       metadata: {review_copied: bool}
GENERATION_FAILED
```

`REVIEW_COPIED` occurs only when the customer clicks **Continue to Google** and clipboard copying succeeds.

It does **not** occur when the suggestion is selected.

---

# 45. Suggested Project Structure

```text id="2j71m5"
index.html
vite.config.ts
src/
├── main.tsx              mount + route dispatch
├── App.tsx               /r/:token | /unavailable | fallback
├── components/
│   ├── Reviewer.tsx      stage machine: suggestions → selected → handoff
│   ├── SuggestionList.tsx
│   ├── SelectedReviewEditor.tsx
│   ├── GoogleHandoff.tsx
│   ├── UnavailableLink.tsx
│   └── states.tsx        LoadingState, InvalidSessionState, ErrorState
├── lib/
│   ├── api.ts            four fetch wrappers
│   ├── draft.ts          sessionStorage persistence
│   └── types.ts
└── index.css             tailwind
```

`MerchantEntryLoader` is gone — that page is the backend's now. `LoadingState`
is back and is load-bearing (§14).

---

# 46. MVP Acceptance Criteria

## Merchant QR

Given an active merchant:

```text id="zgnsd0"
A permanent /m/:merchantId URL exists.

The URL may be reused indefinitely.

Scanning it attempts to create a new review session.
```

---

## Session Creation

When `/m/:merchantId` loads:

```text id="a6w3pu"
Merchant is validated server-side.

A secure temporary session is created.

A cryptographically unpredictable token is returned.

Customer is redirected to /r/:token.
```

---

## Reviewer Session

Given a valid token:

```text id="4vx78g"
Correct merchant loads.

Multiple suggestions appear.

Customer can generate additional suggestions.

Customer can select a suggestion.
```

---

## Review Editor

After selecting:

```text id="i1k1uc"
Suggestion loads into editable textarea.

Nothing is copied automatically.

Customer can edit text.

Customer can press Reset.

Reset restores original selected suggestion.
```

---

## Continue to Google

When the customer presses:

```text id="o0zf4v"
Continue to Google Reviews
```

the application:

```text id="m7m7fy"
Copies current editor text
        ↓
Records redirect
        ↓
Opens correct Google review page
```

---

## Skip AI

Customer can:

```text id="1ziv8y"
Ignore suggestions
        ↓
Continue directly to Google
```

without any clipboard action.

---

## Invalid Session

Invalid, expired, or disabled sessions:

```text id="1lxm8f"
Do not expose merchant information.

Do not generate suggestions.

Do not redirect to Google.

Show generic unavailable state.
```

---

# 47. MVP Build Order

```text id="gfhttc"
1. /m/:merchantId route

2. Session creation API integration

3. Redirect to /r/:token

4. Session validation

5. Merchant identity

6. Suggestion cards

7. Initial suggestion generation

8. Generate More

9. Suggestion selection

10. Review editor

11. Reset behavior

12. Copy-on-Continue behavior

13. Google redirect

14. Skip-suggestions flow

15. Clipboard failure handling

16. Invalid/expired handling

17. Mobile responsiveness

18. Accessibility

19. Rate-limit/error testing

20. End-to-end QR → Google test
```

---

# 48. Final MVP Architecture

```text id="qjsmby"
PERMANENT MERCHANT ENTRY

QR Code
   ↓
/m/:merchantId
   ↓
Create Session
   ↓
Secure Token


TEMPORARY REVIEW EXPERIENCE

/r/:token
   ↓
Validate Session
   ↓
Load Merchant
   ↓
Generate Suggestions
   ↓
Select
   ↓
Edit / Reset
   ↓
Continue
   ↓
Copy Current Text
   ↓
Google Reviews
```

The important architectural distinction is:

```text id="mvnmqz"
merchantId
= permanent public merchant identifier
= used to CREATE a session

token
= temporary secure session identifier
= used to RUN the review experience
```

This keeps the permanent QR simple while ensuring the actual Reviewer session remains temporary, validated, and tied server-side to exactly one merchant.


---

# 49. Build brief — constraints that are easy to get wrong

Everything here was learned by getting it wrong first. None of it is stylistic.

## The clipboard is the product

```ts
async function continueToGoogle(text: string) {
  if (!text.trim())        { setCopyState('skipped'); return }
  if (!navigator.clipboard){ setCopyState('manual');  return }

  try   { await navigator.clipboard.writeText(text); setCopyState('copied') }
  catch { setCopyState('manual') }
}
```

1. **Call it inside the click handler.** Not in a `useEffect`, not after a state
   round-trip. Safari only honours a clipboard write while the user gesture is
   still active, and an effect runs after the render that follows the click — it
   fails silently on exactly the devices this product targets.
2. **It must be the first `await`.** Anything awaited before it — a `fetch`, in
   particular — ends the gesture.
3. **`navigator.clipboard` is `undefined` outside a secure context.** Guard for
   it; that path is the manual-copy fallback, not a crash.
4. **HTTPS is a functional requirement.** No TLS, no clipboard, no product.

## Never let an optional failure destroy finished work

`Generate More` is optional; by the time it is pressed the customer may have an
edited review on screen and already holds `googleReviewUrl`. A failure — even
`404`/`410` — must show a message and leave everything else intact. Do not swap
the tree for an error screen.

`POST /select` failing must be **silent**. The editor already has the text; it
only records which card was chosen.

## One generation in flight, ever

Guard with a ref, set synchronously before the first `await`. Strict Mode
double-invokes effects, and customers double-tap. Each call costs money and one
of five cap slots.

## The draft must survive the back button

React state does not survive the trip to Google and back. Persist
`{selectedId, originalText, reviewText}` to **`sessionStorage`**, keyed by
token, and restore it on mount. Tab-scoped so a shared phone does not leak it.
**Never store the session token** — it lives in the URL and nowhere else.

## Fire-and-forget completion

```ts
fetch(`/api/review/sessions/${token}/complete`, {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({ suggestionId, reviewCopied }), keepalive: true,
})           // NOT awaited
window.location.href = googleReviewUrl
```

Guard the final button against a double tap, or the completion metric
double-counts.

## Rendering

* AI output is **plain text**. No `dangerouslySetInnerHTML`.
* `break-words` on suggestion text and merchant name — both are unbounded and
  will produce horizontal scroll at 375px without it.
* Textarea at 16px minimum, or iOS zooms on focus.
* A batch is **1-3 suggestions**, not always 3.
* Move focus to the new heading on each stage change, and keep one always-
  mounted `aria-live` region for async status.
* Never render a countdown from `expiresAt`.

## Error copy

| Situation | Show |
|---|---|
| `/unavailable` | "This review link is no longer available." |
| session `404`/`410` | "This review session is no longer available." + rescan the QR |
| generation `502` | "We couldn't generate new suggestions right now." + Try Again + Continue to Google |
| generation `429` | limit reached; hide Generate More, keep Google reachable |

The limit is not discovered from the `429`. `GET /sessions/:token` reports
`cappedLanguages` and a successful generation reports `capReached`, so the
notice appears and Generate More goes on the batch that spends the last slot —
not on the press after it, which is the press that would 429. The `429` above
remains the fallback for what those two cannot see: the session-wide attempt
ceiling, and an allowance spent in another tab.

A spent allowance outranks a failure in the notice: it is the only one of the
two that is terminal, and the notice offers Try Again for every other kind. The
live region says the same words the notice shows — a cap must never be
announced as something to retry.

Never expose a status code, a backend message, or which of several causes
applied.
