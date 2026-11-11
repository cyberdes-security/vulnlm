# Operations and maintenance

English · [Türkçe](operations.tr.md) · [README](../README.md)

Schema upgrades run transactionally at startup, serialized by a database lock. `schema_migrations` records each revision; `backend/migrations/v001_initial.py` freezes the original schema, v002 adds document provenance, v003 adds sub-agent delegation records and v004 adds the covert-channel cache medium. Add a new revision for future changes instead of modifying applied ones. Compatible unversioned databases retain their data; incompatible columns and unknown/newer revisions stop startup without resetting data. From the backend directory, `python -m migrations` runs upgrades alone.

Before upgrading, back up PostgreSQL with `pg_dump`, or copy SQLite while the application is stopped. Back up the matching `DATA_DIR` (configuration, keys, public files and Chroma) during the same maintenance window. Restore into a separate installation and check `/ready`. Automatic downgrade is not supported: recovery restores the matching application version and backup. A lab reset deletes records and recreates revisions; it is not backup recovery.

## Document provenance

Use **Advanced settings → Manage document trust** with the actual Admin demo cookie session. Every upload starts unapproved, irrespective of ID, source label, or a supplied `trusted` field. Approval is stored in SQL and mirrored into Chroma. Newly created training fixtures receive explicit approval during seeding. Existing documents are **not automatically approved during migration**; review and approve reference documents, including Cedar, in the panel after upgrading. Startup rebuilds index metadata from SQL approvals. If indexing an approval fails, repair storage, restart, and verify inventory/search before assuming it completed.

With `rag-rank-crowding` **on**, similarity-only retrieval remains vulnerable: attacker documents can displace approved references. With it **off**, approved/unapproved candidates are queried separately after applying the owner scope. Each group contributes at most `min(100, 8 × requested results)` candidates. Approved documents take priority, relevance order stays intact within each group, and duplicate content is normalized for case/whitespace. A heavily duplicated window may produce fewer results. Approval never bypasses owner filtering or makes embedded instructions safe; other scenario switches retain their behavior. Hash embeddings remain a teaching mechanism, not a semantic search benchmark.

Operator API: `GET /lab/documents` and `PUT /lab/documents/{id}/trust` with `{"trusted":true|false}`. Both require the actual Admin demo cookie session; forged JWTs or role-escalation exercises cannot grant this operator access.

## Readiness and telemetry

`/health` retains its app/DB check. `/ready` checks the schema revision, Chroma when enabled, and whether the active model is installed/reachable; it returns 200 or 503 without running inference. Native development uses the model server’s `/models` endpoint. This does not certify model output or attack outcomes.

`/lab/metrics` exposes Prometheus text to an authenticated Admin demo cookie session: HTTP response counters by route/status, duration sum/count, and uptime. Scrapers need a valid operator session and must renew it on expiry. Counters belong to each worker and reset on restart; scrape workers separately.

Operational stdout logs are JSON. `X-Request-ID` correlates HTTP responses with request/error events. Unexpected errors, watcher failures and readiness failures record event names, component and exception type, excluding exception messages. Configure your log collector to alert on ERROR events, increasing 5xx counts or persistent readiness failures. No external monitoring service is contacted automatically.

Operational logs exclude query strings, raw path parameters, request bodies, passwords/cookies/tokens and model prompts. Scenario audit records remain separate and obey their own vulnerability switches. Docker disables Uvicorn's raw access log; use `uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log` for native runs too.

## Maintenance boundaries

`main.py` assembles the app; `routes/` holds HTTP adapters, `chat_service.py` owns context/agent execution, `observability.py` owns telemetry, and `migrations/` owns schema history. Frontend files are build-free ES modules: `app.js` handles sessions/chat and `frontend/js/` handles language, API, catalogue, settings, models and provenance. Serve them over HTTP rather than opening `index.html` directly.

The normal pytest suite covers migration/adoption/rollback, provenance and the preserved crowding vulnerability, readiness and log privacy. `RUN_BROWSER_TESTS=1` adds Chromium checks for modules, TR/EN copy and document trust. PostgreSQL validation must use a dedicated disposable test database.

## Repeated agent calls

Each chat/image request owns execution receipts keyed by tool name and canonical arguments. A repeated call, even with a new transport ID or reordered keys/equivalent numeric spelling, returns the original result or error without dispatching again. Errors are retained because an effect may have committed before the error occurred.

Each model response dispatches at most one new action; other planned actions are marked `deferred` in the trace and omitted from model history, avoiding reinforcement of guessed arguments while the model replans from actual results. The existing agent-step budget still applies. Evidence distinguishes `executed`, `reused` and `deferred`, and response/UI execution counters count actual dispatches. Receipts do not span HTTP requests or change the direct API/MCP transaction-replay exercise or approval controls.

## UI session log

Model status normally refreshes every 15 seconds, or every 1.5 seconds during downloads. Repeated connection failures produce one entry per failure state, with retries after 15, 30 and at most 60 seconds. Recovery produces one entry. HTTP 401 ends the invalid local session, stops polling and shows sign-in; a network outage alone does not end the session. This UI behavior does not change server audit records or scenario controls.
