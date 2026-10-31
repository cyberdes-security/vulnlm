# Installation and configuration

English · [Türkçe](installation.tr.md) · [README](../README.md) · [Walkthrough](walkthrough.md)

**You do not need Ollama, a downloaded model, Python or PostgreSQL installed on your computer.** The default setup runs these dependencies in Docker and downloads `qwen2.5:3b` automatically. No API key is required. Using the host computer’s Ollama is an optional acceleration path.

## 1. Prepare the requirements

| Requirement | Details |
|---|---|
| Docker | [Docker Desktop](https://docs.docker.com/desktop/) on macOS/Windows; [Docker Engine](https://docs.docker.com/engine/install/) + the [Compose plugin](https://docs.docker.com/compose/install/) or Desktop on Linux. The Docker engine must be running. |
| Operating system | macOS, Linux, or a Windows WSL2 terminal with Docker Desktop WSL integration. Select Linux containers on Windows. The Bash script is not a native PowerShell script. |
| Memory | Give Docker approximately 8 GB available RAM at minimum; 10–12 GB is recommended for a comfortable start. Ollama has no fixed container memory cap; account for Docker’s available memory, other services and model runtime overhead. Larger models require more memory. |
| Disk | The default model is about 1.9 GB, plus images, build cache and lab data. Plan around 15 GB free for an initial setup; this is a planning allowance, not a guaranteed download size. |
| Internet | Needed for initial image/model downloads. A GPU is optional; the installer selects verified NVIDIA Docker access on Linux/WSL2, otherwise CPU. |

Open Docker Desktop and wait until its engine is ready. On Linux start the Docker service and make sure your account can access it:

```bash
docker info
docker compose version
```

## 2. Open the project directory

Clone the repository or extract its complete ZIP. In your terminal, enter the **vulnlm** directory containing `docker-compose.yml`, `.env.example`, `backend/`, `frontend/` and `scripts/`. Do not run from `backend/`.

```bash
cd /path/to/vulnlm
```

Replace that path with your actual directory. On Windows use your WSL2 terminal and a project directory accessible from that terminal.

## 3. Automatic installation — recommended

```bash
bash scripts/install.sh
```

The script checks Docker/Compose and configuration, creates `.env` from `.env.example` if missing, builds images and starts services. It waits for the database, document index and active model, then prints the UI/setup URLs with the **actual port**. It does not look for a host Ollama: a fresh setup uses bundled Docker Ollama. Existing `.env`, lab data and downloaded models are preserved; the installer never resets data or removes volumes.

Check prerequisites without changing files or services:

```bash
bash scripts/install.sh --check
```

Startup waits up to 30 minutes by default. For a slow connection:

```bash
bash scripts/install.sh --timeout 3600
```

Initial image/model downloads can take several minutes or longer. The app may be waiting and its web page may not exist yet: follow the installer’s terminal output. If it times out, inspect logs and rerun; existing downloads/data are kept. The script does not install Docker or change OS permissions automatically.

## Automatic GPU selection

`bash scripts/install.sh` checks the operating system and NVIDIA availability. When a candidate is found, it runs `nvidia-smi -L` in a temporary Docker container without network or lab-volume access. Only a successful probe grants GPU access to **Ollama**; the app and its tools receive no GPU devices.

| Environment | Automatic selection |
|---|---|
| Linux + NVIDIA | GPU when the driver and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) are configured for Docker. |
| Windows / WSL2 + NVIDIA | GPU when [Docker Desktop WSL2 GPU support](https://docs.docker.com/desktop/features/gpu/) and a current NVIDIA driver are ready. Run the installer in WSL2. |
| NVIDIA present, Docker probe fails | Prints the reason and continues on CPU. Does not install drivers/Toolkit or restart the Docker service. |
| AMD / Intel or no GPU | This version's automatic GPU support is limited to NVIDIA; uses CPU. |
| macOS | Bundled Docker Ollama uses CPU. Optional host Ollama can use Apple GPU. |
| Host/external Ollama selected | Preserves this preference; that server manages its GPU. No local GPU probe. |

```bash
bash scripts/install.sh --gpu cpu       # Force CPU even when a GPU exists
bash scripts/install.sh --gpu nvidia    # Stop if GPU access cannot be verified
bash scripts/install.sh --gpu auto      # Default: verify, otherwise CPU
```

The selection is saved in Git-ignored `docker-compose.override.yml`, so subsequent normal `docker compose` commands use it too. Rerunning the installer checks hardware again. An existing custom Compose override or `COMPOSE_FILE` selection remains user-managed and disables automatic selection. `--check` is read-only and does not launch a GPU probe. GPU selection does not guarantee the whole model fits VRAM; after a chat response, inspect `PROCESSOR` with `docker compose exec ollama ollama ps` (or `ollama ps` on the host in host mode).

## 4. Verify the first startup

A fresh setup defaults to [http://127.0.0.1:8000](http://127.0.0.1:8000). If `.env` or an environment variable selects another port, use the address printed by the installer.

- **Setup screen:** [http://127.0.0.1:8000/setup](http://127.0.0.1:8000/setup). No sign-in required; shows database/schema, Chroma and active-model availability. It refreshes while not ready and shows an active download’s progress.
- **Readiness API:** `/ready` returns 200 when required dependencies are ready, otherwise 503. It does not run inference or grade model answers.
- **API docs:** `/docs`. **App/DB health:** `/health`. **Scenarios:** `/lab/scenarios`.

On the sign-in screen click **Alice**, then **Log in**. Use **Admin** for settings; all demo accounts are listed below. For a first check ask `Use read_file to read hello.txt` and inspect the evidence for the actual `read_file` result and `Public lab file` content. The first inference can take longer on CPU.

## What if Ollama or the model is missing?

| Situation | Behavior |
|---|---|
| No host Ollama installed | Default setup works: Compose starts a separate Ollama container. |
| Default model missing in Docker | `model-init` downloads it automatically; the app waits for completion. |
| Model already downloaded | The cached model volume is reused without downloading it again at startup. |
| Existing `.env` explicitly selects host Ollama | This choice is preserved. The host server must be reachable; the gateway queues the missing active model and configured image model one at a time. The app retries an initially unreachable host. |
| No internet / failed download / full disk | Setup does not claim success. Inspect logs, fix the issue and rerun. Failed/cancelled gateway downloads can be restarted through Admin → Manage LLM models after fixing connectivity. |

**Bundled Ollama (default):** keep `OLLAMA_URL=` empty in `.env`. A host installation is never selected automatically.

**Host Ollama (optional):** set `OLLAMA_URL=http://host.docker.internal:11434` for a running host Ollama, then rerun the installer. If unreachable, start the host service; clear the value and rerun to return to bundled Ollama. The unused bundled model download is skipped in host mode. Shell/Python tools still run in the app container even when inference uses host Ollama.

Host Ollama binds `127.0.0.1:11434` by default. Especially on Linux, container access also requires a suitable listen address and host firewall configuration; follow the platform steps in the [Ollama FAQ](https://docs.ollama.com/faq#how-do-i-configure-ollama-server). Set `OLLAMA_HOST` to a reachable bind address and restrict access to Docker connections. Do not expose its unauthenticated API to the internet. The project’s `OLLAMA_URL` selects a client destination; it does not reconfigure the host service.

## Change the port, reopen or stop

If 8000 is occupied, change `.env` from `LAB_PORT=8000` to e.g. `LAB_PORT=18000` and rerun. Open `http://127.0.0.1:18000`. The installer never overwrites an existing `.env`; exported environment variables can override its values.

```bash
# Subsequent startup; keeps data and models.
bash scripts/install.sh

# Status and diagnostics
docker compose ps --all
docker compose logs --tail 80 model-init model-gateway ollama app

# Stop without deleting data
docker compose stop
```

Do not use `down -v` for routine shutdown: `-v` removes model/lab volumes. See [operations](operations.md) for backups and schema upgrades before updating.

## Manual alternative

You can run Compose directly. **Skip the first command** if `.env` already exists:

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f model-init model-gateway app
```

`Ctrl+C` exits the log viewer without stopping services. Check `/setup` afterwards. Choose other models from **Advanced settings → Manage LLM models** (see [LLM model selection](#llm-model-selection)).

## Synthetic accounts

| Account | Email | Password | Initial role |
|---|---|---|---|
| Alice | `alice@lab.local` | `alice-lab` | user |
| Bob | `bob@lab.local` | `bob-lab` | user |
| Admin | `admin@lab.local` | `admin-lab` | admin |

Each account starts with 1,000 synthetic credits. The login form includes shortcuts for the demo accounts. The API login response returns a bearer token; browser login additionally sets a session cookie. Passwords are stored in plaintext as a lab vulnerability; this setup is not for real identity management.

## Advanced settings

Sign in with the **Admin** demo account and open **Advanced settings** in the header. Each scenario has an independent switch, grouped by LLM, agent, application, and trust boundary risks. The panel also includes controls for the arbitrary SQL tool and debug configuration output. A scenario card’s **Configure** button opens its setting directly.

- **On:** enables the intentionally vulnerable behavior.
- **Off:** applies the protection described beside the switch. The tool or workflow remains available.

Save changes to apply them lab-wide to new requests. Settings persist in `DATA_DIR/private/scenario-settings.json` across restarts and lab data resets. All vulnerabilities are enabled initially. Other demo users can inspect settings but cannot change them. Settings management requires a current Admin cookie session; the unsigned-JWT exercise does not grant this access.

Protected MCP tools remain discoverable and callable. Tool edits invalidate approval, calls must match the approved revision, and approved default arguments cannot be replaced. Privileged model actions are presented for explicit **Approve and execute** confirmation in the evidence panel.

Protected tools keep a defined scope: shell commands use an argument list and a supported command set; Python accepts calculations, output, `math`/`json`, and text file operations within the public workspace. Protected SQL uses a read-only, user-scoped snapshot. HTTP accepts public IP destinations or exact URLs configured in `SAFE_HTTP_URLS`; the default public lab resource is `http://internal-service:9000/public`.

Prompt, memory, image, and tool-result controls separate untrusted reference data and enforce permissions and action approval. They do not guarantee model instruction compliance. Settings are training controls within the lab process; they are not a substitute for deployment isolation, particularly while arbitrary execution scenarios are enabled.

The settings footer shows **38 scenarios + 2 additional controls** separately; the SQL tool and debug configuration controls do not add catalogue scenarios. See the [comparison guide](walkthrough.md#comparison-cards) for each switch’s prerequisites, vulnerable/protected outcomes, legitimate use, browser steps and reset requirements.

## Reset system

**Advanced settings → Reset system** returns the lab to its first-start state, for example between experiments. Accounts, roles and balances go back to their starting values (1,000 credits each). Transfers, documents and the RAG index, memories, chat history, approvals, audit records and the tool registry are deleted. Flags, canaries and the JWT signing key are regenerated, and every session and token is invalidated, the Admin's included. Files that experiments left in the lab data directory, such as shell or Python output, are deleted. The confirmation dialog can also restore the vulnerability settings and model selection to their defaults; it is ticked by default. Downloaded models are kept. Only the Admin demo account can reset the lab, and the reset cannot be undone.

## LLM model selection

Open **Advanced settings → Manage LLM models**. The dialog lists each catalogue model with a description, size, capabilities, and whether it is downloaded. Choosing a downloaded model switches the lab at once. Choosing a model that is not downloaded starts the download: the main screen shows its progress and the current model, and the lab switches over when the download completes. If the download fails or is cancelled, the current model stays in use. Only the Admin demo account can change the model; other users see the list read-only.

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:3b` (default) | 1.9 GB | Fast; runs on CPU or installer-verified NVIDIA GPU |
| `qwen2.5:7b-instruct` | 4.7 GB | More consistent tool calls and JSON |
| `qwen2.5:14b-instruct` | 9.0 GB | Larger Qwen2.5 model; needs about 11 GB of memory |
| `qwen3:8b` | 5.2 GB | Thinking mode can be switched on |
| `qwen3:14b` | 9.3 GB | Thinking mode; needs about 11 GB of memory |
| `qwen3-vl:4b-instruct` | 3.3 GB | Accepts images; tool calling; requires Ollama ≥ 0.12.7 |
| `qwen3.8:27b` | 17.7 GB | Accepts images; thinking mode; needs about 22 GB of memory and a recent Ollama such as the bundled 0.35.1 |

Models that support thinking have a **Thinking mode** switch in the dialog. It is off by default, so requests carry `reasoning_effort: none` and thinking is explicitly disabled for comparisons. When it is on, the model reasons before answering, the request gets a larger token budget, and the reasoning appears in the evidence panel. Protected modes redact the private context and SSNs from the reasoning just as they do from the answer.

The selection applies lab-wide to new model requests and is stored in `DATA_DIR/private/model-settings.json`. Restarts and CLI data resets preserve it. The UI system reset restores it to default when its settings checkbox is selected. `LLM_MODEL` remains the default and is downloaded at startup when the configured Ollama does not have it. Image chat uses `VISION_MODEL` when it is set; otherwise it uses the active model when that model accepts images. The catalogue lives in `backend/model_catalog.json`.

Models come from the Ollama behind the model gateway. By default this is the lab's own Ollama container (Ollama 0.35.1), without a project-defined container memory cap; the installer can enable verified NVIDIA GPU access on Linux/WSL2. Model fit also depends on available RAM/VRAM. To use the host's Ollama, with its GPU and the models already installed there, set `OLLAMA_URL=http://host.docker.internal:11434` in `.env` and recreate the stack. The models must then fit the host's memory.



Version references: [Qwen3-VL model page](https://ollama.com/library/qwen3-vl:4b-instruct) and [Qwen3.8 model page](https://ollama.com/library/qwen3.8:27b), checked 2026-10-29. Qwen3-VL specifies Ollama 0.12.7 or newer. Installation/download status alone does not verify runtime memory or model compatibility; validate a real chat/image request.

## Image model and UI

Attach a PNG/JPEG using 📎 to call `/chat/image`; text documents still go to RAG. Images are limited to 1 MB decoded (the proxy's 2 MiB body cap still applies). The simplest setup is to select an image-capable model such as `qwen3-vl:4b-instruct` in **Advanced settings → Manage LLM models**; it then answers both text and image chat. To keep a separate text model, set `VISION_MODEL` in `.env` to an image-capable Ollama model instead; `model-init` pulls it together with `LLM_MODEL`. Pull it and recreate the app:

```bash
bash scripts/install.sh
```

The model must support the chat API's `image_url` input, and tool calls or the lab JSON fallback for action-based experiments. Check available RAM/VRAM and Docker memory allocation for the selected model; the project does not cap Ollama memory. With neither `VISION_MODEL` nor an image-capable active model, `/chat/image` returns 503. Image bytes are retained in the intentionally exposed raw audit; saved conversation history keeps only text and an omission marker, so reattach images when needed. PDF/OCR is not implemented.

Swagger documents the API endpoints, and the UI lists the scenario catalogue. Startup initializes the required tables and preserves lab data. A full reset clears approvals, agent messages, and HTTP fixtures along with other lab records. After editing backend code, rebuild the app with `docker compose up --build -d app`.


## Native development

The shell tools carry the host user's privileges in a native process. Prefer native runs only in a disposable VM or a controlled test environment. The code tests use their own temporary files.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export DATABASE_URL=
export MODEL_GATEWAY_URL=
export DATA_DIR="$(mktemp -d /tmp/vulnlm-native.XXXXXX)"
export LLM_API_URL=http://127.0.0.1:11434/v1/chat/completions
export LLM_MODEL=qwen2.5:3b
cd backend
python seed_data.py
uvicorn main:app --host 127.0.0.1 --port 8000 --no-access-log
```

If `DATABASE_URL` is empty, SQLite is used. You must separately prepare Ollama and the model in a native setup. `CHROMA_ENABLED=False` is only for non-RAG development; it does not present the RAG routes as a working scenario.
