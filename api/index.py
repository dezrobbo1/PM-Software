"""Stateless FastAPI entrypoint for Vercel's current Python runtime."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from time import monotonic
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from deterministic_scheduling_core.native_planning_ui.hosted import execute, initial_response  # noqa: E402
from deterministic_scheduling_core.native_planning_ui.server import MAX_BODY_BYTES  # noqa: E402

_BOOTED_AT = monotonic()
_INVOCATIONS = 0  # Diagnostics only; never used as workspace state.
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def _origin_matches_https_host(headers) -> bool:
    hosts = headers.getlist("host")
    origins = headers.getlist("origin")
    protos = headers.getlist("x-forwarded-proto")
    if len(hosts) != 1 or len(origins) != 1 or protos != ["https"]:
        return False
    host = hosts[0]
    origin = origins[0]
    try:
        serving = urlsplit(f"https://{host}")
        supplied = urlsplit(origin)
        return (
            serving.hostname is not None
            and host == serving.netloc
            and supplied.scheme == "https"
            and supplied.username is None
            and supplied.password is None
            and supplied.hostname == serving.hostname
            and (supplied.port if supplied.port is not None else 443)
            == (serving.port if serving.port is not None else 443)
            and origin == f"{supplied.scheme}://{supplied.netloc}"
        )
    except ValueError:
        return False


def _response(status: int, value: dict, started: float) -> JSONResponse:
    global _INVOCATIONS
    _INVOCATIONS += 1
    elapsed_ms = round((monotonic() - started) * 1000, 1)
    value["runtime"] = {
        "server_elapsed_ms": elapsed_ms,
        "instance_invocation": _INVOCATIONS,
        "module_age_ms": round((monotonic() - _BOOTED_AT) * 1000, 1),
    }
    return JSONResponse(
        status_code=status,
        content=value,
        headers={**_SECURITY_HEADERS, "Server-Timing": f"app;dur={elapsed_ms}"},
    )


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/planning")
async def initial_state() -> JSONResponse:
    started = monotonic()
    return _response(200, initial_response(), started)


@app.post("/api/planning")
async def action(request: Request) -> JSONResponse:
    started = monotonic()
    if not _origin_matches_https_host(request.headers):
        return _response(403, {"ok": False, "error": "hosted mutations require the exact serving HTTPS origin"}, started)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return _response(415, {"ok": False, "error": "hosted mutations require Content-Type application/json"}, started)
    try:
        declared_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared_length = 0
    if declared_length <= 0 or declared_length > MAX_BODY_BYTES:
        return _response(413, {"ok": False, "error": "request body must be present and no larger than 2 MiB"}, started)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return _response(413, {"ok": False, "error": "request body must be present and no larger than 2 MiB"}, started)
    try:
        body = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _response(400, {"ok": False, "error": "request body must be valid JSON"}, started)
    status, result = execute(body)
    return _response(status, result, started)


# The Python runtime owns the deployment routes when a project-level ASGI
# entrypoint is configured. Serve the same packaged trial assets from that
# function rather than depending on a build-output directory that is not part
# of the isolated function filesystem.
app.mount(
    "/",
    StaticFiles(
        directory=_ROOT / "src" / "deterministic_scheduling_core" / "native_planning_ui",
        html=True,
    ),
    name="frontend",
)
