"""FastAPI HTTP wrapper around ``audit_ai_deployment()``.

Used by:
- Apify Actor (``actor_main.py`` thin wrapper around this)
- ``mimir.lv/ai-act-checker`` lead-capture page
- any other non-MCP integration

Run locally:
    uvicorn http_main:app --host 0.0.0.0 --port 8200 --reload

In production on the MIMIR VPS, run as systemd unit ``mimir-ai-act-api`` on port 8200,
routed via Caddy ``/api/ai-act-audit`` → ``localhost:8200``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from anthropic import APIError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from server import DEPLOYMENT_TYPES, audit_ai_deployment

log = logging.getLogger("mimir-ai-act-api")

app = FastAPI(
    title="MIMIR EU AI Act Compliance Checker",
    version="1.0",
    description="Audit AI deployments against EU AI Act Articles 5, 50, 53.",
)

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


@app.post("/audit")
def audit(req: AuditRequest) -> dict[str, Any]:
    try:
        return audit_ai_deployment(req.text, req.deployment_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except APIError as e:
        # Log full detail server-side; return a generic message to avoid leaking
        # billing state, request IDs, or upstream error bodies to the public endpoint.
        log.exception("Anthropic API error: status=%s message=%s", getattr(e, "status_code", "?"), e.message)
        if getattr(e, "status_code", None) == 429:
            raise HTTPException(status_code=503, detail="Rate limit exceeded. Please try again shortly.")
        raise HTTPException(status_code=502, detail="Audit service is temporarily unavailable.")
    except RuntimeError as e:
        log.exception("Audit RuntimeError")
        raise HTTPException(status_code=502, detail="Audit service error.")
