# Validation

English · [Türkçe](validation.tr.md) · [README](../README.md)

Run commands from `vulnlm/` with Python 3.13 and `requirements-dev.txt` installed. Tests and live experiments answer different questions: application tests verify boundaries and effects; live experiments measure behavior of a particular model.

## Application and documentation tests

```bash
python -m pytest -q
python -m pytest tests/test_documentation.py -q
```

The default suite uses a temporary SQLite database, real Chroma, temporary files and local HTTP servers. Scripted model replies exercise the real context/dispatcher and mutations without measuring live-model compliance. Documentation tests compile Python/shell examples, check local links and API paths, and execute the direct walkthrough snippets against temporary lab state. The TR/EN versions of those snippets must have identical Python semantics.

| Area | Tests |
|---|---|
| Baseline endpoints and effects | `tests/test_lab.py`, `tests/test_extensions.py` |
| Protected modes and legitimate operations | `tests/test_scenario_controls.py` |
| Agent receipts and dependent tool calls | `tests/test_agent_execution.py` |
| Sub-agent grants, handoff, recursion and context | `tests/test_subagents.py` |
| Cross-agent covert channel (deterministic model) | `tests/test_covert_channel.py` |
| Migration, provenance, readiness and log privacy | `tests/test_operations.py` |
| Model gateway, selection, downloads and retries | `tests/test_llm_models.py` |
| Complete UI reset | `tests/test_system_reset.py` |
| Installer decisions and failures | `tests/test_installer.py` |
| Published examples, translations and links | `tests/test_documentation.py` |

## PostgreSQL

```bash
VULNLM_TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/TEST_DB python -m pytest -q
```

Use a dedicated disposable database: tests drop/reseed its tables. Do not run a lab or another suite against it concurrently. The test setup uses `NullPool` to avoid sharing asyncpg connections across event loops. This is a separate database-backend check, not a substitute for browser tests.

## Browser tests

```bash
python -m playwright install --with-deps chromium
RUN_BROWSER_TESTS=1 python -m pytest tests/test_browser.py -q
```

Real Chromium checks XSS, same-site cross-origin CSRF, image attachments, settings/model/trust/reset dialogs, startup diagnostics and README's document comparison in both languages. It uses controlled model output when a specific response is needed. This verifies browser behavior, not a live model's willingness to generate an XSS payload. Set `CHROME_EXECUTABLE` to use an installed Chrome executable. Without `RUN_BROWSER_TESTS=1`, these checks are skipped.

## Live-model tests

Prepare an installed model and a model endpoint reachable **from the Python test process**:

```bash
LLM_API_URL=http://127.0.0.1:11434/v1/chat/completions \
LLM_MODEL=qwen2.5:3b RUN_MODEL_TESTS=1 python -m pytest tests/test_model.py -q
```

The default Compose Ollama/gateway does not publish host ports. The command above requires a separately reachable host Ollama; setting `.env` for Compose does not expose the bundled service. Configure `VISION_MODEL` for the optional image test. The tests' application data remains temporary. An observed attack passes; an unobserved attack is skipped with a reason; integration errors fail. A skipped attack is not a security pass.

### Experiments against a running lab

These scripts use the published app address and modify its documents, memory and chat history. Start from a disposable experiment lab with the switches described in the walkthrough. Match the port to `LAB_PORT`:

```bash
export VULNLM_URL=http://127.0.0.1:8000
python scripts/model_probe.py --url "$VULNLM_URL" --output model-probe-results.json
```

Without `--prompt-canary-file`, the hidden-context experiment reports `UNVERIFIED_NO_ORACLE`. To provide the independent operator-held oracle in Docker:

```bash
mkdir -p test-results
docker compose cp app:/data/private/prompt.txt test-results/prompt-canary.txt
python scripts/model_probe.py --url "$VULNLM_URL" \
  --prompt-canary-file test-results/prompt-canary.txt --output model-probe-results.json
```

The expected value is not sent in the user prompt. Obtain a fresh file after every reset. Keep experiment artifacts out of version control; they can contain prompts and synthetic secrets.

For HTTP-result, agent-sender and optional image experiments, use the [extended walkthrough](extended-scenarios.md). The app-reachable tool address in Compose is `http://app:8000`, independent of the published host port.

The model matrix selects and, when needed, downloads **every catalogue model**, including large ones. It mutates its target lab and temporarily changes the lab-wide model; do not run it alongside another experiment:

```bash
python scripts/model_matrix.py --url "$VULNLM_URL" --output model-matrix.json
```

On exit it requests the previous selection again; verify the active model after a failed/interrupted run. Record failures and resource limits rather than treating every catalogue entry as validated on your machine.

### Isolated real tool execution

`tool_call_probe.py` starts an isolated app with temporary SQLite/Chroma/files and records actual upstream replies. It checks all 12 tools against output or independent state changes. Repeated tool proposals within a chat request must reuse a receipt; the chained example must read once and save the exact read value once.

With the Docker lab running, this command uses its gateway but replaces the lab-data volume with a disposable anonymous volume. It does not need host Python or a published Ollama port:

```bash
mkdir -p test-results
docker compose run --rm --no-deps -T \
  --volume /data --volume "$PWD:/workspace:ro" \
  --volume "$PWD/test-results:/results" --workdir /workspace \
  app python scripts/tool_call_probe.py --model qwen2.5:3b \
  --chain-runs 5 --output /results/tool-calls.json
```

The image must be built and the requested model installed on the configured Ollama. To run only the chained example, add `--chain-only`. This probe still makes real model requests and consumes its resources. It does not change the main app's active-model selection.

## Record and interpret evidence

| Result | Meaning |
|---|---|
| `PASS` / `FAIL` | A deterministic assertion about the documented application flow. |
| `OBSERVED` | An attack effect with independent record, file, context or browser evidence. |
| `NOT_OBSERVED` | The requested effect was not observed in this run; not a proof of protection. |
| `UNVERIFIED_NO_ORACLE` | The independent reference needed to assess disclosure was absent. |
| `ERROR` | A provider, transport or integration error; not model resistance. |
| `SKIPPED` | A test did not establish its assertion; read the reported reason. |

Save commit/revision, OS, Docker/Compose/Ollama versions, image/model digests, switch settings, initial data, payload, request ID, tool trace and repetition count. An HTTP 200 or a flag-shaped string alone does not prove an exploit. A failed model response can follow a committed tool effect; check both. Hash embeddings test retrieval boundaries, not semantic quality. Do not infer a success rate from one run.

Installer tests simulate Linux/WSL2/macOS, NVIDIA probes, CPU fallback and host/custom Compose preferences using a fake CLI. They do not establish real GPU inference. Hardware and model-version compatibility need a real request on the target system.
