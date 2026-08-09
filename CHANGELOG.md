# Changelog

All notable changes to Rivet are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0.0, minor versions may change internal interfaces.

## [Unreleased]

### Changed

- Rivet no longer ships a classifier Modelfile or names any model as a
  default. Dispatch mode now requires an administrator-selected model and
  reports an explicit unconfigured state when none is supplied.

### Fixed

- An explicitly configured classifier remains available to benchmarks but is
  excluded from assistant routing, preventing a label-only model from being
  selected for chat.
- Long conversations scroll inside the canvas instead of growing the page and
  pushing the composer below the viewport.

## [1.2.0] - 2026-08-09

### Added

- Models can be reordered by drag and drop during onboarding and later in
  Settings → Routing. The saved provider-qualified order controls selection
  priority within each routing tier; Alt+Arrow keys provide the same control
  from the keyboard.
- About now contains a subtle, non-destructive path back through onboarding;
  the setup journey can be revisited without changing the active instance.

### Fixed

- Frontend assets are now served with a strict no-store policy so an upgrade
  cannot combine new HTML with stale JavaScript from a browser or proxy cache.

## [1.1.1] - 2026-08-09

### Added

- Onboarding model rows are now direct include/exclude controls with clear
  enabled, muted, and crossed-out states. Choices survive back navigation and
  can be changed later in Settings → Routing.

### Changed

- Benchmark editing now uses compact disclosures for execution targets,
  prompt rules, and test cases instead of presenting every control at once.
- Evaluation cases use readable stacked cards when expanded, with a live case
  count and a smaller suite identity treatment that matches the rest of the
  settings interface.

### Fixed

- Benchmark controls no longer overlap or force horizontal scrolling inside
  the narrower settings pane.
- The general Settings save footer is hidden while editing benchmarks, leaving
  only the relevant Delete, Save, and Run actions visible.
- Model choices made during onboarding now persist as provider-qualified
  routing exclusions and are enforced by automatic routing, manual model
  selection, and the composer route menu.

## [1.1.0] - 2026-08-09

### Added

- Benchmark Studio in Settings, with editable Speed & Footprint and Judgment &
  Limits starter suites, custom suites, automatic Ollama model targets,
  streamed progress, grading, and persistent run history.
- A single explained “New benchmark” workflow plus an Advanced visibility
  control that can restore the starters without duplicating or deleting custom
  suites.
- Ollama auto-detection now checks bounded administrator and Docker candidates
  after the configured endpoint, without scanning the local network or
  redirecting explicitly created manual connections.

### Changed

- Instance branding now follows the assistant name selected during onboarding
  and remains separate from Rivet's project identity in About.

### Fixed

- Fresh or reset onboarding now begins with neutral “Your assistant” branding
  everywhere, including the browser tab, and a blank name field instead of
  inheriting or suggesting an identity.
- Stopped benchmark streams are recorded as cancelled and cannot overlap a
  second run while shutdown is still settling.
- Benchmark lists now pair the latest timestamp with the status and summary
  from that same run rather than an indeterminate grouped database row.
- The new-benchmark form now obeys its hidden state, and benchmark editors no
  longer force horizontal scrolling at compact dashboard widths.

## [1.0.1] - 2026-08-09

### Added

- Manual connections can now be removed from Connections; Rivet also cleans up
  the unused node created for that connection.

### Changed

- Provider diagnostics now expose node type so remote and Tailscale compute is
  labelled and selected independently from local-only routes.
- Provider health checks share a cache whose online and offline lifetimes both
  outlast the dashboard poll, reducing repeated probes of sleeping hardware.
- Atmospheric rendering now receives accent changes through an explicit event
  and keeps effective opacity within the 8–18% interface range.

### Fixed

- Adaptive accent changes are no longer pinned to the initial amber value, and
  the controller now updates an accessible context status target.
- Eval CLI endpoint and model arguments now take precedence over deployment
  environment variables, so evaluations cannot silently target another host.
- Classifier failures now surface their actionable error in the diagnostics
  popover, including an actionable warning when a configured classifier is missing.
- Classifier health remains cached beyond the dashboard refresh interval,
  avoiding a blocking dispatcher probe on every poll when Ollama is offline.

## [1.0.0] - 2026-08-09

The first stable Rivet release: a self-hosted AI dashboard that can run on an
Ubuntu server or in Docker, discover available compute, and route each request
without hiding where it executed.

### Added

- A live routing and execution dashboard with provider latency, endpoint
  health, HTTP/SSE diagnostics, and an expanded Compute matrix.
- Provider-aware route selection that lists only configured, reachable models
  and lets a user switch execution targets directly from the composer.
- Manual connections for Ollama, OpenAI-compatible APIs, and OpenRouter when
  automatic discovery cannot see a service. Connections may be classified as
  local, remote/Tailscale, or cloud without storing API keys in the browser.
- Contextual developer triggers, delayed control descriptions, conversation
  deletion, streaming cancellation, and visible keyboard shortcuts when a
  compatible route is available.

### Changed

- Reworked the main canvas around a compact control path instead of a generic
  chat-product hero. The detailed execution matrix now lives in Compute.
- Refined the borderless glass interface, structural grid, adaptive ambient
  state lighting, and dynamic task-based accent system.
- The platform mark is configurable: the compact first letter remains anchored
  while the rest of the wordmark expands from it with the conversation sidebar.
- The composer now has a grounded glass surface, a single dynamic accent edge,
  a compact engine selector, and clear ready, executing, and stop states.

### Fixed

- Textarea focus no longer draws an unwanted rectangular selection border.
- Settings panels remain usable at desktop and phone sizes, including long
  Connections forms and provider menus.
- Manual connection setup opens immediately even while automatic provider
  probes are slow or unavailable.
- Connection status now opens real diagnostics rather than acting as a static
  badge, and offline providers never appear as selectable execution targets.

## [0.3.0] - 2026-08-09

The adaptive interface release. Rivet now feels more like a quiet part of the
homelab than a generic cloud chat client, while keeping routing and execution
details available when they are useful.

### Added

- Adaptive composer accents that classify work locally while typing: creative,
  math and science, code and systems, analysis and planning, and actions each
  receive a distinct visual treatment. A fixed accent, presets, a color picker,
  or exact RGB values can be selected in Appearance settings.
- Delayed contextual tooltips for routing, compute, connection, trace, accent,
  and atmosphere controls.
- Conversation deletion directly from the dashboard, with confirmation and a
  tested API path.

### Changed

- Reworked the dashboard into a softer, borderless glass interface with the
  spaced Rivet wordmark, a stronger bottom-flowing atmospheric backdrop, and a
  compact rectangular composer.
- Restored the single-click Static, Ambient, and Dynamic atmosphere control.
  Dynamic motion now responds to routing, generation, completion, errors, and
  the current adaptive accent.
- Simplified the empty state and removed redundant route, execution, and history
  labels.
- Redesigned Settings scrolling and compact navigation so longer panels remain
  usable on desktop and phone-sized screens.

### Fixed

- The Settings footer no longer covers Connections or Appearance fields, moves
  with the scroll area, or loses width to a duplicated sidebar offset.
- Settings dropdowns now use the active light or dark palette and display a
  consistent disclosure arrow.
- RGB accent inputs no longer collapse at narrow viewport widths.

## [0.2.1] - 2026-08-08

A correctness release. Every fix here is a case where a stated guarantee
held on the ordinary path and quietly stopped holding on the failure
path — which is where nobody is looking.

### Upgrading

Live configuration moved out of version control. `config/assistant.yaml`
and `config/rivet.yaml` are now generated on first start from the tracked
`config/*.yaml.example` templates.

Installed instances are unaffected: `/etc/rivet` was never tracked, and
the installer still seeds only files that do not already exist. **If you
run Rivet from a git checkout**, pulling this removes those two files
from your working tree and Rivet regenerates them from the templates on
the next start, so any settings you had committed there revert to
defaults. Copy them aside first if you want to keep them.

### Fixed

- **`Local only` held on the failure path.** A per-request `Local only`
  chat could still reach a cloud provider when the local model failed
  mid-answer: the fallback checked `privacy_mode` but not the request's
  own mode. The one control a user has for "do not send this anywhere"
  now applies to recovery too, which is exactly where its absence was
  invisible. Fallback candidates are validated with
  `RoutingPolicy.allowed_tiers(mode)` against each model's real tier.
- **The Switchyard adapter validated against `auto`**, so an external
  router could return a remote or cloud model for a `Local only` request
  and have it accepted. It is now checked against the request's mode.
- **n8n settings saved from the browser were silently discarded.**
  `SettingsPayload` had no `actions` field, so Pydantic dropped it before
  it reached the config: the Connections panel reported success and
  changed nothing.
- **A fallback answer was spliced onto the abandoned one.** The server
  discarded the failed model's partial text but the browser kept its own
  copy, so the dead fragment stayed glued to the front of the real
  answer. The server now emits a `reset` event before fallback tokens and
  the client clears both its buffer and the rendered output.
- **A fallback on a local node was labelled `REMOTE`**, because the route
  was derived from node presence rather than node type. It now uses
  `tier_of`, consistent with the rest of routing.

### Changed

- `eval/run_eval.py` gates on every metric, not just catastrophic ones.
  Minimum ACTION precision/recall, ESCALATE recall, LOCAL precision and
  accuracy are configurable with `--min-*` flags and a non-zero exit
  follows any breach. A quiet drop in ESCALATE recall is a real
  regression; it just fails as worse answers rather than as an incident.
- Live configuration is no longer tracked. `config/assistant.yaml` and
  `config/rivet.yaml` are generated on first start from the shipped
  `*.example` templates and are gitignored. Rivet rewrites its own config
  whenever settings are saved, so tracking those files meant finishing
  onboarding on a dev machine edited the defaults every new installation
  would receive — which had already happened once.
- Tests run against their own seeded config directory instead of the
  developer's live configuration.

## [0.2.0] - 2026-08-08

The routing release. Classification and model selection became separate,
testable decisions, actions gained a gateway that refuses to overstate
what happened, and the classifier became something you can measure
instead of something you have to trust.

### Fixed

- **Streamed responses no longer lose newlines.** Server-Sent Event
  payloads were written as raw strings, so any token containing a newline
  split into a line with no `data:` prefix, which browsers silently drop.
  Because Ollama streams `\n` as its own chunk, every blank line and code
  block in every response was being mangled. All SSE payloads are now
  JSON-encoded.
- **Upgrades no longer leave a stale interface running.** The frontend was
  served without cache directives, so browsers reused cached JavaScript
  and CSS heuristically and an upgraded Rivet could run last version's
  interface against the new backend until someone hard-reloaded. The
  shell and all static assets now send `Cache-Control: no-cache`, so the
  browser revalidates and pays a 304 instead.
- Node type, not node name, decides the routing tier. A node called
  anything other than `homelab` was previously misclassified as remote,
  so renaming a node silently rerouted traffic.
- `prefer_local` was read from config but never applied.
- Session affinity could keep a conversation on a cloud model after
  privacy or route policy changed to disallow it.
- A manual model override could select a cloud model while
  `privacy_mode: local_only` was set.
- Model candidates are ordered deterministically. Selection previously
  depended on dictionary and network response order, so the same request
  could route differently across restarts.
- Unknown `/api/...` paths return a JSON 404 instead of `index.html`,
  which had been returning HTTP 200 and HTML to callers expecting JSON.
- Partial output is kept when a stream ends early, rather than being
  discarded after the tokens were already paid for.
- A settings payload with a blank assistant name no longer erases the
  assistant's identity.

### Added

- **Classifier subsystem** (`backend/routing/classifier.py`) with two
  interchangeable implementations: a deterministic `heuristic` (default,
  needs nothing installed) and a `dispatch` mode that asks a small local
  model. Configure under `router.classifier`.
- **Eval harness** (`eval/`) scoring the classifier on ACTION precision,
  ACTION recall, ESCALATE recall, LOCAL precision, fallbacks and latency.
  Exits non-zero when it would have fired the action gateway on a
  non-action, so it can gate a commit rather than just inform one.
- **n8n Actions Gateway** (`backend/actions/`), off by default. Rivet
  reports an action as done only when the gateway confirms it; a webhook
  that answers before its workflow runs is reported as `unconfirmed`
  rather than as success.
- Routing policy is now explicit and separately testable
  (`backend/routing/policies.py`), including the distinction between
  `privacy_mode: local_only` (bans cloud providers, allows your own
  remote nodes) and the per-request `Local only` mode (pins execution to
  the local machine).
- Optional external routing engine seam
  (`backend/routing/switchyard_adapter.py`). Off unless
  `router.engine: switchyard` is set, unverified against a live
  Switchyard, and it hands the request back to the built-in router rather
  than inventing a decision.
- "Specific model…" entries in the route selector, so a single model can
  be chosen for one request.
- Prompt and completion token counts are captured from providers that
  report them and stored alongside each message. Absent counts stay
  absent; nothing is estimated.
- Execution telemetry moved into `frontend/js/telemetry.js` and now shows
  action status and node display names.
- The About panel reads the running version from `/api/status` instead of
  hardcoding it.

#### Packaging and distribution

- One-line Ubuntu Server installer with systemd integration.
- Release archive checksum verification and update rollback.
- `rivet` management command for status, diagnostics, logs, restart,
  updates, paths, and removal.
- GitHub Actions workflows for continuous integration and tagged
  releases. Release notes are now taken from this changelog, falling back
  to generated notes when a version has no section.

### Changed

- Classification and selection are now separate stages. Selection is pure
  and synchronous, so it can be tested against a fixed model list with no
  classifier, event loop or network involved.
- An unreadable or unreachable classification **fails upward** to
  `ESCALATE` rather than quietly landing on the cheap option. Set
  `router.classifier.fallback_lane: LOCAL` to invert the trade. This
  reverses the earlier `FALLBACK_LANE=LOCAL` default.
- ACTION is decided by deterministic patterns only and is never
  model-decided, because a misfiring lane can cause a real side effect. A
  question about an action ("how do I create a task?") is never an
  action.
- `RoutingEngine.decide()` is now async, since classification may call a
  model. `RoutingEngine.select()` is the synchronous entry point when a
  `Classification` is already in hand.
- Heuristic accuracy on the bundled eval set went from 75% to 100%, with
  ESCALATE recall going from 35% to 100%. These patterns were tuned
  against those cases, so the score means the suite passes, not that the
  classifier is 100% accurate on real traffic.

### Performance

- Reachability probes and model discovery are cached briefly. A chat
  request against an unreachable provider went from ~2.7s to ~0.25s,
  because an asleep node now costs one connection timeout rather than one
  per request.

### Security

- The n8n webhook URL carries its own authorisation, so it is treated as
  a credential: stored server-side and never returned through the API.
- `N8N_ACTION_KEY` is read from the environment only and is never written
  to config.

## [0.1.0] - 2026-08-08

Initial release.

### Added

- One assistant interface over local, remote and cloud compute, with
  streaming responses and persistent SQLite conversation history.
- Ollama, OpenRouter and generic OpenAI-compatible providers, with model
  discovery.
- Node abstraction with health status, Tailscale-compatible hostnames and
  Wake-on-LAN, restricted to explicitly configured targets.
- Lightweight built-in routing with expandable execution traces and route
  telemetry.
- Assistant identity, infrastructure and secrets kept in separate files:
  `config/assistant.yaml`, `config/rivet.yaml` and `.env`.
- First-run onboarding, collapsible chat history, dark/light themes, and
  Static/Ambient/Dynamic background modes that respect
  `prefers-reduced-motion`.
- Docker support.

[Unreleased]: https://github.com/superC12/Rivet/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/superC12/Rivet/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/superC12/Rivet/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/superC12/Rivet/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/superC12/Rivet/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/superC12/Rivet/releases/tag/v1.0.0
[0.3.0]: https://github.com/superC12/Rivet/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/superC12/Rivet/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/superC12/Rivet/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/superC12/Rivet/releases/tag/v0.1.0
