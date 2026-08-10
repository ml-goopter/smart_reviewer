from fastapi import FastAPI

from app.errors import install_error_handlers
from app.routers import entry, leads, review

app = FastAPI(title="Smart Reviewer API", docs_url=None, redoc_url=None)

install_error_handlers(app)
app.include_router(review.router)
# Internal-facing and unauthenticated for the prototype. nginx proxies all of
# /api/*, so this is reachable wherever the API is — accepted deliberately,
# with the Google key's per-day quota as the ceiling on what that costs.
app.include_router(leads.router)
# Browser-facing, outside /api on purpose: it is a page the customer navigates
# to, not an endpoint the SPA calls. nginx routes /m/ here explicitly, or the
# static bundle would answer it with index.html and the QR would dead-end.
app.include_router(entry.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness only.

    Deliberately does not touch the database: nginx and the container
    orchestrator use this to decide whether the process is up, and coupling
    that to Postgres turns a slow query into a restart loop.
    """
    return {"status": "ok"}
