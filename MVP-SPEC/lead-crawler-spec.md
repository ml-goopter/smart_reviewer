# 2.1 Merchant Lead Crawler — MVP

An internal prospecting tool: search Google for merchants, save one into the
system, and hand back the URL that already powers Smart Reviewer.

This is **not a standalone product**. A saved lead is a row in the existing
`merchants` table, and the URL the tool produces is the existing QR entry route
`/m/:merchantId`. Read `DECISIONS.md` first; the decisions below extend it and
are numbered `L1`–`L19` so the two lists never collide.

---

## 2.1.0 Decisions

| # | Decision |
|---|---|
| L1 | The crawler writes an **ACTIVE row in the existing `merchants` table**. The deliverable URL is the existing `/m/:merchantId` |
| L2 | `slug` is slugified `name`+`city`, suffixed on collision, and **returned in the save response** |
| L3 | **Places API (New) `searchText`**, behind a provider adapter with a fixture-backed fake |
| L4 | Rating ceiling and review count are filtered **in our code**; pagination runs to Google's ceiling and the response **reports the funnel** |
| L5 | **Geocoding API** resolves the search origin; the response echoes what it resolved to |
| L6 | Category is a **curated dropdown** → `includedType`; all other free text → one `textQuery` |
| L7 | `merchants` gains `website`, `google_rating`, `google_review_count`, `google_synced_at`, `source` |
| L8 | A duplicate Place ID is **create-or-read. Save never mutates an existing row** |
| L9 | The save body is **`{placeId}` only**; the server re-fetches Place Details and stores only what Google returned |
| L10 | **Auth is deferred, which here means fully open.** No nginx rule, no port change, no token |
| L11 | Google spend is bounded by a **console quota and a budget alert**, not by code |
| L12 | The UI is a **`/leads` route in the existing SPA**, unlinked from customer screens |
| L13 | Search results are **marked as already saved** via one indexed lookup |
| L14 | **`PUBLIC_BASE_URL`** in `config.py` builds the absolute copied URL |
| L15 | A partial Google failure **returns what matched**, flagged `partial` |
| L16 | `merchant_review_context` is **auto-filled from Places** on save and marked approved |
| L17 | **`GET /api/leads/merchants`** lists saved merchants, newest first |
| L18 | An **admin editor at `/leads/:merchantId`** covers the eight `review_context` fields |
| L19 | **No machine-vs-human provenance is tracked.** YAML seeding is demo-only; the editor is the real path |

---

## 2.1.1 Objective

1. Search for merchants using Google Places data.
2. View matching merchants.
3. Save a merchant into the system.
4. Copy its Smart Reviewer URL.
5. Fill in what Google cannot supply, so the URL demos well.

Step 5 is not decoration. Suggestion quality is bounded entirely by
`merchant_review_context`, and Places supplies two of its eight fields.

---

## 2.1.2 Merchant Search

### Criteria

| Input | Sent as | Filtered by |
|---|---|---|
| Text query | `textQuery` | Google |
| Business category | `includedType`, and `textQuery` when nothing was typed | Google |
| Address / postal code / city | geocoded → the rectangle's centre | Google |
| Radius | `locationRestriction.rectangle` — then the exact circle | Google, then **us** |
| Minimum rating | `minRating` | Google |
| Maximum rating | — | **us** |
| Maximum review count | — | **us** |

Google has no filter for review count and no rating ceiling, so those two run
after the fetch. This is why §2.1.3 reports a funnel rather than a bare list:
the filter that matters most to prospecting — *few reviews* — is the one Google
will not help with.

### Two things `searchText` will not do

Both were found against the live API, not against a mock, and both are pinned
by tests now.

**`locationRestriction` takes a rectangle, never a circle.** A circle is valid
for `searchNearby` and for `locationBias`, and a `circle` here is rejected with
`INVALID_ARGUMENT`. A bias would only nudge the ranking, so the request carries
the smallest rectangle containing the circle — whose corners reach about 1.41×
the radius — and the true radius is applied afterwards with haversine, using
the distance the result list already shows. A listing Google returns without
coordinates is kept: it satisfied the rectangle, and dropping it for missing
data would hide a merchant almost certainly in range.

**`textQuery` may not be empty.** "Every restaurant near this postal code" is
the most ordinary search this tool performs, and it carries no text at all. So
when nothing was typed, the category becomes the query as well as the type
filter. A location with no subject whatsoever is refused with
`criteria_too_broad` **before the geocode**, which is itself billed — inventing
a search term would silently decide what the operator was looking for, and
`searchNearby` is the API that actually answers that question.

### One text box, and matching is Google's

One free-text field, and **no separate merchant-name field**: a name and a
keyword would both land in the same `textQuery`, so separating them would
advertise a distinction the API does not make.

Whatever is typed goes to `textQuery` verbatim, and Google decides how it
matches. The system makes **no promise of exact, partial, or case-insensitive
matching**, because that behaviour is not ours to implement or guarantee. A
search for `Sushi Mura` may return `Sushi Mura Japanese Restaurant` and may
return neighbours.

### Category

A curated list of Google place types, held in the API and rendered as a
dropdown. It covers what the sales team actually prospects — restaurant, cafe,
bar, bakery, hair salon, nail salon, spa, dentist — rather than Google's full
table, most of which is irrelevant.

`strictTypeFiltering` stays **off**. It restricts results to places whose
*primary* type equals `includedType`, so a sushi restaurant — primary type
`sushi_restaurant` — would be dropped from a `restaurant` search.

Anything not in the dropdown goes in the text query instead.

### Geocoding

A circle needs a centre, and the user supplies a postal code, a city, or a
street address. One Geocoding call resolves it, and **the response echoes the
resolution**:

```json
"resolvedLocation": {
  "query": "V6X 1T3",
  "formatted": "Richmond, BC V6X 1T3, Canada",
  "lat": 49.1745, "lng": -123.1370
}
```

Echoing it is the point: a typo'd postal code otherwise searches the wrong
suburb and returns a plausible list of the wrong merchants, silently.

An unresolvable location is a `400`, not an empty result — nothing was
searched, and saying "no matches" would be a lie.

### Pagination

Google returns at most 20 results per page and stops issuing page tokens after
60. The adapter fetches pages until it has enough post-filtered matches or runs
out of tokens, whichever comes first, capped by `LEAD_SEARCH_MAX_PAGES`.

Each page is a separately billed request. Three pages plus a geocode is the
worst case for one search.

---

## 2.1.3 Search Results

Each result carries: name, category, formatted address, distance, Google
rating, review count, phone, website, Place ID, and whether it is already
saved.

Distance is haversine from the resolved centre — Google returns coordinates,
not distances.

### The funnel line

```
V6X 1T3 · 5 km · Restaurant · 3.5–4.5 · ≤200 reviews
─────────────────────────────────────────────────────
60 listings searched · 12 matched
```

Without it, a strict review-count cap produces a nearly empty list that reads
as a broken search rather than a narrow filter.

### Already-saved rows

Every returned Place ID is checked against `merchants` in a single
`WHERE google_place_id = ANY(:ids)` — served by the existing partial unique
index `merchants_google_place_id_idx`. Saved rows carry their merchant id, URL
and status, so the row's action is **Copy URL** rather than Save, with no
round trip to discover it.

### Partial failures

If Google errors after at least one page has succeeded, the response returns
what matched with `partial: true`, and the funnel says what was actually
searched:

```
20 of up to 60 listings searched · 4 matched
⚠ Google returned an error partway through — results incomplete
```

Discarding four real leads and re-billing page 1 would serve nobody. A failure
on the *first* page is a `502` — there is nothing to return.

---

## 2.1.4 Save Merchant

### Request

```json
POST /api/leads/merchants
{ "placeId": "ChIJ-b-XikB2hlQRq91JgwcRa9s" }
```

The Place ID is the **only** thing accepted. The server calls Place Details
itself and writes only what Google returned. With auth deferred (L10) this is
what keeps the endpoint from being a write-anything hole, and it also stops a
stale browser tab from recording last week's rating as today's fact.

### Duplicate detection

`google_place_id` is the key, and it is always present — `searchText` always
returns one.

**Save never mutates an existing row.** A merchant seeded with curated context,
or deliberately set to `ARCHIVED`, is returned exactly as it stands:

```
201  {created: true,  status: "ACTIVE",   url: "https://…/m/8f3c…"}
200  {created: false, status: "ACTIVE",   url: "https://…/m/8f3c…"}
200  {created: false, status: "ARCHIVED", url: null,
      note: "archived — this URL will not open"}
```

Refreshing the Google snapshot on re-save would be the merchant-data refresh
that §2.1.15 defers, arriving through a side door and only for whichever rows
someone happened to re-search. Reactivating an archived row would overrule
whoever archived it.

### What is written

| Column | Source |
|---|---|
| `name` | `displayName.text` |
| `category` | `primaryTypeDisplayName.text` |
| `address` | `formattedAddress` |
| `city`, `province_state`, `postal_code`, `country` | `addressComponents` |
| `phone` | `nationalPhoneNumber` |
| `website` | `websiteUri` |
| `google_place_id` | `id` |
| `google_profile_url` | `googleMapsUri` |
| `google_review_url` | derived from the Place ID by the existing template |
| `google_rating` | `rating` |
| `google_review_count` | `userRatingCount` |
| `google_synced_at` | now |
| `source` | `'GOOGLE_PLACES'` |
| `status` | `'ACTIVE'` |
| `slug` | L2 |

`status = ACTIVE` is what makes the copied URL work immediately:
`google_review_url` derives from the Place ID, and session creation requires
only an ACTIVE merchant with that URL present.

### Slug

Slugified `name`+`city` — `Sushi Mura` in Richmond becomes
`sushi-mura-richmond` — with `-2`, `-3` on collision. It is returned in the
save response and shown in the UI, because `slug` is unique and a second row
claiming the same one is a hard failure at insert.

### Review context

The same Place Details response fills `merchant_review_context`:

| Context field | Source |
|---|---|
| `business_summary` | `editorialSummary.text`, falling back to a sentence built from primary type + city |
| `selling_points` | the atmosphere booleans that are **true** — dine-in, takeout, outdoor seating, vegetarian, good for children, allows dogs, reservable |
| `experience_topics` | a per-category default table |
| `products`, `services`, `menu_items`, `approved_keywords`, `custom_instructions` | **null** |

The nulls are deliberate. Google does not know the menu, and inventing one is
how the AI starts praising a dish that does not exist.

`is_approved` is set **true**, with `approved_at` set to now. The generator
ignores context entirely unless it is approved, so leaving it false would store
context that changes nothing — which is the opposite of the reason for
fetching it.

---

## 2.1.5 Merchant URL

The URL is the existing entry route, built from `PUBLIC_BASE_URL`:

```
https://{PUBLIC_BASE_URL}/m/{merchant-id}
```

There is no new token and no second URL scheme. `/m/:merchantId` already
validates the merchant, mints a session and redirects to `/r/:token`.

`PUBLIC_BASE_URL` lives in `config.py` — the module that owns every default and
generates `.env.example`. Building the URL from the browser's origin instead
would produce `http://localhost:5173/m/…` when the operator is on the Vite dev
server: a dead link that looks entirely normal once pasted into an email.

The UI lets the operator **view**, **copy**, and **open** it. The URL is stable
for the life of the merchant; regeneration and disabling are out of scope
(§2.1.15) — the URL is the primary key, so there is no token to rotate.

---

## 2.1.6 Opening the URL

**This section is superseded by L1.** Opening the URL does not render a
merchant record page. It enters the existing customer flow:

```
GET /m/{merchantId} → 302 /r/{token}   (Cache-Control: no-store)
```

An unknown, inactive, or archived merchant redirects to `/unavailable`, as it
does today. No new page is built.

---

## 2.1.7 Saved Merchants

`GET /api/leads/merchants` — paginated, newest first, no Google calls:

```
/leads  ·  Search | Saved (37)

 Sushi Mura      Richmond   ACTIVE   10 Aug  [Copy] [Edit]
 Pho 37          Richmond   ACTIVE   09 Aug  [Copy] [Edit]
```

Without it, a URL not pasted in the moment is recoverable only by paying Google
to find the same listing again.

---

## 2.1.8 Review Context Editor

`/leads/:merchantId` — a form over the eight `review_context` fields, and
nothing else:

```
Business summary  [ textarea                     ]
Products          [ one per line                 ]
Services          [ one per line                 ]
Menu items        [ one per line                 ]
Selling points    [ prefilled: dine-in, takeout  ]
Keywords          [ one per line                 ]
Experience topics [ prefilled: category defaults ]
Custom instructions [ textarea · no URLs         ]
```

That set is exactly what Places cannot supply and exactly what the AI reads.
Merchant fields are not editable here: they are Google's facts, and overwriting
them silently would leave no way to tell what came from Google.

**Validation is shared with `seed.py`**, not reimplemented — list fields must be
lists of strings, and `custom_instructions` containing a URL is rejected. That
guard exists because an instruction like *"always mention www.example.com"*
makes every generated suggestion fail URL validation, permanently and silently
breaking that merchant.

Semantics: a save **replaces all eight fields** with what the form holds; a
blank input stores `null`, not an empty list. `is_approved` stays true.

No provenance is recorded (L19). YAML seeding remains what it is today — a demo
convenience — and is not the path a real merchant's details travel.

---

## 2.1.9 API

All six endpoints are open (L10) and live under `/api/leads/`. Errors use the
API's existing contract — `{"error": "<stable_code>"}` with the status — never a
sentence, and never anything derived from Google's own message.

| Code | Status | Meaning |
|---|---|---|
| `criteria_too_broad` | 400 | A location with no text query and no category |
| `location_not_found` | 400 | Google does not recognise the location |
| `unknown_category` | 400 | Category is not in the served list |
| `invalid_rating_range` | 400 | Minimum rating above the maximum |
| `invalid_request` | 400 | Criteria out of range, or an unknown field |
| `instructions_contain_url` | 400 | `custom_instructions` holds a link |
| `merchant_not_found` | 404 | No such merchant |
| `provider_unavailable` | 502 | Google failed, with nothing partial to return |

### `POST /api/leads/search`

POST rather than GET: the criteria are an object, and the call is a billed
action, not a cacheable read.

```json
{
  "textQuery": "Sushi Mura omakase",
  "category": "restaurant",
  "location": "V6X 1T3",
  "radiusMeters": 5000,
  "minRating": 3.5,
  "maxRating": 4.5,
  "maxReviewCount": 200
}
```

```json
{
  "resolvedLocation": { "query": "V6X 1T3", "formatted": "…", "lat": 49.17, "lng": -123.14 },
  "searched": 60,
  "matched": 12,
  "partial": false,
  "results": [
    {
      "placeId": "ChIJ…", "name": "Sushi Mura", "category": "Sushi Restaurant",
      "address": "…", "distanceMeters": 1200, "rating": 4.2,
      "reviewCount": 187, "phone": "+1…", "website": "https://…",
      "saved": false, "merchantId": null, "url": null, "status": null
    }
  ]
}
```

### `POST /api/leads/merchants`

Body `{placeId}`. Returns `201`/`200` per §2.1.4, with `created`, `merchantId`,
`slug`, `status`, `url`, and the stored merchant fields.

### `GET /api/leads/merchants`

`?limit=&offset=`. Newest first.

### `GET /api/leads/categories`

The category dropdown's contents. Served rather than duplicated in the bundle:
a category the SPA offers but the server rejects is a 400 nobody can act on.

### `GET /api/leads/merchants/{id}/context`

The merchant and its current context, for the editor to load.

### `PUT /api/leads/merchants/{id}/context`

Body is the eight fields; all eight are replaced. `404` for an unknown
merchant, `400 instructions_contain_url` for the URL rule, `400
invalid_request` for anything else — **not** 422, because the API's existing
error handler maps every validation failure to a 400 with a stable code, and a
second convention would be one the SPA has to learn twice.

---

## 2.1.10 Data Model

One migration:

```sql
ALTER TABLE merchants
  ADD COLUMN website             text,
  ADD COLUMN google_rating       numeric(2,1),
  ADD COLUMN google_review_count integer,
  ADD COLUMN google_synced_at    timestamptz,
  ADD COLUMN source              varchar(30) NOT NULL DEFAULT 'YAML';

ALTER TABLE merchants
  ADD CONSTRAINT ck_merchants_source
  CHECK (source IN ('YAML', 'GOOGLE_PLACES'));
```

`source` defaults to `'YAML'` because seeding is the only path that exists
today, so every existing row is correctly labelled by the default alone.
`varchar` + `CHECK` rather than a Postgres enum, matching the reasoning already
recorded on `MERCHANT_STATUSES`.

No new tables. No new index: `merchants_google_place_id_idx` already serves
both duplicate detection and the saved-row lookup.

`google_synced_at` records the snapshot's age, so the UI can render
"4.2 ★ · 187 reviews (as of 10 Aug 2026)" instead of implying live data — and
so the deferred refresh feature has something to update.

---

## 2.1.11 Configuration

New settings, in `config.py` and nowhere else, so `.env.example` regenerates
and the existing drift test covers them:

| Setting | Why it exists |
|---|---|
| `LEAD_PROVIDER` | `google` or `fake`. The fake answers from fixed Richmond and Vancouver listings, so the whole tool runs and demos with no billing account. Unlike `AI_PROVIDER` this selects an adapter, so an unknown value is refused rather than defaulted |
| `GOOGLE_API_KEY` | Places and Geocoding. A secret; no default |
| `PUBLIC_BASE_URL` | The origin in the copied URL, which is not necessarily the one the operator is browsing |
| `LEAD_SEARCH_MAX_PAGES` | Bounds billed requests per search |
| `LEAD_SEARCH_PAGE_SIZE` | Google's per-page ceiling is 20; lower is cheaper per page |
| `LEAD_SEARCH_TIMEOUT_SECONDS` | Must stay below nginx's `proxy_read_timeout` |

Restrict the key to those two APIs in the Cloud console, set a per-day request
quota on each, and set a billing budget alert (L11). That is the spend ceiling;
there is none in code.

---

## 2.1.12 Exposure and accepted risks

**The crawler endpoints are open.** `nginx.conf` proxies every `/api/*` path
with a regex catch-all, and `docker-compose.yml` publishes the API on `8000` to
all interfaces, so `/api/leads/*` is reachable at both `:8080` and `:8000`.
Neither is changed. Deferring auth was decided to mean exactly this.

Consequences, accepted deliberately for a prototype:

1. **Anyone who reaches the host can spend your Google quota.** The console
   quota is what bounds the damage, not the application.
2. **Anyone who reaches the host can insert merchants** into the same table the
   customer-facing product reads. They can only insert what Google returns for
   a Place ID (L9), and they cannot modify existing rows through save (L8) —
   but `PUT …/context` can rewrite any merchant's AI grounding.
3. **`TRUST_PROXY_HEADERS` is true**, so a caller hitting `:8000` directly also
   chooses its own `X-Real-IP`, and therefore its own rate-limit bucket on the
   *existing* endpoints.

Closing these later is a `location` block and a `127.0.0.1:` prefix, plus real
auth on `/api/leads/*`.

**HTTPS remains a functional requirement** for anything other than `localhost`,
for the reason already recorded: `navigator.clipboard` is undefined outside a
secure context, so the reviewer's core mechanic fails silently.

---

## 2.1.13 MVP User Flow

1. **Search** — postal code `V6X 1T3`, radius 5 km, category Restaurant, rating
   3.5–4.5, at most 200 reviews.
2. **Confirm the origin** — the resolved location is echoed above the results.
3. **Review results** — funnel line, then the matches; already-saved rows are
   marked.
4. **Select and save** — one click; the server re-fetches Place Details, writes
   the merchant and its context, and returns the URL and slug.
5. **Copy the URL** — absolute, built from `PUBLIC_BASE_URL`.
6. **Fill the gaps** — open the editor and add products, menu items, keywords
   and selling points. Until then the merchant demos on Google's generic
   summary alone.

---

## 2.1.14 Acceptance Criteria

The MVP is complete when each of these can be demonstrated:

1. A search by postal code and radius returns results, and the response echoes
   the resolved coordinates.
2. An unresolvable location returns `400` and no result list.
3. A category selection restricts results by Google place type, and a sushi
   restaurant still appears under Restaurant.
4. Rating floor is applied by Google; rating ceiling and review-count cap are
   applied by us, and the response reports `searched` and `matched`.
5. Pagination stops at `LEAD_SEARCH_MAX_PAGES` or when Google stops issuing
   tokens, whichever comes first.
6. A Google failure after page 1 returns the matches found so far with
   `partial: true`; a failure on page 1 returns `502`.
7. Results already in the database are marked saved and carry their URL.
8. Saving a new Place ID returns `201` with `created: true`, a merchant id, a
   slug, and an absolute URL.
9. That URL, opened, redirects to `/r/:token` and the reviewer shows the
   merchant's name.
10. The saved merchant has `google_place_id`, `google_rating`,
    `google_review_count`, `google_synced_at` and `source = 'GOOGLE_PLACES'`.
11. Its `merchant_review_context` exists, is approved, and has a
    `business_summary` and `experience_topics`.
12. Saving the same Place ID again returns `200`, `created: false`, the same
    merchant id and URL, and **no column on that row has changed**.
13. Saving a Place ID belonging to an ARCHIVED merchant returns that merchant
    with `url: null` and does not reactivate it.
14. Two merchants with the same name and city receive distinct slugs.
15. The saved list returns previously saved merchants newest first, with no
    Google call.
16. The editor saves all eight context fields, stores blanks as `null`, and
    rejects `custom_instructions` containing a URL with the same message
    `seed.py` produces.
17. After editing, a new session for that merchant produces suggestions
    grounded in the edited context.

---

## 2.1.15 Out of Scope

Deferred, with the reason where it is not obvious:

* **Authentication and authorization** — L10, accepted risk, §2.1.12
* URL regeneration and disabling — the URL is the primary key; there is no
  token to rotate
* Merchant-data refresh — including on re-save, which is why L8 forbids it
* Using Google review texts as AI grounding — a different authenticity position
  than R1's "merchant context only", to be decided on purpose rather than by
  field mask
* Editing merchant fields (name, category, status, review URL override)
* Sales representative assignment, lead ownership, lead scoring
* Recent review activity filtering, historical review tracking
* Automated crawling, scheduled searches, saved searches
* Bulk import, complex AND/OR filter logic
* CRM workflow, merchant analytics, sales activity tracking

---

## 2.1.16 Test Plan

Per R15a — if a failure means "the code is wrong" it is a unit test; if it means
"the schema or the transaction is wrong" it is an integration test.

**Unit** (`tests/unit/`, fixture provider, no containers, no Google):

* rating-ceiling and review-count filtering, including the boundary values
* funnel counting: `searched` vs `matched`, and both under a partial failure
* pagination stops at the cap, at exhausted tokens, and when enough matched
* page-1 failure → `502`; page-2 failure → partial results
* slug generation and collision suffixing
* Place Details → merchant column mapping, including missing optional fields
* Place Details → context mapping: editorial summary present, absent (fallback
  sentence), and the true-only atmosphere selection
* unresolvable geocode → `400`
* context editor validation, shared with `seed.py`

**Integration** (`tests/integration/`, real Postgres):

* the partial unique index on `google_place_id` rejects a second insert
* `slug` uniqueness rejects a collision the generator failed to avoid
* create-or-read: a second save returns the existing row **with every column
  unchanged**
* the new `source` CHECK constraint rejects an unknown value

---

## 2.1.17 Open item

The field mask is **functionally** confirmed against the live API —
`editorialSummary`, the address components and the atmosphere booleans all
return. What is still unconfirmed is the **price**: those fields sit in higher
Place Details SKU tiers than the basics, and `DETAILS_FIELDS` in
`google_places.py` is what sets the per-save cost. Check it against Google's
current pricing table before running at volume, and confirm at the same time
how Google rounds `minRating` — a coarse floor changes where our own filtering
has to start.

A search costs **2 to 4 billed requests**: one Geocoding call, then one to three
Places pages. A save costs one more. Nothing else calls Google — the review URL
is a plain template, not an API.
