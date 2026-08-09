from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import __version__
from backend.api import chat, conversations, health, models, nodes, routes, settings as settings_api
from backend.api.dependencies import database
from backend.config import ROOT, settings

FRONTEND = ROOT / "frontend"


class RevalidatingStaticFiles(StaticFiles):
    """Serve the frontend with `Cache-Control: no-cache`.

    Not "do not cache" — "check with me before reusing". Without it the
    browser caches JS and CSS heuristically, and upgrading Rivet leaves
    people running a stale interface against a new backend until they
    manually hard-reload. That failure is invisible and infuriating: the
    served file is correct, the loaded file is not.

    The cost is one conditional request per asset, answered with a 304.
    On the LAN or Tailscale link Rivet is designed for, that is nothing
    next to shipping a broken upgrade.
    """

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    yield


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title=settings.assistant["platform"]["name"], version=__version__, lifespan=lifespan)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(nodes.router)
app.include_router(routes.router)
app.include_router(settings_api.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.mount("/static", RevalidatingStaticFiles(directory=FRONTEND), name="static")

# The shell names every asset the app loads, so a stale copy of it
# pins a stale interface no matter how fresh those assets are.
NO_CACHE = {"Cache-Control": "no-cache"}


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers=NO_CACHE)


@app.get("/{path:path}", include_in_schema=False)
async def frontend_fallback(path: str) -> FileResponse:
    # An unknown API path is a bug in the caller, not a deep link. Serving
    # index.html there returns 200 and HTML to something expecting JSON,
    # which turns a clear 404 into a confusing parse error.
    if path == "api" or path.startswith("api/") or path == "health":
        raise HTTPException(404, "Not found")
    candidate = (FRONTEND / path).resolve()
    if FRONTEND.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate, headers=NO_CACHE)
    return FileResponse(FRONTEND / "index.html", headers=NO_CACHE)
