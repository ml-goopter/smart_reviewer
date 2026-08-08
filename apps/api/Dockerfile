# Pinned to 3.12: SQLAlchemy/psycopg wheel coverage for 3.14 is still
# incomplete, and a source build here would fail at image time.
FROM python:3.12-slim

# Pinned for the same reproducibility reason as the dependency bounds below;
# `latest` would make the toolchain drift between builds.
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /usr/local/bin/uv

WORKDIR /srv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Test dependencies are opt-in so a production image does not ship pytest and
# its transitive tree. docker-compose passes true for local development.
ARG INSTALL_DEV=false

# `-r pyproject.toml` installs the dependency list without building the project
# itself, which would need app/ to be present and defeat layer caching.
COPY pyproject.toml ./
RUN if [ "$INSTALL_DEV" = "true" ]; then \
        uv pip install --system --no-cache -r pyproject.toml --extra dev; \
    else \
        uv pip install --system --no-cache -r pyproject.toml; \
    fi

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
