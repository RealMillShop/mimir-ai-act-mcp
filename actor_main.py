"""Apify Actor entrypoint.

Reads ``{text, deployment_type}`` from Apify input, calls the same
``audit_ai_deployment()`` function used by the MCP and HTTP transports, writes
the resulting ``ComplianceReport`` to the default dataset.

Required env (set as Secrets in the Apify Actor settings):
    ANTHROPIC_API_KEY

Optional env:
    MIMIR_AUDIT_MODEL  (default: claude-haiku-4-5-20251001)
"""
from __future__ import annotations

import asyncio

from apify import Actor

from server import DEPLOYMENT_TYPES, audit_ai_deployment


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        text = actor_input.get("text")
        deployment_type = actor_input.get("deployment_type")

        if not text or not isinstance(text, str) or not text.strip():
            await Actor.fail(
                status_message="`text` is required and must be a non-empty string"
            )
            return
        if deployment_type not in DEPLOYMENT_TYPES:
            await Actor.fail(
                status_message=(
                    f"`deployment_type` must be one of {DEPLOYMENT_TYPES}, "
                    f"got {deployment_type!r}"
                )
            )
            return

        Actor.log.info(f"Auditing {deployment_type} ({len(text)} chars)")
        try:
            report = audit_ai_deployment(text, deployment_type)
        except Exception as e:
            Actor.log.exception("audit_ai_deployment failed")
            await Actor.fail(status_message=f"Audit failed: {e}")
            return

        await Actor.push_data(report)
        Actor.log.info(
            f"Audit complete: status={report['compliance_status']} "
            f"risk_score={report['risk_score']} "
            f"violations={len(report['violations'])}"
        )


if __name__ == "__main__":
    asyncio.run(main())
