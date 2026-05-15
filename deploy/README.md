# Deployment runbook — MIMIR EU AI Act Compliance Checker

Three deployment targets, in order of priority:

1. **MIMIR VPS** (`your-vps.example.com`) — FastAPI HTTP wrapper as `mimir-ai-act-api` systemd unit on port 8200, fronted by Caddy at `mimir.lv/api/ai-act-audit/` and `mimir.lv/ai-act-checker`.
2. **Apify Store** — `.actor/` + `Dockerfile.actor` build an Actor that calls `audit_ai_deployment()` from input.
3. **Claude Desktop / Cursor** (local) — stdio MCP via `server.py`. See root [README.md](../README.md).

---

## 1. MIMIR VPS deploy

Assumes the repo is already at `/root/mimir-ai-act-mcp/` with `.venv/` set up (Phase 2 already did this for offline tests).

```bash
ssh root@your-vps.example.com
cd /root/mimir-ai-act-mcp

# 1a. Install systemd unit and inject the API key from the existing mimir-api unit
cp deploy/mimir-ai-act-api.service /etc/systemd/system/
KEY=$(systemctl show your-anthropic-service --property=Environment | grep -oP 'ANTHROPIC_API_KEY=\K\S+')
sed -i "s|REPLACE_ME|$KEY|" /etc/systemd/system/mimir-ai-act-api.service
chmod 600 /etc/systemd/system/mimir-ai-act-api.service
systemctl daemon-reload
systemctl enable --now mimir-ai-act-api
systemctl status mimir-ai-act-api --no-pager

# 1b. Confirm the wrapper responds on loopback
curl -s http://127.0.0.1:8200/health
# Expected: {"status":"ok","service":"mimir-ai-act-mcp","version":"1.0"}

# 1c. Wire into Caddy — merge deploy/caddy-snippet.conf into the mimir.lv block
#     BEFORE the existing `/api/*` → :8100 handler. See the snippet for ordering notes.
nano /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

# 1d. Drop the static landing page into the mimir.lv web root
mkdir -p /var/www/ai-act-checker
cp www/* /var/www/ai-act-checker/

# 1e. End-to-end smoke test
curl -s https://mimir.lv/api/ai-act-audit/health
# Expected: {"status":"ok",...}

# Open https://mimir.lv/ai-act-checker in a browser, paste a voice script, audit.
```

### Rate limiting

The current FastAPI wrapper does not rate-limit itself. Add either:

- Caddy `rate_limit` directive (requires the `caddy-rate-limit` module):
  ```caddy
  handle /api/ai-act-audit/* {
      rate_limit {
          zone ai_act_audit {
              key {remote_host}
              events 3
              window 1d
          }
      }
      reverse_proxy localhost:8200
  }
  ```
- Or a `slowapi` middleware in `http_main.py` (no extra Caddy module needed).

Recommend Caddy-side for now — keeps server stateless.

### Rollback

```bash
systemctl disable --now mimir-ai-act-api
rm /etc/systemd/system/mimir-ai-act-api.service
systemctl daemon-reload

# Revert the Caddyfile (manually remove the two handle blocks)
nano /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

# Optional: remove the static landing
rm -rf /var/www/ai-act-checker
```

---

## 2. Apify Store

```bash
# Install Apify CLI (one-time)
npm install -g apify-cli
apify login

# From the repo root on KOMP:
apify push
```

After upload (via the Apify console):

- Mark the Actor as **Public**.
- Configure pricing model: **Pay-per-event**, $0.05 per `audit_completed` event, first 100 events per user free. If pay-per-event is not available on this tier, fall back to **Pay-per-run** at $0.05.
- Add `ANTHROPIC_API_KEY` as a Secret env var in the Actor settings.
- Fill in description, categories (`ai`, `compliance`, `legal`), tags (`mcp`, `eu-ai-act`, `audit`).
- Add link to GitHub repo in the README.

### Apify smoke test

In the Apify console, "Run" the Actor with input:

```json
{
  "text": "Hello, this is Anna from BrightHouse Energy. How are you doing today?",
  "deployment_type": "voice_agent"
}
```

Expected output in the dataset: a `ComplianceReport` with `violations` containing V002.

---

## 3. Claude Desktop / Cursor (local stdio MCP)

See the [root README](../README.md) for `claude_desktop_config.json` snippet. Local stdio is the developer experience — Phase 3 changes don't affect it.
