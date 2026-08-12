# Smart Reviewer

Customer-facing review assistant. A merchant's permanent QR code leads to
`/m/:merchantId`, which mints a temporary session and redirects to `/r/:token`,
where the customer picks an AI-drafted suggestion, edits it, and continues to
the merchant's official Google review page with the text on their clipboard.

## Running locally

```bash
cp .env.example .env                           # fill in the secrets
(cd apps/web && npm install && npm run build)  # dist/ is gitignored
docker compose up -d                           # migrates, then starts
open http://localhost:8080/leads               # find a merchant, save, subscribe
```

**Merchants come from the lead crawler**, at `/leads`. Search Google Places,
save a listing, then subscribe it — a saved merchant's URL does not open until
it has an active subscription. There is no seed script and no YAML.

**Build the frontend before the first `up`.** nginx serves `apps/web/dist` from
a bind mount and `dist/` is gitignored, so on a fresh clone it does not exist —
and Docker silently creates an empty directory for a missing bind source, which
serves as 404s on every path rather than as an error. On Linux that directory is
created `root:root`, so a later `npm run build` fails `EACCES` until it is
removed with `sudo`. Order matters there; on macOS it is only 404s.

**Migrations run themselves.** A one-shot `migrate` service runs
`alembic upgrade head` and exits; the API waits on it completing successfully,
so the schema is always current before anything serves a request and a fresh
clone needs no separate step.

It is a service rather than an entrypoint inside the API container on purpose:
an entrypoint runs once per replica and again on every `--reload` restart, so
several workers would race each other into the same upgrade. This runs exactly
once per `up`, and a failed migration stops the API from starting at all rather
than leaving it to crash-loop against a half-built schema.

```bash
docker compose logs migrate            # what it did
docker compose run --rm migrate        # re-run on demand
docker compose run --rm migrate alembic downgrade -1
docker compose run --rm migrate alembic revision --autogenerate -m "..."
```

## Configuration

`apps/api/app/config.py` is the only place a default is written. `.env.example`
is generated from it, and a test fails if the committed file drifts:

```bash
docker compose run --rm api python -m app.config --example > .env.example
```

Copy it to `.env` and fill in the two secrets; everything else is commented out
with its default shown, and uncommenting is how you override. `.env` is passed
into the container whole, so every setting is tunable without touching code.

`docker-compose.yml` sets only `DATABASE_URL` and `TRUST_PROXY_HEADERS` — the
two values that differ by environment rather than by decision. A
`${VAR:-default}` fallback there would be a second source for a value the
settings module already owns, so a test rejects one.

Regenerating `.env.example` needs `docker compose restart api` afterwards: it is
a single-file bind mount, and the running container keeps serving the old
inode — so the drift test fails against a file you just fixed.

`OPERATOR_TIMEZONE` decides the calendar subscriptions expire on. A term runs to
midnight at the end of a day, and which instant that is depends on a zone — in
UTC a Richmond merchant would go dark at 5pm on their last day.

## Lead crawler

An internal prospecting tool at **`/leads`**: search Google Places, save a
merchant, copy its Smart Reviewer URL, then fill in what Google cannot supply.

```bash
LEAD_PROVIDER=fake docker compose up -d api   # no Google account needed
open http://localhost:8080/leads
```

A saved lead is a row in the same `merchants` table, with its review URL derived
from the Place ID. That URL does **not** open until the merchant is subscribed —
saving is prospecting, subscribing is signing them up.
`merchant_review_context` is auto-filled from the listing's editorial summary
and attributes and marked approved, which makes a fresh lead demo with
grounding rather than with the generic fallback. What Places has no field for —
products, menu items, keywords, custom instructions — is typed in the editor at
`/leads/:merchantId`.

**The crawler endpoints are unauthenticated**, deliberately, for the prototype.
nginx proxies all of `/api/*` and the API is published on `:8000`, so anyone who
can reach the host can search (spending your Google quota) and save. The ceiling
is the per-day quota on the key, not the application — set one, restrict the key
to Places and Geocoding, and add a billing alert. `SPECS/lead-crawler-spec.md`
§2.1.12 records this as an accepted risk with what closing it later costs.

Two Google filters do not exist: there is no rating *ceiling* and no review-count
filter at all. Both run in our code after the fetch, which is why every result
list states `N listings searched · M matched` — a strict review cap legitimately
empties the list, and without the funnel that reads as a broken search.

| Service | Purpose |
|---|---|
| `web` | Stock nginx on `:8080`. Serves `apps/web/dist` from a bind mount; proxies `/api/*` and `/m/*` to the API |
| `api` | FastAPI on `:8000`. Source mounted, `--reload` |
| `migrate` | One-shot `alembic upgrade head`, then exits. The API waits on it |
| `db` | Postgres 16, exposed on host `:5433` for psql |

nginx and the SPA are one service because the SPA is not a process — it is a
directory of files nginx reads. There is no Node runtime, and no image is built
for the frontend: `web` is the stock `nginx:1.27-alpine` with `apps/web/dist`
and `nginx/nginx.conf` mounted in. Deploying the frontend is therefore a build,
not an image push.

## Frontend development

One loop, and it is the same shape that runs in production:

```bash
cd apps/web && npm run build     # typechecks, then writes dist/
open http://localhost:8080
```

Rebuild and refresh. nginx picks up the new `dist/` on the next request — no
restart, no `docker compose` command of any kind. Correspondingly there is no
`--build` for `web`: it is a stock image, so `docker compose build web` prints
`No services to build` and **exits 0**, which is a trap if you expect it to
produce a bundle.

There is deliberately no Vite dev server in compose: **the nginx that answers
you is the nginx that answers in production**, so a route cannot work in
development and dead-end after deploy. That matters more here than HMR, because
the routing split is the part most likely to be got wrong — `/m/:merchantId`
must reach FastAPI, `/r/:token` must reach the SPA, and one file decides which.

The cost is a build per change and no hot reload. Accepted deliberately.

**`npm run build` is now the only thing that typechecks shipped code.** No image
build runs `tsc` and there is no CI. It is `tsc --noEmit && vite build`, so a
type error exits non-zero and `dist/` is left holding the *previous* bundle —
which nginx keeps serving. Read the exit code: the symptom of a failed build is
not an error page, it is your change appearing not to have happened.

`npm run dev` on `:5173` still works for isolated component work:

```bash
cd apps/web && npm install
npm run dev              # http://localhost:5173
```

Vite proxies `/api` and `/m` to the API's published port, so the full flow —
including scanning `/m/:merchantId` — runs there too. But `vite.config.ts` is
then the router, not nginx, and the two express the same split in different
syntaxes with nothing checking that they agree. Add a route in one and forget
the other and it works at `:5173` and 404s at `:8080`. Verify anything
route-shaped at `:8080` before believing it.

## Tests

```bash
cd apps/web
npm run typecheck
npm test
```

```bash
docker compose exec api python -m pytest tests/unit   # no database needed
docker compose exec api python -m pytest              # both layers
docker compose exec db psql -U reviewer -d reviewer   # or psql -h localhost -p 5433
```

The suite is split by whether the database is the subject or the scaffolding —
`tests/unit/` mocks everything outward and runs with no containers,
`tests/integration/` keeps a real Postgres for what only Postgres verifies. See
`apps/api/tests/README.md`.

Integration tests build their own scratch database by running the migration, so
they cannot pass against a schema the migration does not actually produce.

The unit suite includes guards that read repo-level files rather than code —
`.env.example` drift, and every `proxy_read_timeout` in `nginx/`. Those files are
bind-mounted into the API container at `/repo` precisely so the documented
`docker compose exec api` command checks them; run the suite on the host and it
walks up to the real tree instead.

Never use `docker compose down -v`; it destroys `pgdata` along with it.

## HTTPS is a functional requirement, not hardening

`navigator.clipboard.writeText()` only works in a secure context. Copying the
review is the mechanic the entire product depends on, so **any environment
other than `localhost` must serve HTTPS or the product does not work.**

This bites first when testing the QR flow from a phone against
`http://<laptop-ip>:8080` — `navigator.clipboard` is `undefined` there, and
Continue-to-Google fails in exactly the setting the product is built for. Use a
TLS tunnel (`cloudflared`, `ngrok`, `tailscale serve`) for device testing.

Compose ships plain HTTP: nginx listens on 80 and is published as `:8080`.
Production terminates TLS at nginx itself — the `listen 443 ssl` and
`ssl_certificate` lines are present but commented out in `nginx/nginx.conf`
(:41, :47-48), along with the certificate mount in `docker-compose.yml`.
Enabling it is uncommenting those three places, not new configuration.

## Layout

```
apps/api/     FastAPI · SQLAlchemy · Alembic · provider adapters
apps/web/     Vite · React · TypeScript · plain CSS
nginx/        reverse proxy + static serving config
mockups/      accepted visual direction, screen by screen
SPECS/        requirements — DECISIONS.md is authoritative
```

`SPECS/DECISIONS.md` records the decisions the build is based on and
lists where the four original spec documents are superseded. Read it before the
others; they contradicted each other in several places and those contradictions
were resolved deliberately, not by accident.

## Flow

```
/leads ──▶ POST /api/leads/search    ──▶ Places searchText (up to 3 pages)
       ──▶ POST /api/leads/merchants ──▶ Place Details → merchant + context
                                          │
                                          ▼  https://{PUBLIC_BASE_URL}/m/{id}
```

```
QR → /m/:merchantId ──FastAPI──▶ creates the session
                                       │
                              302 → /r/:token
                                       │
     GET /api/review/sessions/:token ──┤  merchant name as soon as it lands;
                                       │  never generates (R4)
     POST .../suggestions ─────────────┤  batch 1, then Generate More (capped)
     POST .../select ──────────────────┤  records the choice, copies nothing
                                       │
     copy on click → POST .../complete (keepalive, not awaited) → Google
```

## AI provider

The `openai` SDK is a transport, not a commitment. Any OpenAI-compatible
endpoint is reachable by changing `OPENAI_BASE_URL` — Azure, OpenRouter,
Together, Groq, vLLM, Ollama — with no code change. Providers that are not
wire-compatible (Anthropic, Gemini) need one new adapter implementing
`app.providers.base.SuggestionProvider`; prompt construction, topic rotation,
and validation live outside the adapter and are shared.

Each generated row records `model_provider` and `model_name`, so a provider
switch is visible in the data rather than inferred.
