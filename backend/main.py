from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.benchmarks import seed as seed_starters
from backend.api import (
    benchmarks,
    chat,
    classify,
    conversations,
    health,
    models,
    nodes,
    routes,
    settings as settings_api,
)
from backend.api.dependencies import benchmark_store, database
from backend.config import ROOT, settings

FRONTEND = ROOT / "frontend"


class FreshStaticFiles(StaticFiles):
    """Never reuse frontend files across a Rivet upgrade.

    `no-cache` still permits a browser or reverse proxy to retain a module
    and revalidate it incorrectly. That produced a split UI in practice:
    new onboarding HTML with old onboarding JavaScript. Rivet's frontend is
    small, so a fresh transfer is a better trade than a silently inert UI.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    # Only seeds an empty table, so a deleted starter stays deleted.
    seed_starters(benchmark_store)
    yield


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title=settings.assistant["platform"]["name"], version=__version__, lifespan=lifespan)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(nodes.router)
app.include_router(routes.router)
app.include_router(classify.router)
app.include_router(benchmarks.router)
app.include_router(settings_api.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.mount("/static", FreshStaticFiles(directory=FRONTEND), name="static")

# The shell names every asset the app loads, so a stale copy of it
# pins a stale interface no matter how fresh those assets are.
NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers=NO_STORE)


@app.get("/{path:path}", include_in_schema=False)
async def frontend_fallback(path: str) -> FileResponse:
    # An unknown API path is a bug in the caller, not a deep link. Serving
    # index.html there returns 200 and HTML to something expecting JSON,
    # which turns a clear 404 into a confusing parse error.
    if path == "api" or path.startswith("api/") or path == "health":
        raise HTTPException(404, "Not found")
    candidate = (FRONTEND / path).resolve()
    if FRONTEND.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate, headers=NO_STORE)
    return FileResponse(FRONTEND / "index.html", headers=NO_STORE)
