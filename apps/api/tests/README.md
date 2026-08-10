# Tests

Two layers, split by whether the dependency is scaffolding or the subject.

```
tests/unit/          no database, no network. Everything outward is substituted.
tests/integration/   a real Postgres, because the database is what is under test.
```

## `tests/unit/`

```bash
docker compose exec api python -m pytest tests/unit     # or, with the deps installed
pytest tests/unit                                       # anywhere, no containers
```

Routes, pure functions, and configuration. The seam nearest the code under test
is replaced — `dependency_overrides` for the request-scoped `Session`,
`monkeypatch.setattr` for the service a router calls — and the test asserts on
both the response coming back and the arguments going out.

A failure here points at the code. It cannot be a stopped container, a stale
schema, or another test's leftover rows.

## `tests/integration/`

```bash
docker compose exec api python -m pytest tests/integration
```

Deliberately small, and only for properties Postgres itself provides:

| File | Why it cannot be mocked |
|---|---|
| `test_schema_constraints.py` | Asserts the database rejects a duplicate token, a negative counter, blank text, a suggestion belonging to another session. Against a stub these assert that the stub does what it was told |
| `test_generation_cap.py` | Concurrent claims never exceed the cap. The property is the atomicity of one `UPDATE … WHERE` under real threads |
| `test_generation_refund.py` | R6b's conditional refund. The failure it pins — a reissued `generation_number` colliding with the unique constraint, 500ing that session until it expires — reproduces only against a real index |
| `test_seed.py` | Idempotent upsert on `slug`. The upsert is the behaviour |

These run against a real Postgres rather than SQLite: the schema depends on
JSONB, `gen_random_uuid()`, partial indexes, a composite foreign key with a
column-list `SET NULL`, and the atomic conditional `UPDATE` that enforces the
generation cap. None behave the same on SQLite, so an in-memory substitute would
pass while production broke.

The scratch database is built by running the migration, not
`Base.metadata.create_all` — the migration is what production executes, and
hand-edits to it would otherwise be untested.

## Which layer does a new test belong in?

Ask what a failure would mean. If it would mean "the code is wrong", it is a
unit test. If it would mean "the schema or the transaction is wrong", it is an
integration test. If a test needs a database only to have somewhere to put a
row, the database is scaffolding — mock it.
