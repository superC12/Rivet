# Rivet

Rivet is a lightweight, self-hosted control layer for AI compute. It gives you one assistant interface and decides whether each request should run on a local model, a remote machine, or a configured cloud provider.

## Install on Ubuntu Server

Rivet supports a one-line install on Ubuntu 24.04 LTS:

```bash
curl -fsSL https://raw.githubusercontent.com/superC12/Rivet/main/install.sh | sudo bash
```

The GitHub owner in this command is filled in when the repository is published. Until then, install from a cloned or copied checkout:

```bash
sudo ./install.sh --local
```

The installer:

- creates a locked-down `rivet` system user;
- installs Rivet beneath `/opt/rivet` in a dedicated virtual environment;
- keeps configuration in `/etc/rivet`;
- keeps conversations in `/var/lib/rivet`;
- installs and starts `rivet.service` through systemd;
- binds to `127.0.0.1:8080` by default;
- verifies `/health` and rolls back a failed update.

Python 3.12 or newer is required. Ubuntu 24.04 LTS includes a compatible Python version. For older Ubuntu releases, use Docker or provide Python 3.12 separately.

### Manage the service

```bash
rivet status
rivet doctor
rivet logs
rivet restart
rivet update
```

Normal removal preserves your assistant configuration and conversations:

```bash
sudo rivet uninstall
```

Permanent removal requires an explicit purge:

```bash
sudo rivet uninstall --purge
```

Edit `/etc/rivet/rivet.env` for the bind address, port, GitHub repository, and API keys. Edit `/etc/rivet/assistant.yaml` and `/etc/rivet/rivet.yaml` for identity and infrastructure. Restart Rivet after manual changes.

The platform name, assistant identity, infrastructure, and secrets are deliberately separate:

- `config/assistant.yaml` holds the portable assistant name, behavior, and appearance.
- `config/rivet.yaml` holds routing, providers, nodes, and actions.

Both are generated on first start from the `config/*.yaml.example` templates and are **not** tracked in git. Rivet rewrites them whenever settings are saved, so editing the tracked templates by accident — by finishing onboarding on a development machine, say — would change the defaults every new installation receives. Edit the live files to configure your instance; edit the templates only to change what a fresh install starts with.
- `.env` holds secrets and is never returned by the API.
- `data/rivet.db` holds conversations and execution metadata.

## Developer setup

Python 3.12 or newer is recommended.

```powershell
cd rivet
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. Rivet checks the default Ollama endpoint at `http://127.0.0.1:11434` during onboarding.

For OpenRouter, copy `.env.example` to `.env`, set `OPENROUTER_API_KEY`, and load the file into your process environment before starting Rivet. Secrets are intentionally not editable through the browser.

## How routing works

Routing is two separate decisions, kept apart on purpose.

**Classification** answers *what kind of request is this* and produces a lane:

| Lane | Meaning |
| --- | --- |
| `ACTION` | An instruction that should change something in the world |
| `LOCAL` | A small model can answer this well |
| `ESCALATE` | This needs a stronger model |

**Selection** answers *which machine runs it* and produces a route — `LOCAL`, `REMOTE`, `CLOUD`, or `ACTION` — plus the provider, model, and node. Selection is pure and synchronous, so it can be tested against a fixed model list with no classifier and no network involved.

```
request
   ↓
classifier ──► lane            (backend/routing/classifier.py)
   ↓
policy     ──► allowed tiers   (backend/routing/policies.py)
   ↓
router     ──► provider+model  (backend/routing/builtin.py)
```

Three rules are load-bearing:

**ACTION is never model-decided.** A request reaching the ACTION lane can cause a real side effect, so it is gated on deterministic patterns only, and a question about an action ("how do I create a task?") is never an action. A misfiring classifier should cost a wasted token, not an email nobody meant to send.

**Unreadable classification fails upward.** If the classifier is unreachable or returns something unparseable, the lane defaults to `ESCALATE` rather than quietly landing on the cheap option — an unclassified request answered by a 3B model is a confidently wrong answer, while the same request answered by a stronger model is a slightly larger bill. Set `router.classifier.fallback_lane: LOCAL` to invert that trade.

**`privacy_mode: local_only` is a guarantee, not a preference.** Nothing routes around it — not a manual model override, not session affinity, not failing upward, not an external routing engine. It blocks *cloud* providers, not remote nodes: a machine you own, reached over Tailscale, keeps content inside your own estate. The per-request `Local only` mode is the stricter one that pins execution to the local machine.

Both constraints hold on the **failure path** too. When the chosen model dies mid-answer, the fallback is validated against the same allowed tiers as the original choice, so a `Local only` request cannot quietly reach the cloud while recovering. If no permitted fallback exists, Rivet says the model stopped responding rather than answering from somewhere you excluded.

### Choosing a classifier

`heuristic` (the default) is deterministic pattern matching. It needs nothing installed and costs nothing.

`dispatch` asks a small local model instead. The dispatcher is built in — Rivet ships the model recipe, runs the classifier in its own process, and needs no separate routing service. Build the model on whichever machine runs Ollama for it:

```bash
ollama create administrator-selected-classifier -f administrator-provided model recipe
```

Then turn it on and measure it before trusting it:

```yaml
router:
  classifier:
    mode: dispatch
    endpoint: http://127.0.0.1:11434
    model: administrator-selected-classifier
```

The dispatcher is the same weights as the local brain, pinned to an 8K context at zero temperature. Classification never needs a large context — that was the tool-calling requirement, and this model does not call tools.

### Pointing the dispatcher elsewhere

The classifier usually runs on the always-on server rather than wherever the config file was last edited, so every value can be overridden by the environment. `RIVET_`-prefixed names win; the unprefixed spellings are accepted too.

| Variable | Overrides | Default |
| --- | --- | --- |
| `RIVET_CLASSIFIER_MODE` / `CLASSIFIER_MODE` | `mode` | `heuristic` |
| `RIVET_DISPATCH_ENDPOINT` / `OLLAMA_URL` | `endpoint` | `http://127.0.0.1:11434` |
| `RIVET_DISPATCH_MODEL` / `DISPATCH_MODEL` | `model` | `administrator-selected-classifier` |
| `RIVET_DISPATCH_TIMEOUT_S` / `DISPATCH_TIMEOUT_S` | `timeout_s` | `5.0` |
| `RIVET_FALLBACK_LANE` / `FALLBACK_LANE` | `fallback_lane` | `ESCALATE` |

### Checking the classifier

`GET /api/classifier` reports the configuration and probes the dispatcher for real. It separates the two failures that look identical from inside a request:

```json
{ "status": "model_missing", "model_installed": false,
  "error": "administrator-selected-classifier is not installed. Create it with: ollama create administrator-selected-classifier -f administrator-provided model recipe" }
```

That distinction matters because a broken dispatcher never fails loudly. Every request simply fails upward to `ESCALATE` and gets answered by a larger model, so the first symptom is the bill. `/api/status` carries the same block, and marks the router `degraded` when the classifier is not healthy.

### Asking where a request would go

`POST /api/classify` returns the lane without running anything — it picks no provider, wakes no node, runs no action, and stores nothing:

```bash
curl -s localhost:8080/api/classify -H 'content-type: application/json' \
  -d '{"text":"why is my docker container exiting with 137"}'
```

```json
{"lane": "ESCALATE", "confident": true, "source": "heuristic",
 "reason": "Infrastructure specifics are easy to invent",
 "latency_ms": 0, "allowed_tiers": ["REMOTE", "CLOUD", "LOCAL"]}
```

`allowed_tiers` is what the lane may actually use under the current policy and the requested `mode`, which the lane alone does not tell you. An `ACTION` lane returns none, because actions go to the gateway rather than to a model.

## Measure before you wire

```bash
python eval/run_eval.py                  # the built-in heuristic
python eval/run_eval.py --mode dispatch  # a small local model
```

This is the gate. An endpoint that returns a label is not evidence the label is right, and `LOCAL` vs `ESCALATE` asks a model to assess its own competence — the thing small models are worst at.

Read the numbers in this order:

1. **ACTION precision** — of the requests that would have gone to n8n, how many were really instructions? First, because it is the only metric whose failure has a side effect in the world.
2. **ACTION recall** — of the real instructions, how many did we catch? A miss here is merely annoying.
3. **ESCALATE recall** — a miss is a confidently wrong answer delivered to you.
4. **LOCAL precision** — the cost side, the OpenRouter bill.

The heuristic scores 100% on the bundled cases, but its patterns were tuned against them, so that number means *the suite passes*, not *100% accurate on your traffic*. The real job of `eval/cases.jsonl` is regression detection: it tells you what a prompt or pattern change broke. Add cases from your own use — especially ones Rivet got wrong — and the score starts to mean something. `--mode dispatch` is the honest comparison, since that model has never seen these cases.

Every metric is gated, so the command exits non-zero on any regression rather than only on catastrophic ones. The defaults are floors, not targets; tighten them for your deployment:

```bash
python eval/run_eval.py --min-escalate-recall 0.95 --min-accuracy 0.95
```

`--min-action-precision` defaults to `1.00` and has no slack, because a false ACTION has a side effect in the world.

## Add a remote Ollama node

Add a provider and node to `config/rivet.yaml`. A Tailscale hostname or IP works as the provider endpoint:

```yaml
providers:
  desktop-ollama:
    type: ollama
    node: gaming-pc
    endpoint: http://gaming-pc:11434

nodes:
  gaming-pc:
    type: tailscale
    display_name: Gaming PC
    hostname: gaming-pc
    always_on: false
    wake_on_lan:
      enabled: true
      mac: "AA:BB:CC:DD:EE:FF"
      broadcast: "192.168.1.255"
```

Node **type** drives routing, not node name: `type: local` is the `LOCAL` tier, anything else is `REMOTE`. Renaming a node never silently reclassifies your routes.

Wake-on-LAN only accepts targets explicitly present in this file. Rivet does not expose arbitrary shell execution.

## Actions (n8n)

Off by default. Enable it in Settings → Connections, or in `config/rivet.yaml`:

```yaml
actions:
  n8n:
    enabled: true
    endpoint: "https://n8n.example/webhook/rivet"
    timeout_s: 30
```

Set `N8N_ACTION_KEY` in `.env` to have Rivet sign requests with an `X-Rivet-Key` header. The webhook URL carries its own authorisation, so it is treated as a credential: stored server-side, never returned through the API.

**Rivet reports an action as done only when n8n confirms it.** To confirm, the workflow must end in a **Respond to Webhook** node returning a body Rivet recognises:

```json
{ "status": "success", "message": "Task created." }
```

`{"success": true}`, `{"result": "ok"}` and similar all work, and a workflow that reports failure is reported as a failure.

A webhook set to *respond immediately* returns 200 **before** the workflow runs. That is a receipt, not a confirmation, so Rivet reports it as `unconfirmed` — the user is told the request was delivered but could not be verified. This is deliberate: a 200 that means nothing is the most common way an automation chain lies to the person using it.

| Status | What the user is told |
| --- | --- |
| `executed` | The gateway's own message, e.g. "Task created." |
| `failed` | "I couldn't complete that action." |
| `unconfirmed` | "I sent that to your action gateway, but it didn't confirm whether it ran." |
| `unreachable` | "I couldn't reach your action gateway, so nothing was run." |
| `rejected` | "Your action gateway refused the request, so nothing was run." |
| `not_configured` | Points at Settings → Connections. |

## Docker

```powershell
docker compose up --build
```

The Compose file binds Rivet to `127.0.0.1:8080`, persists `config` and `data`, and contains only the Rivet service. If Ollama runs on the Docker host, change its configured endpoint to `http://host.docker.internal:11434`.

## Releases

CI runs on pushes and pull requests. Pushing a version tag such as `v1.0.0` runs the full test suite, creates `rivet.tar.gz` with a SHA-256 checksum, and publishes both files as a GitHub Release. The one-line installer prefers that signed-by-GitHub release path and falls back to the `main` branch before the first release exists.

## Safe network access

Rivet binds to localhost by default. For access from other devices, prefer Tailscale. If you use a reverse proxy, add authentication and TLS; do not publish an unauthenticated Rivet instance directly to the internet.

## API

Core endpoints include `/health`, `/api/status`, `/api/models`, `/api/providers`, `/api/nodes`, `/api/routes`, `/api/conversations`, `/api/chat`, `/api/settings`, `/api/onboarding`, and `POST /api/nodes/{node}/wake`. An unknown `/api/...` path returns a JSON 404 rather than the frontend.

Chat responses use Server-Sent Events over a streaming `POST` request. Every SSE payload is JSON-encoded, including plain token strings — a raw string containing a newline would otherwise split into a line with no `data:` prefix, which the browser drops, silently eating blank lines and code blocks.

Reachability probes and model discovery are cached briefly, so an asleep node costs one connection timeout rather than one per request.

## Test

```powershell
pip install -r requirements-dev.txt
pytest
```

Rivet logs route metadata and failures, but not full prompts or secrets. The UI escapes model output before applying its small safe Markdown subset; arbitrary HTML is never rendered.
