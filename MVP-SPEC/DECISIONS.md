# Smart Reviewer MVP — Decisions

Authoritative. Where any other document in `MVP-SPEC/` disagrees with this one,
this one is correct — the other four were written before these were settled and
contradicted each other in several places.

| # | Decision | Resolution |
|---|---|---|
| R1 | Suggestion grounding | Merchant context only. No rating or tag capture from the customer |
| R2 | Token storage | **Plaintext** `token` with `UNIQUE(token)`. No `token_hash`, no SHA-256 lookup |
| R3 | Google handoff | Fire-and-forget `POST /complete`, `keepalive`, never awaited. **No `/google-redirect` endpoint.** Five endpoints total |
| R4 | First suggestion batch | `GET /sessions/:token` **never generates**. The client calls `POST /suggestions` |
| R5 | Session creation | ~~Server-side in Next.js~~ → **revised: FastAPI serves `/m/:merchantId` and redirects.** See Architecture revision |
| R6 | Rate limiting | Atomic DB `generation_count < 5` per session; 60/hour per IP on create, counted in the database |
| R7 | Completion | A milestone, not a gate. Validation reads `expires_at` and `disabled_at` only — never `status` |
| R8 | Session TTL | 24 hours |
| R9 | Handoff UX | ~~Instruction screen with a deliberate second tap~~ → **revised: instructions on the editor, Continue redirects directly.** See R9b |
| R10 | AI provider | OpenAI SDK as transport; model via `OPENAI_MODEL`, endpoint via `OPENAI_BASE_URL` |
| R11 | Bad batches | Store every suggestion that validates (1–3). Zero valid → one retry → 502 **and refund the cap slot** |
| R12 | Topology | Monorepo, nginx reverse proxy, single origin, no CORS. **Frontend revised: Vite SPA, static build, no server** |
| R13 | Onboarding | YAML seed files, idempotent upsert on `slug`, review URL derived from `google_place_id` |
| R14 | Events | Six server-observable types only |
| R15 | Testing | pytest integration tests against real Postgres + one Playwright E2E |
| R16 | Diversity | One topic per suggestion, rotating by generation; prior batches as an avoid-list |

## Corrections to the other documents

**`data-models.md`** — `smart_review_sessions.token_hash` is now `token`, plaintext
and unique; the "Token Design" hashing diagram does not apply. Session status is
`ACTIVE | COMPLETED | DISABLED`; `EXPIRED` was removed because `expires_at` is
authoritative and no background job exists to write it. `smart_review_suggestions`
gains a `topic` column. `merchants` gains a `slug` (the seed upsert key). Events
are the six below, not eleven.

**`api-contracts.md`** — §1 "Backend stores: Hash of the token" is wrong; the token
is stored directly. §2's "must not include `token_hash`" refers to a column that no
longer exists.

**`backend-spec.md`** — §12.2 "Auto-generates suggestions if missing" is reversed by
R4. §13's "3 suggestions per batch" is now *up to* 3 (R11). §15's in-memory rate
limiting is replaced by database counting, which stays correct across workers.

**`frontend-spec.md`** — §27, §31, and §38's `POST /:token/google-redirect` endpoint
does not exist; `googleReviewUrl` arrives with the session and `/complete` is
fire-and-forget. §13 and §42's `token_hash` references are obsolete. §42's "never
use merchantId from the browser after session creation" still holds. §44's event
list is superseded. §28's "Opening Google…" screen and §29's clipboard-failure
screen are both removed by R9b/R9c — Continue redirects directly and a failed
copy is silent. §19's "replace the currently displayed suggestion batch" is
reversed by R16a; batches accumulate. §22 and §25's `[ Reset ]` button is an
icon inside the textarea in the accepted design.

## Event types

```text
SESSION_CREATED
SESSION_OPENED
SUGGESTIONS_GENERATED
SUGGESTION_SELECTED
SESSION_COMPLETED       metadata: {review_copied: bool}
GENERATION_FAILED
```

`SUGGESTION_EDITED` is deliberately absent: edits stay in the browser, and
capturing them would mean shipping the customer's text to the server, reversing
the privacy stance. `GENERATE_MORE_CLICKED` is derivable from
`generation_number > 1`. `REVIEW_COPIED` is a field on `SESSION_COMPLETED`.

## What cannot be measured

Instrumentation ends at `window.location.href = googleReviewUrl`. Whether a review
was actually posted happens on Google's property and is invisible. The pilot's
headline number — reviews produced — has to come from checking each merchant's
Google listing count before and after.

## Constants

| Setting | Value | Env var |
|---|---|---|
| Session TTL | 24 hours | `SESSION_TTL_HOURS` |
| Generations per session | 5 | `MAX_GENERATIONS_PER_SESSION` |
| Session creates per IP per hour | 60 | `CREATE_RATE_LIMIT_PER_HOUR` |
| Suggestions per batch | 3 | `SUGGESTIONS_PER_BATCH` |
| Suggestion length | 20–500 chars | `SUGGESTION_MIN_CHARS` / `_MAX_CHARS` |
| AI timeout | 20s | `AI_TIMEOUT_SECONDS` |

## Known risks, accepted

1. **R1 leaves the AI writing about an experience nobody described.** The
   authenticity notice on the suggestions screen is the only thing carrying the
   "you are the author" position. Accepted deliberately.
2. **HTTPS is functional, not hardening.** `navigator.clipboard` is undefined
   outside a secure context, so any non-localhost deployment without TLS breaks
   the core mechanic.
3. **Completion analytics undercount**, because `/complete` is best-effort by
   design. That is the price of never blocking the customer.

## Amendments after adversarial review

**R6a — a second, monotonic generation ceiling.** `generation_count` is refunded
when a generation fails, so on its own it bounds only *successful* batches:
failures were free and endlessly repeatable, which made AI spend unbounded for
anyone holding one token. `generation_attempts` is never refunded and caps
provider calls at 10 per session (`MAX_GENERATION_ATTEMPTS_PER_SESSION`).

**R6b — the refund is conditional.** An unconditional decrement refunds *the
counter*, not *this caller's claim*. If another request claimed a higher number
meanwhile, the next caller receives a `generation_number` already in use, the
unique constraint rejects the insert, and — because the failure rolls the claim
back — the collision repeats forever, 500ing that session until it expires. The
refund now applies only when the claim is still the newest.

**R7a — merchant availability is re-checked on every request.** Otherwise
deactivating a merchant leaves up to a full TTL of live sessions that keep
spending AI money and then hand the customer an empty Google URL.

**R3a — `/complete` parses its body by hand.** A declared Pydantic body is a
*required* body, so no body, an empty body, a body truncated by unload, and
`navigator.sendBeacon`'s `text/plain` content type each returned 400 — all four
normal for a request the contract calls optional and fires during navigation.

**R9a — the review survives the back button.** Keeping a completed session
usable is pointless if the edited text is gone: React state does not survive the
navigation and `cache: no-store` disables bfcache. The draft is kept in
tab-scoped `sessionStorage`, keyed by token. The token itself is never stored.

**R16a — suggestions accumulate; a batch is never replaced.** `GET
/sessions/:token` returns every suggestion in the session, ordered by
generation then position, and the client appends each new batch rather than
swapping it in. Replacing was a one-way door: a customer who liked the second
card, pressed Generate More out of curiosity, and preferred the original had no
route back to it, and on reaching the five-generation cap was left holding
whichever batch happened to be last. Since every batch is already stored (R11)
and rotates topics deliberately (R16), discarding them on screen threw away the
diversity the rotation exists to produce.

New cards land at the **bottom**, directly above the button that was just
tapped. Prepending would place them off-screen above the customer's scroll
position, which reads as nothing having happened.

This reverses `frontend-spec.md` §19's "replace the currently displayed
suggestion batch". The upper bound is 5 generations × 3 = 15 cards.

**R9b — the instructions move to the editor and the handoff screen is removed.**
R9 put "paste this into Google" on a screen *after* the tap, which is the moment
the customer has already decided to leave and is least willing to read. The same
sentences sit above the Continue button instead, where they are read before the
decision, and **Continue to Google Reviews is a direct redirect** — one tap, on
both the edited path and the skip path. The reviewer has two stages, not three.

**R9c — a failed clipboard write is silent.** R9's handoff screen existed partly
to absorb clipboard failure; with it gone there is nowhere to put a fallback, and
one was deliberately not reinvented elsewhere. `navigator.clipboard` is absent on
insecure origins and unreliable inside in-app browser WebViews, but neither is
judged frequent enough to spend a screen and an extra tap on. The customer always
reaches Google; on those origins they arrive without the text.

Two consequences, both accepted:

* `review_copied` is **optimistic**. `writeText` rejects asynchronously, so the
  flag records that the API existed and was called, not that the text landed.
  Awaiting the result to find out would reintroduce the delay before the redirect
  that this decision removes.
* HTTPS remains a functional requirement (risk 2 above), and now fails *quietly*
  rather than visibly. A non-TLS deployment degrades to a plain link to Google
  with no error anywhere the customer or the operator can see.

**Operational fix — nginx no longer logs the request line.** Session tokens
travel in the URL path, so `"$request"` wrote live capability keys into the
access log, and from there into every log shipper and backup.

**Seed-time guard on `custom_instructions`.** An instruction like "always mention
our website www.example.com" makes every generated suggestion fail URL
validation, silently and permanently breaking that merchant. Rejected at
onboarding, where someone can act on it.

---

# Architecture revision — FastAPI redirect + Vite SPA

Supersedes **R5** and the frontend half of **R12**. Everything else in this
document still stands. The backend API contract is unchanged apart from one
added route.

## R5 (revised) — FastAPI owns `/m/:merchantId`

Session creation moves out of the frontend entirely. FastAPI serves the
merchant entry route directly and answers with a redirect.

```
GET /m/{merchantId}
     ↓  FastAPI: validate merchant, create session
302 → /r/{token}          Cache-Control: no-store
```

Why this is better than the Next.js version it replaces:

* **The client IP is correct for free.** nginx talks to FastAPI directly, so
  `X-Real-IP` arrives natively. The old design had to thread the customer's IP
  through the Next server by hand, and getting that wrong silently collapsed
  every customer into one rate-limit bucket.
* **One less runtime on the critical path.** The QR scan no longer traverses a
  Node server that exists only to forward one POST.
* **The frontend needs no server at all**, which is what makes the SPA viable.

### Redirect rules — both matter

**Use `302`, never `301` or `308`.** A permanent redirect is cached by the
browser, so the *second* scan of the same QR code would skip the API entirely
and reuse a dead token. Send `Cache-Control: no-store` alongside it.

**Never render HTML from the API.** An unavailable merchant redirects to the
SPA's own route:

```
merchant unknown / inactive / archived / no google_review_url
     ↓
302 → /unavailable        Cache-Control: no-store
```

All four causes produce the identical destination — which of them applies is
the merchant's private information.

## R12 (revised) — frontend is a Vite SPA, served as static files

```
browser ──▶ nginx ──┬── /api/*  ──▶ FastAPI
                    ├── /m/*    ──▶ FastAPI   (redirect only)
                    └── /*      ──▶ static SPA build
                                    try_files $uri /index.html
```

Still one origin, still no CORS, still no backend hostname in the bundle. There
is no `INTERNAL_API_URL` any more, and no server-side rendering anywhere.

## R4 — consequence you are accepting

R4 keeps its rule (`GET /sessions/:token` never generates), but the SPA loses
the server-rendered first paint. `/r/:token` now boots as an empty shell,
fetches the session, and only then can show the merchant's name.

So the loading state that the Next version deleted **comes back and matters**:

```
/r/:token
   ↓  blank shell + JS boot     ~200-400ms
   ↓  GET /api/review/sessions/:token
   ↓  merchant name appears
   ↓  POST .../suggestions  → skeleton cards → suggestions
```

Render "Preparing your review…" during that first fetch. Do **not** leave a
white screen, and do **not** wait for suggestions before showing the merchant.
