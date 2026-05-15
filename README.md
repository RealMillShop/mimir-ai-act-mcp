# MIMIR — EU AI Act Compliance Checker (MCP)

A Model Context Protocol (MCP) server that audits AI deployments — voice agents, chatbots, AI-generated content, deepfakes — against the EU Artificial Intelligence Act (Regulation (EU) 2024/1689). Single tool, structured output, runs locally next to your dev agent.

Coverage targets the obligations most likely to bite SMB deployments:

- **Article 5** — Prohibited AI practices (in force since 2025-02-02)
- **Article 50** — Transparency obligations (in force from 2026-08-02)
- **Article 53** — Obligations for providers of general-purpose AI models (in force since 2025-08-02)

**Not legal advice.** This is a first-pass developer tool to catch obvious gaps before shipping. Consult qualified counsel for binding decisions.

## What it does

Exposes one MCP tool:

```
audit_ai_deployment(text: str, deployment_type: str) -> ComplianceReport
```

Where `deployment_type` is one of `voice_agent | chatbot | generated_content | deepfake | biometric_system | other`.

Returns a structured report (see [schemas/compliance_report.json](schemas/compliance_report.json)) with status, risk score, individual violations with evidence and suggested fixes, plus general recommendations.

## Quickstart (Claude Desktop)

```bash
git clone https://github.com/mimir-lv/mimir-ai-act-mcp
cd mimir-ai-act-mcp
pip install -e .
cp .env.example .env  # add your ANTHROPIC_API_KEY
```

Add to `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mimir-ai-act": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

Restart Claude Desktop and ask:

> Use the `audit_ai_deployment` tool to check this voice script: [paste]

## Example output

```json
{
  "compliance_status": "non_compliant",
  "risk_score": 7,
  "violations": [
    {
      "violation_id": "V002",
      "article": "Article 50(1)",
      "title": "Voice agent missing AI disclosure",
      "severity": "high",
      "evidence": "Hello, this is Anna from [Company]. How are you doing today?",
      "explanation": "The opening introduces the caller as 'Anna' without disclosing she is an AI system. Article 50(1) requires that natural persons be informed they are interacting with AI, unless obvious from context.",
      "suggested_fix": "Replace the opening with: 'Hello, this is an AI assistant from [Company]. How are you doing today?'",
      "deadline": "2026-08-02"
    }
  ],
  "general_recommendations": ["..."],
  "disclaimer": "This is an automated first-pass check, not legal advice. Consult qualified counsel before deploying.",
  "audited_at": "2026-05-16T12:00:00Z",
  "audit_version": "1.0"
}
```

## What's covered (v1)

| ID   | Article  | Trigger                                                |
| ---- | -------- | ------------------------------------------------------ |
| V001 | 50(1)    | Chatbot missing AI disclosure                          |
| V002 | 50(1)    | Voice agent missing AI disclosure                      |
| V003 | 50(2)    | Synthetic content not machine-readable marked          |
| V004 | 50(4)    | Deepfake without clear disclosure                      |
| V005 | 50(4)    | AI-generated public-interest text without label        |
| V006 | 5(1)(a)  | Subliminal manipulation                                |
| V007 | 5(1)(b)  | Exploitation of vulnerabilities (age, disability)      |
| V008 | 5(1)(c)  | Social scoring with detrimental treatment              |
| V009 | 5(1)(f)  | Emotion recognition in workplace/education             |
| V010 | 5(1)(g)  | Biometric categorisation for sensitive attributes      |
| V011 | 5(1)(h)  | Real-time remote biometric identification in public    |
| V012 | 53       | GPAI provider missing documentation / copyright policy |

## Languages

Input text accepted in **English, Latvian, Lithuanian, Estonian, and Russian**. Reports are English-only in v1 (Baltic translations on the roadmap).

## Architecture (v0.1)

- **Model:** `claude-haiku-4-5` by default (fast, cheap). Set `MIMIR_AUDIT_MODEL=claude-sonnet-4-6` to escalate.
- **Structured output:** the model is forced to call a `submit_compliance_report` tool whose `input_schema` is the JSON Schema in [schemas/compliance_report.json](schemas/compliance_report.json). No JSON-string parsing.
- **Prompt caching:** the system prompt + violations catalog + relevant AI Act articles are cached server-side with `cache_control: ephemeral`. Audits within the 5-minute TTL reuse cache.
- **Transports:** stdio (Claude Desktop, Cursor); HTTP wrapper (`http_main.py`) reuses the same audit function for Apify and the `mimir.lv/ai-act-checker` lead page.

## Testing

Two test suites:

- **Offline tests** — no API calls. Verify catalog structure, schema validity, golden-set coverage, and clean imports. Safe for CI.
  ```bash
  pip install -e ".[dev]"
  pytest tests/test_offline.py
  ```

- **Live golden-set eval** — makes real Anthropic API calls (~60 calls × Haiku 4.5 ≈ €0.10 per run). Skipped by default.
  ```bash
  RUN_AUDIT_EVAL=1 pytest tests/test_audits.py -s
  ```
  Thresholds: recall ≥0.85, precision ≥0.75, consistency ≥0.80 across 20 examples × 3 runs.

## Privacy

- Audited text is sent to the Anthropic API. **Not persisted** by this server.
- No PII logging. Aggregate counts only.
- `ANTHROPIC_API_KEY` lives in env. Never in code, never logged.

## Roadmap

- v1.1 — Latvian / Lithuanian / Estonian / Russian report output
- v1.2 — Article 26 deployer obligations; Annex III high-risk classification
- v1.3 — Apify Actor + HTTP wrapper, public release on Apify Store
- v2 — Image / audio / video input via Claude vision

## About MIMIR

[MIMIR](https://mimir.lv) is a Latvian AI agency building production AI for SMBs across the Baltics. We built this tool because we needed it ourselves before shipping voice agents into the EU market. If you want help fixing the violations it flags, [get in touch](https://mimir.lv).

## License

MIT — see [LICENSE](LICENSE).
