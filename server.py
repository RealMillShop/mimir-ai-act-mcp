"""MIMIR EU AI Act Compliance Auditor — MCP server (stdio transport).

Exposes one tool: ``audit_ai_deployment(text, deployment_type) -> ComplianceReport``.

The core function ``audit_ai_deployment()`` is the single source of truth — it is
reused by ``http_main.py`` (FastAPI HTTP wrapper for Apify and the mimir.lv lead
page) without duplication.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

load_dotenv()

REPO_ROOT = Path(__file__).parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
SCHEMAS_DIR = REPO_ROOT / "schemas"

VIOLATIONS_CATALOG_TEXT = (KNOWLEDGE_DIR / "violations_catalog.json").read_text(encoding="utf-8")
AI_ACT_RELEVANT_TEXT = (KNOWLEDGE_DIR / "ai_act_relevant.md").read_text(encoding="utf-8")
SYSTEM_PROMPT_TEXT = (KNOWLEDGE_DIR / "system_prompt.md").read_text(encoding="utf-8")
OUTPUT_SCHEMA: dict[str, Any] = json.loads(
    (SCHEMAS_DIR / "compliance_report.json").read_text(encoding="utf-8")
)

MODEL = os.getenv("MIMIR_AUDIT_MODEL", "claude-haiku-4-5-20251001")
AUDIT_VERSION = "1.0"

DEPLOYMENT_TYPES = [
    "voice_agent",
    "chatbot",
    "generated_content",
    "deepfake",
    "biometric_system",
    "other",
]

# Cached system block: instructions + catalog + relevant articles.
# ``cache_control: ephemeral`` keeps it for ~5 min; every audit after the first reuses it.
SYSTEM_BLOCKS: list[dict[str, Any]] = [
    {
        "type": "text",
        "text": (
            f"{SYSTEM_PROMPT_TEXT}\n\n"
            f"## Violations Catalog (JSON)\n\n"
            f"```json\n{VIOLATIONS_CATALOG_TEXT}\n```\n\n"
            f"## AI Act — Relevant Articles\n\n{AI_ACT_RELEVANT_TEXT}"
        ),
        "cache_control": {"type": "ephemeral"},
    }
]

# Model is forced to call this tool. input_schema = our output schema, so Anthropic
# validates the call shape before returning — no manual JSON parsing on our side.
SUBMIT_REPORT_TOOL: dict[str, Any] = {
    "name": "submit_compliance_report",
    "description": "Submit the structured EU AI Act compliance audit report.",
    "input_schema": OUTPUT_SCHEMA,
}

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in environment")
        _client = Anthropic(api_key=api_key)
    return _client


def audit_ai_deployment(text: str, deployment_type: str) -> dict[str, Any]:
    """Audit one AI deployment artifact against the EU AI Act catalog (V001-V012).

    Reused by both the MCP server (stdio) and the HTTP wrapper.
    Returns a dict matching schemas/compliance_report.json.
    """
    if deployment_type not in DEPLOYMENT_TYPES:
        raise ValueError(
            f"deployment_type must be one of {DEPLOYMENT_TYPES}, got {deployment_type!r}"
        )
    if not text or not text.strip():
        raise ValueError("text must be a non-empty string")

    user_message = (
        f"Audit the following `{deployment_type}` artifact for EU AI Act compliance. "
        f"Input may be in English, Latvian, Lithuanian, Estonian, or Russian — handle all languages. "
        f"Call the `submit_compliance_report` tool with your findings.\n\n"
        f"---\n{text}\n---"
    )

    response = get_client().messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_BLOCKS,
        tools=[SUBMIT_REPORT_TOOL],
        tool_choice={"type": "tool", "name": "submit_compliance_report"},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            report: dict[str, Any] = dict(block.input)
            # Server-stamp these — don't trust the model to set them.
            report["audited_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            report["audit_version"] = AUDIT_VERSION
            return report

    raise RuntimeError(
        f"Expected tool_use block from model {MODEL}, got: "
        f"{[getattr(b, 'type', '?') for b in response.content]}"
    )


# --- MCP server wiring ------------------------------------------------------

server = Server("mimir-ai-act-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="audit_ai_deployment",
            description=(
                "Audit text/script of an AI deployment for EU AI Act violations "
                "(Articles 5, 50, 53). Returns a structured compliance report covering the top 12 "
                "violations most likely to appear in SMB deployments. Accepts input in EN/LV/LT/ET/RU."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The text to audit (voice agent script, chatbot opening message, "
                            "generated content brief, deepfake marketing copy, etc.)"
                        ),
                    },
                    "deployment_type": {
                        "type": "string",
                        "enum": DEPLOYMENT_TYPES,
                        "description": "What kind of AI deployment is being audited.",
                    },
                },
                "required": ["text", "deployment_type"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name != "audit_ai_deployment":
        raise ValueError(f"Unknown tool: {name}")
    report = audit_ai_deployment(arguments["text"], arguments["deployment_type"])
    return [TextContent(type="text", text=json.dumps(report, indent=2, ensure_ascii=False))]


def main() -> None:
    """Entrypoint for stdio transport (Claude Desktop, Cursor, etc.)."""

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
