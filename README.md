# Smart Reviewer

Customer-facing review assistant. A merchant's permanent QR code leads to
`/m/:merchantId`, which mints a temporary session and redirects to `/r/:token`,
where the customer picks an AI-drafted suggestion, edits it, and continues to
the merchant's official Google review page with the text on their clipboard.

## Running locally

```bash
cp .env.example .env                                        # add an OPENAI_API_KEY
docker compose up -d
docker compose exec api alembic upgrade head                # create the schema
docker compose exec api python -m app.seed merchants/*.yaml # load merchants
open http://localhost:8080
```

Nothing runs migrations automatically yet, so a fresh clone starts with an empty
database until `alembic upgrade head` is run. The seed script is the only
merchant onboarding path — there is no admin UI — and it prints each merchant's
permanent `/m/:merchantId` URL, which is what goes into the QR code. It upserts
on `slug`, so editing a merchant means editing its YAML and running it again.

| Service | Purpose |
|---|---|
| `web` | nginx on `:8080`. Serves the built SPA; proxies `/api/*` and `/m/*` to the API |
| `api` | FastAPI on `:8000`. Source mounted, `--reload` |
| `db` | Postgres 16, exposed on host `:5433` for psql |

nginx and the SPA are one service because in production the SPA is not a
process — it is a directory of files nginx reads. There is no Node runtime.

## Frontend development

The compose `web` service builds a production image, so it is the wrong loop for
UI work. Run Vite on the host instead:

```bash
cd apps/web && npm install
npm run dev              # http://localhost:5173
```

Vite proxies `/api` and `/m` straight to the API's published port, so the whole
flow — including scanning `/m/:merchantId` — works at `:5173` with nginx out of
the picture. `vite.config.ts` and `nginx/nginx.conf` express the same routing
split and must stay in step: a path served by one and not the other works in
development and dead-ends in production.

```bash
cd apps/web
npm run typecheck
npm test
```

```bash
docker compose exec api python -m pytest              # API tests
docker compose exec db psql -U reviewer -d reviewer   # or psql -h localhost -p 5433
```

API tests build their own scratch database by running the migration, so they
cannot pass against a schema the migration does not actually produce.

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
QR → /m/:merchantId ──FastAPI──▶ creates the session
                                       │
                              302 → /r/:token
                                       │
     GET /api/review/sessions/:token ──┤  merchant name as soon as it lands;
                                       │  never generates (R4)
     POST .../suggestions ─────────────┤  batch 1, then Generate More (max 5)
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
