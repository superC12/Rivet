# Contributing

Rivet intentionally stays small. Before adding a dependency or subsystem, confirm that it belongs in the orchestration layer rather than an existing external service.

## Development

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest
```

Run the application with:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8080 --reload
```

Pull requests should include focused tests, avoid logging prompts or secrets, preserve local-only privacy behavior, and keep the frontend usable without a heavyweight framework.
