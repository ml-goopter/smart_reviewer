# Smart Reviewer MVP — Decisions

Authoritative. Where any other document in `SPECS/` disagrees with this one,
this one is correct — the other four were written before these were settled and
contradicted each other in several places.

| # | Decision | Resolution |
|---|---|---|
| R1 | Suggestion grounding | Merchant context only. No rating or tag capture from the customer |
| R2 | Token storage | **Plaintext** `token` with `UNIQUE(token)`. No `token_hash`, no SHA-256 lookup |
| R3 | Google handoff | Fire-and-forget `POST /complete`, `keepalive`, never awaited. **No `/google-redirect` endpoint.** Five endpoints total |
| R4 | First suggestion batch | `GET /sessions/:token` **never generates**. The client calls `POST /suggestions` |
| R5 | Session creation | ~~Server-side in Next.js~~ → **revised: FastAPI serves `/m/:merchantId` and redirects.** See Architecture revision |
| R6 | Rate limiting | Atomic DB check on `generation_count` per session; a per-IP hourly cap on create, both counted in the database. Limits live in `config.py` |
| R7 | Completion | A milestone, not a gate. Validation reads `expires_at` only — never `status`. See R7b |
| R8 | Session TTL | 24 hours |
| R9 | Handoff UX | ~~Instruction screen with a deliberate second tap~~ → **revised: instructions on the editor, Continue redirects directly.** See R9b |
| R10 | AI provider | OpenAI SDK as transport; model via `OPENAI_MODEL`, endpoint via `OPENAI_BASE_URL` |
| R11 | Bad batches | Store every suggestion that validates (1–3). Zero valid → one retry → 502 **and refund the cap slot** |
| R12 | Topology | Monorepo, nginx reverse proxy, single origin, no CORS. **Frontend revised: Vite SPA, static build, no server** |
| R13 | Onboarding | ~~YAML seed files, idempotent upsert on `slug`~~ → **revised: seeding is removed.** The lead crawler is the only merchant write path. See R20 |
| R14 | Events | Six server-observable types only |
| R15 | Testing | Two pytest layers — mocked unit tests, plus integration tests against real Postgres for what only Postgres verifies — and one Playwright E2E. See R15a |
| R16 | Diversity | One topic per suggestion, rotating by generation; prior batches as an avoid-list |
| R17 | Merchant availability | A `subscriptions` row is the only **availability** gate; `google_review_url` still gates separately. `merchants.status` is dropped, along with both checks that read it |
| R18 | Subscription term | `expires_at` is persisted, never recalculated. Exclusive next-midnight in a fixed operator timezone; renewal extends from the later of the current expiry and today |
| R19 | Subscription lifecycle | One row per merchant, mutated in place. `ACTIVE \| CANCELLED \| PAUSED`. No history table, no paused-time credit |
| R20 | Merchant write path | The lead crawler owns merchant *and* subscription creation. `seed.py` and `merchants/*.yaml` are deleted |

## Corrections to the other documents

**`data-models.md`** — `smart_review_sessions.token_hash` is now `token`, plaintext
and unique; the "Token Design" hashing diagram does not apply. Session status is
`ACTIVE | COMPLETED`; `EXPIRED` was removed because `expires_at` is
authoritative and no background job exists to write it, and `DISABLED` with
`disabled_at` by R7b. `smart_review_suggestions`
gains a `topic` column. `merchants` gains a `slug`. Events are the six below, not
eleven. `merchants.status` is **dropped** and a `subscriptions` table replaces it
as the availability gate (R17).

**`api-contracts.md`** — §1 "Backend stores: Hash of the token" is wrong; the token
is stored directly. §2's "must not include `token_hash`" refers to a column that no
longer exists.

**`backend-spec.md`** — §12.2 "Auto-generates suggestions if missing" is reversed by
R4. §13's "3 suggestions per batch" is now *up to* 3 (R11). §15's in-memory rate
limiting is replaced by database counting, which stays correct across workers.
§6's `status = ACTIVE` rule and §10's "merchant valid" per-request check are
both replaced by the subscription gate (R17); §8's session `EXPIRED` status was
already removed by R7.

**`lead-crawler-spec.md`** — L1's "ACTIVE row" and §2.1.4's `status` column no
longer exist; a saved merchant is unusable until it is subscribed (R20). L19's
"YAML seeding is demo-only" is now "there is no YAML seeding".

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

Values live in `apps/api/app/config.py` and nowhere else — this table used to
restate them and drifted, which is the failure the settings module now has a
test against. What is decided here is that each of these is a knob at all, and
why; what it is set to is an operational choice, changed without amending a
decision.

| Setting | Env var | Why it exists |
|---|---|---|
| Session TTL | `SESSION_TTL_HOURS` | Covers scanning at the table and writing that evening |
| Generations per session | `MAX_GENERATIONS_PER_SESSION` | Cost control; refundable, so it bounds successful batches only |
| Generation attempts per session | `MAX_GENERATION_ATTEMPTS_PER_SESSION` | R6a's monotonic ceiling; must exceed the cap above |
| Session creates per IP per hour | `CREATE_RATE_LIMIT_PER_HOUR` | Runaway-script guard, loose because of carrier-grade NAT |
| Suggestions per batch | `SUGGESTIONS_PER_BATCH` | Up to this many; fewer may survive validation (R11) |
| Suggestion length | `SUGGESTION_MIN_CHARS` / `_MAX_CHARS` | Too short is not a review, too long is unusable on a phone |
| AI timeout | `AI_TIMEOUT_SECONDS` | Must stay below nginx's `proxy_read_timeout` |
| Operator timezone | `OPERATOR_TIMEZONE` | The day boundary subscriptions expire on (R18). One operator, one calendar |

`.env.example` is generated from the same module. Only `DATABASE_URL` and
`TRUST_PROXY_HEADERS` are set in `docker-compose.yml`, because those genuinely
differ by environment rather than by decision.

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

**R7a — merchant availability is re-checked on every request.** *(Narrowed by
R17 to `google_review_url` only — see the note below.)* Otherwise
deactivating a merchant leaves up to a full TTL of live sessions that keep
spending AI money and then hand the customer an empty Google URL.

*Narrowed by R17.* What remains re-checked per request is `google_review_url`:
without one the customer reaches a dead end, so it must be caught however late.
The subscription is checked at session creation **only** — see R17's
"Checked once" below for why the argument above does not carry over to it.

**R7b — sessions are not disabled; `expires_at` is the only check.**
`disabled_at` and the `DISABLED` status were a manual kill switch for a single
session, and nothing ever pulled it — no endpoint, no service, no admin path
wrote either field. The only writer in the tree was the test asserting the check
worked.

It has no use case at a 24-hour TTL (R8). By the time anyone noticed a session
worth killing, it has expired on its own; and the thing an operator actually
wants to switch off is a *merchant*, which is the subscription's job (R19), not
a session's. A gate with no lever is worse than no gate: it reads as a
capability the product has, so the next person to want one assumes it works.

Session validation is therefore `expires_at` alone, plus the merchant still
having a `google_review_url` (R7a). Session status is `ACTIVE | COMPLETED`, and
is still never consulted.

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

**R15a — the suite is two layers, and the default is mocked.** R15 read as
"integration tests against real Postgres", which made a database the price of
running any test at all. Most of them did not need one: a route test asserting a
status code and a header used Postgres only as somewhere to put a row, so a
stopped container or another test's leftover data failed it for reasons that had
nothing to do with the code.

`tests/unit/` substitutes everything outward — `dependency_overrides` for the
request-scoped `Session`, `monkeypatch.setattr` for the service a router calls —
and runs with no containers. `tests/integration/` keeps a real Postgres and is
deliberately small, holding only properties the database itself provides: the
unique index on `token`, the CHECK constraints, the atomic conditional `UPDATE`
behind the generation cap, and R6b's refund race. Mocking those would assert
that a stub does what it was told. (The seed's idempotent upsert on `slug` was
one of these until R20 deleted the seed.)

The test to apply when adding one: if a failure would mean "the code is wrong",
it is a unit test; if it would mean "the schema or the transaction is wrong", it
is an integration test.

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
onboarding, where someone can act on it. *(R20 deletes the seed; the guard moves
to the context editor, which is now the only path that writes the field —
`lead-crawler-spec.md` §2.1.8.)*

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
merchant unknown / not subscribed / expired / suspended / no google_review_url
     ↓
302 → /unavailable        Cache-Control: no-store
```

Every cause produces the identical destination — which of them applies is the
merchant's private information.

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

---

# Merchant subscriptions

Supersedes **R13** and narrows **R7a**. A merchant's review link now lives only
as long as the merchant is paid up.

## R17 — the subscription is the only gate

A merchant may create a session when **all** of these hold:

```text
a subscriptions row exists for the merchant
subscription.status == 'ACTIVE'
now < subscription.expires_at
merchant.google_review_url is present
```

No subscription row at all is the same as an expired one: **INACTIVE**. There is
no grandfather clause and no fail-open path — a gate that passes when its data is
missing is not a gate.

**`merchants.status` is dropped**, along with the checks that read it in
`create_session` and `load_valid_session`. Two independent notions of "switched
off" is one too many. The first draft of this change went the other way and
added `EXPIRED`, `CANCELLED` and `PAUSED` to the merchant status enum — billing
states on a column that gates for operational reasons, kept in step with the
subscription by nothing. The suspension states go on the subscription instead
(R19), and the column goes.

`google_review_url` is a separate check and survives: "the only gate" here means
the only *availability* gate, the only thing answering "is this merchant
switched on". A merchant with no Google URL is misconfigured, not switched off,
and that check still runs on every request (R7a).

Consequences accepted:

* `merchants.archived_at` loses the status value it paired with. Nothing reads
  it; suspending a merchant is now `status = 'CANCELLED'` on the subscription.
* Any row currently `INACTIVE` or `ARCHIVED` comes back to life once the
  backfill grants it a subscription. Check for non-`ACTIVE` rows before running
  the migration — the column is gone afterwards and the distinction is not
  recoverable.

**Checked once, at session creation.** R7a's argument — that an off merchant
would otherwise keep spending AI money for a full TTL — was written about a
human deliberately flipping a switch, where cutting live sessions off is the
intent. Expiry is a clock running out at midnight, and enforcing it per request
would delete the review a customer was typing at 23:59:58 with no warning and no
way to recover it. The exposure is bounded by `SESSION_TTL_HOURS` and is
self-limiting; the lost review is not.

**The customer is told nothing.** An expired merchant produces the existing
`409 merchant_unavailable` → `302 /unavailable`, identical to unknown and
missing-a-Google-URL. Whether a business is behind on payment is that business's
private information, and the customer can act on none of it. No new error code
and no new copy.

## R18 — how `expires_at` is computed

`expires_at` is calculated once, at create or renew, and **persisted**. It is
never recomputed at read time; the stored value is the source of truth.

The boundary is **exclusive next-midnight in `OPERATOR_TIMEZONE`**, stored as
UTC. The value lives in `config.py` like every other setting; that it is a
single configured zone rather than a per-merchant column is what is decided
here:

```text
create   expires_at = local_midnight(tomorrow) + duration
renew    expires_at = max(expires_at, local_midnight(tomorrow)) + duration
active   now < expires_at
```

A 30-day subscription created 12 Aug: `local_midnight(13 Aug) + 30 days` =
`12 Sep 00:00` local, so the merchant's **last valid day is 11 Sep**. That gap
is the one trap here — the stored timestamp names the first dead day, not the
last live one — so **every surface that shows an expiry date must render the
last valid day**, not the raw column.

The term is measured from the end of the creation day, so the remainder of that
day is free: 12 Aug through 11 Sep inclusive is **31 usable days** for a 30-day
term. That is the requirement as written ("calculated from the end of the day on
which the subscription is created") and it is deliberate — a merchant signed at
16:00 gets a whole first day either way. Do not "correct" it to
`local_midnight(today) + duration`, which silently shortens every term by a day.

Exclusive midnight rather than the `23:59:59` the requirement was first written
with: that loses the final second of the day (at `23:59:59.5` the merchant is
already inactive) and forces an inclusive comparison, which is a fencepost
waiting to be got wrong in one of the two places that check it.

**Renewal extends from the later of the current expiry and today.** Renewing
early must not burn the days already paid for, and a merchant who lapsed in
March must not be credited the dead months. `max()` covers both in one
expression; no branch, no "is it still active" question first.

**Offset changes are why the addition happens in local terms.** Adding
`timedelta(days=30)` to an aware datetime adds 30 × 24h of absolute time, so a
term crossing a clock change lands at 23:00 or 01:00 local and the merchant
gains or loses an hour of their last day. Add the days to the local *date*,
combine with midnight, attach the zone, then convert to UTC.

This is not hypothetical for this deployment. British Columbia legislated an end
to seasonal clock changes, and the tz database has **America/Vancouver leaving
DST permanently on 2 Nov 2026**, fixed at UTC-7 thereafter and reported under
the name `MST`. Winter in Vancouver is no longer UTC-8. Any code, fixture, or
worked example that assumes `-08:00` for a December date — or that a Vancouver
midnight is `08:00Z` in winter — is wrong from that date on. Computing on local
dates is what made this a tzdata update rather than a code change.

**A fixed operator timezone, not a per-merchant one.** Every merchant is in
Metro Vancouver; a column would be another field the crawler must populate and
silently shift expiry when it is wrong. When a merchant is signed in another
timezone this becomes a `merchants.timezone` defaulting to the setting — an
addition, not a rewrite.

**Only `day` is implemented.** `duration_unit` accepts `day | month | year` at
the database so the schema does not need revisiting, but the API rejects
anything but `day`, and a year is expressed as 365 days. Calendar months need
either a new dependency or hand-rolled end-of-month clamping (what is 31 Jan
plus one month?), and no product requirement has asked for one yet.

## R19 — one row, three states, no history

One `subscriptions` row per merchant, enforced by `UNIQUE (merchant_id)`.
Renewal mutates it in place, so `created_at` means "first ever subscribed" and
`duration`/`duration_unit` describe only the most recent term. `updated_at`
records when it last moved. There is no billing, invoicing, or dispute process
to serve, so an audit trail would be built for a requirement that does not
exist.

```text
ACTIVE      the only state that opens the gate
CANCELLED   suspended by the operator
PAUSED      suspended, expected to resume
```

`CANCELLED` and `PAUSED` exist because dropping `merchants.status` otherwise
left no way to switch off a merchant with 300 days remaining, short of lying
about their expiry or deleting the row.

**Suspension blocks; the clock keeps running.** `expires_at` never moves and
there is no `paused_at`. Resuming is `status = 'ACTIVE'` and nothing else.
Crediting paused time means storing when the pause began and handling pause
while already expired, double-pause, and resume-after-expiry — three edge cases
bought for a fairness the operator can deliver with a renewal instead. The name
is the cost: `PAUSED` means suspended, not frozen.

## R20 — the crawler owns the write path; seeding is deleted

`apps/api/app/seed.py` and `merchants/*.yaml` are removed, along with R13 and
L19's "YAML seeding is demo-only". The lead crawler already creates every real
merchant, and keeping a second write path would mean an idempotent upsert that
re-runs over subscriptions — where the safe behaviour (never touch `expires_at`)
makes the file useless for renewals and the useful behaviour (recompute) turns
editing a typo into a free extension.

Subscriptions are created, renewed, and suspended through the leads API. See
`lead-crawler-spec.md` §2.1.4a.

**The migration backfills.** Every existing merchant gets an `ACTIVE`
subscription of 365 days from the end of the migration day. Without it, shipping
this kills every QR code already in circulation, which is not what a schema
change is allowed to do. These are pilot merchants who have never been billed,
so a year is the honest value rather than a placeholder.

## Subscription risks, accepted

Numbered `S1`–`S3` so they do not collide with the three general risks above.

* **S1 — nothing warns before expiry.** No job, no email, no dashboard alert.
  The operator finds out a link is dead when they look at the saved-merchants
  list or a merchant complains. Acceptable at pilot scale with a year on the
  clock; the expiry dates are in the list so it is visible to anyone who looks.
* **S2 — the backfill grants a year to every crawled lead**, including prospects
  who were never contacted. Their links work for a year. The alternative —
  expiring them — breaks the demo URLs the crawler exists to produce.
* **S3 — the subscription endpoints are open, like every other leads endpoint**
  (L10). Anyone who reaches the host can grant themselves an unlimited
  subscription, and — new with `PATCH` — can cancel a paying merchant's live QR
  code. Until this change the worst an anonymous caller could do was insert rows
  and rewrite AI grounding; it can now switch off a merchant in production. See
  `lead-crawler-spec.md` §2.1.12, where this is the first consequence that has
  an effect a customer would notice.
