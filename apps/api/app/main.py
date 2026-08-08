from fastapi import FastAPI

from app.errors import install_error_handlers
from app.routers import entry, review

app = FastAPI(title="Smart Reviewer API", docs_url=None, redoc_url=None)

install_error_handlers(app)
app.include_router(review.router)
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
