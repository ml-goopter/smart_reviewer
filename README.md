# Smart Reviewer

Customer-facing review assistant. A merchant's permanent QR code leads to
`/m/:merchantId`, which mints a temporary session and redirects to `/r/:token`,
where the customer picks an AI-drafted suggestion, edits it, and continues to
the merchant's official Google review page with the text on their clipboard.

## Running locally

```bash
cp .env.example .env                                        # fill in the secrets
docker compose up -d                                        # migrates, then starts
docker compose exec api python -m app.seed merchants/*.yaml # load merchants
open http://localhost:8080
```

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

Seeding is for demo merchants. It prints each merchant's permanent
`/m/:merchantId` URL, which is what goes into the QR code, and upserts on
`slug`, so editing a demo merchant means editing its YAML and running it again.
Real merchants arrive through the lead crawler below.

## Lead crawler

An internal prospecting tool at **`/leads`**: search Google Places, save a
merchant, copy its Smart Reviewer URL, then fill in what Google cannot supply.

```bash
LEAD_PROVIDER=fake docker compose up -d api   # no Google account needed
open http://localhost:8080/leads
```

A saved lead is a row in the same `merchants` table, `ACTIVE`, with its review
URL derived from the Place ID — so the URL it hands you works immediately.
`merchant_review_context` is auto-filled from the listing's editorial summary
and attributes and marked approved, which makes a fresh lead demo with
grounding rather than with the generic fallback. What Places has no field for —
products, menu items, keywords, custom instructions — is typed in the editor at
`/leads/:merchantId`.

**The crawler endpoints are unauthenticated**, deliberately, for the prototype.
nginx proxies all of `/api/*` and the API is published on `:8000`, so anyone who
can reach the host can search (spending your Google quota) and save. The ceiling
is the per-day quota on the key, not the application — set one, restrict the key
to Places and Geocoding, and add a billing alert. `MVP-SPEC/lead-crawler-spec.md`
§2.1.12 records this as an accepted risk with what closing it later costs.

Two Google filters do not exist: there is no rating *ceiling* and no review-count
filter at all. Both run in our code after the fetch, which is why every result
list states `N listings searched · M matched` — a strict review cap legitimately
empties the list, and without the funnel that reads as a broken search.

| Service | Purpose |
|---|---|
| `web` | nginx on `:8080`. Serves the built SPA; proxies `/api/*` and `/m/*` to the API |
| `api` | FastAPI on `:8000`. Source mounted, `--reload` |
| `migrate` | One-shot `alembic upgrade head`, then exits. The API waits on it |
| `db` | Postgres 16, exposed on host `:5433` for psql |

nginx and the SPA are one service because in production the SPA is not a
process — it is a directory of files nginx reads. There is no Node runtime.

## Frontend development

The compose `web` service builds a production image, so it is the wrong loop for
UI work. There are two dev loops; prefer the first.

### In compose, behind the real nginx

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
open http://localhost:8080
```

`/` stops being a directory of built files and becomes the Vite dev server, so
an edit under `apps/web/src` is live at `:8080` with no rebuild. **nginx stays
in the path** and keeps routing `/api` and `/m` to FastAPI, so the topology is
production's — a path that works here works in production, because the same
nginx decided both. `nginx/nginx.dev.conf` routes `/api` and `/m` identically;
`location /` proxies to Vite instead of serving files, and production's two
static-cache locations (`/assets/`, `= /index.html`) have no counterpart because
Vite serves those paths itself.

The Vite container reuses the `build` stage of `apps/web/Dockerfile`, so its
`node_modules` is installed for Linux. Do not mount the host's over it: a macOS
`esbuild` binary inside a Linux container fails at startup. Changing
`package.json` needs `--build`.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build vite
docker compose -f docker-compose.yml -f docker-compose.dev.yml down     # then plain `up -d` for production shape
```

### On the host

```bash
cd apps/web && npm install
npm run dev              # http://localhost:5173
```

Vite proxies `/api` and `/m` straight to the API's published port, so the whole
flow — including scanning `/m/:merchantId` — works at `:5173` with nginx out of
the picture. `vite.config.ts` and `nginx/nginx.conf` express the same routing
split and must stay in step: a path served by one and not the other works in
development and dead-ends in production. The compose loop above avoids that
class of mistake entirely, which is why it is the default recommendation.

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

After changing anything under `apps/web/`, rebuild the image to see it on
`:8080` — the bundle is baked in, not mounted:

```bash
docker compose up -d --build web
```

Never use `docker compose down -v`; it destroys `pgdata` along with it.

## HTTPS is a functional requirement, not hardening

`navigator.clipboard.writeText()` only works in a secure context. Copying the
review is the mechanic the entire product depends on, so **any environment
other than `localhost` must serve HTTPS or the product does not work.**

This bites first when testing the QR flow from a phone against
`http://<laptop-ip>:8080` — `navigator.clipboard` is `undefined` there, and
Continue-to-Google fails in exactly the setting the product is built for. Use a
TLS tunnel (`cloudflared`, `ngrok`, `tailscale serve`) for device testing.

The compose file listens on port 80 only. Production terminates TLS at nginx.

## Layout

```
apps/api/     FastAPI · SQLAlchemy · Alembic · provider adapters
apps/web/     Vite · React · TypeScript · plain CSS
nginx/        reverse proxy + static serving config
mockups/      accepted visual direction, screen by screen
merchants/    per-merchant YAML, loaded by the seed script
MVP-SPEC/     requirements — DECISIONS.md is authoritative
```

`MVP-SPEC/DECISIONS.md` records the sixteen decisions the build is based on and
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
