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

Nothing runs migrations automatically, so a fresh clone starts with an empty
database until `alembic upgrade head` is run. The seed script is the only
merchant onboarding path — there is no admin UI — and it prints each merchant's
permanent `/m/:merchantId` URL, which is what goes into the QR code.

Both commands are safe to re-run: migrations are versioned, and the seed upserts
on `slug`. Editing a merchant means editing its YAML and running it again.

| Service | Purpose |
|---|---|
| `nginx` | Single public origin on `:8080`. `/api/*` → api, everything else → web |
| `web` | Next.js. Dev mode with source mounted; hot reload works through nginx |
| `api` | FastAPI. Source mounted, `--reload` |
| `db` | Postgres 16, exposed on host `:5433` for psql |

```bash
docker compose exec api python -m pytest    # API tests
docker compose exec web npx tsc --noEmit    # web typecheck
docker compose exec db psql -U reviewer -d reviewer   # or psql -h localhost -p 5433
```

End-to-end, against the running stack:

```bash
cd apps/web && npm ci && npx playwright install chromium
E2E_MERCHANT_ID=$(docker compose -f ../../docker-compose.yml exec -T db \
  psql -U reviewer -d reviewer -tA -c "select id from merchants where slug='pho37';" | tr -d '\r') \
  npx playwright test
```

The E2E suite stubs suggestion generation, so it costs nothing and is
deterministic. It exists for the one thing API tests cannot reach: the clipboard
write, which needs a real browser, a real user gesture, and a secure context.

Tests build their own scratch database by running the migration, so they cannot
pass against a schema the migration does not actually produce.

After changing `apps/web/package.json`, refresh the dependency volume —
compose reuses it across rebuilds, so a new package would otherwise never
appear in the container:

```bash
docker compose down web && docker volume rm smart_reviewer_web_modules
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
apps/web/     Next.js · TypeScript · Tailwind v4
nginx/        reverse proxy config
merchants/    per-merchant YAML, loaded by the seed script
MVP-SPEC/     requirements — DECISIONS.md is authoritative
```

`MVP-SPEC/DECISIONS.md` records the sixteen decisions the build is based on and
lists where the four original spec documents are superseded. Read it before the
others; they contradicted each other in several places and those contradictions
were resolved deliberately, not by accident.

## Flow

```
QR → /m/:merchantId ──server-side──▶ POST /api/review/sessions
                                       │
                              307 → /r/:token
                                       │
     GET /api/review/sessions/:token ──┤  merchant name in first paint,
                                       │  never generates
     POST .../suggestions ─────────────┤  batch 1, then Generate More (max 5)
     POST .../select ──────────────────┤  records the choice, copies nothing
                                       │
     copy on click → instruction screen → POST .../complete (keepalive,
                                          not awaited) → Google
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
