"""FastAPI HTTP wrapper around ``audit_ai_deployment()``.

Used by:
- Apify Actor (``actor_main.py`` thin wrapper around this)
- ``mimir.lv/ai-act-checker`` lead-capture page
- any other non-MCP integration

Run locally:
    uvicorn http_main:app --host 0.0.0.0 --port 8200 --reload

In production, run as a systemd unit on port 8200 fronted by Caddy at
``/api/ai-act-audit/`` → ``localhost:8200``. See ``deploy/README.md``.

Security posture:
- API key only ever in the systemd Environment, never in code or logs.
- Rate-limited via slowapi (per-IP, 3 audits per day) — the lead-page free tier.
  Caddy sets X-Forwarded-For; we trust it for IP attribution. Higher-volume
  users should go through the Apify Actor where pricing handles abuse.
- FastAPI auto-docs (/docs, /redoc, /openapi.json) are disabled in production
  to avoid leaking the API shape and the framework fingerprint.
- Upstream model errors are sanitized server-side and never echoed to clients.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import APIError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from server import DEPLOYMENT_TYPES, audit_ai_deployment

log = logging.getLogger("mimir-ai-act-api")


def client_ip(request: Request) -> str:
    """Real client IP from Caddy's X-Forwarded-For; fall back to direct peer."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # X-Forwarded-For is comma-separated; the left-most entry is the original client.
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=client_ip, default_limits=[])

# docs_url/redoc_url/openapi_url=None — disable auto-generated docs in production.
# They leak API shape and frame fingerprint. The Apify INPUT_SCHEMA.json is the
# documented entrypoint for non-browser users.
app = FastAPI(
    title="MIMIR EU AI Act Compliance Checker",
    version="1.0",
    description="Audit AI deployments against EU AI Act Articles 5, 50, 53.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "MIMIR_ALLOWED_ORIGINS",
        "https://mimir.lv,http://localhost:5173,http://localhost:3000",
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AuditRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=20_000)
    deployment_type: str

    @field_validator("deployment_type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in DEPLOYMENT_TYPES:
            raise ValueError(f"deployment_type must be one of {DEPLOYMENT_TYPES}")
        return v


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mimir-ai-act-mcp", "version": "1.0"}


# Per-IP rate limit: matches the lead-page promise of "3 audits per IP per day".
# slowapi reads ``request`` to bucket by IP via ``client_ip`` key_func above.
# Higher-volume users get routed to the Apify Actor (paid path) by the JS.
@app.post("/audit")
@limiter.limit("3/day")
def audit(request: Request, req: AuditRequest) -> dict[str, Any]:
    try:
        return audit_ai_deployment(req.text, req.deployment_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except APIError as e:
        # Log full detail server-side; return a generic message to avoid leaking
        # billing state, request IDs, or upstream error bodies to the public endpoint.
        log.exception(
            "Anthropic API error: status=%s message=%s",
            getattr(e, "status_code", "?"),
            e.message,
        )
        if getattr(e, "status_code", None) == 429:
            raise HTTPException(status_code=503, detail="Rate limit exceeded. Please try again shortly.")
        raise HTTPException(status_code=502, detail="Audit service is temporarily unavailable.")
    except RuntimeError as e:
        log.exception("Audit RuntimeError")
        raise HTTPException(status_code=502, detail="Audit service error.")
