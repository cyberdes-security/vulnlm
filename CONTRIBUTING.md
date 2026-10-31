# Contributing

English · [Türkçe](CONTRIBUTING.tr.md)

Run commands from the repository root containing `docker-compose.yml`, `backend/`, `frontend/` and `scripts/`. Read the [installation guide](docs/installation.md) and [walkthrough](docs/walkthrough.md) before changing a scenario. English and Turkish documentation are maintained together.

## Report a problem

Use the repository's issue tracker, when available. Include:

- Commit/revision, OS, Docker/Compose versions, and bundled or host Ollama.
- Model name/digest and active scenario settings for model-dependent behavior.
- The smallest request or UI sequence that reproduces the problem, with expected and actual status/effect.
- Logs or tool evidence with credentials, session cookies and personal information removed.

Distinguish an intentionally vulnerable scenario from a regression. Model refusal is a valid experiment outcome; a transport error is an integration problem. Do not use real sensitive data in a report.

## Change a scenario

Keep the vulnerable mode reproducible and the protected mode usable for legitimate requests. A change should identify its control ID, the affected API/tool/UI path, prerequisites and observable effects. Test changes to state through records or files rather than trusting generated text. Preserve authentication and network boundaries unrelated to the exercise.

Update both walkthroughs when payloads, status codes, UI labels, reset behavior or model requirements change. Use the same payload and expected effects in both languages. Add a migration for schema changes; do not rewrite applied revisions.

## Validate a change

Use Python 3.13 and a disposable test environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

Default tests use temporary SQLite/Chroma state. `VULNLM_TEST_DATABASE_URL` selects a database that tests **delete and reseed**; never point it at a working lab. Live-model tests are opt-in and do not provide a model-security pass/fail guarantee. See [validation](docs/validation.md) for PostgreSQL, probes and evidence interpretation.

For frontend polling and session behavior, use Node.js 20+ without Docker or a model server:

```bash
node --experimental-vm-modules --test tests/frontend_polling.test.mjs
```

## Continuous integration

[GitHub Actions CI](.github/workflows/ci.yml) runs on pushes and pull requests and supports manual dispatch. It checks installer/Compose configuration, the SQLite suite including Chromium, and a separate PostgreSQL suite. Live-model tests are disabled in CI; no Ollama or API key is required. JUnit reports are retained as artifacts even on failure. The README badge reflects this workflow’s actual status.

## Submit a change

Keep the change focused. Describe the trigger, resulting behavior, validation performed and any untested environment. Avoid claims such as “secure” or “enterprise-ready” based only on unit tests. Code and documentation are distributed under the existing [BSD 3-Clause license](LICENSE); keep its notices.
