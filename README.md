# GroundFetch

Lightweight grounded web search for coding agents.

GroundFetch calls a Gemini-compatible `generateContent` endpoint with the
`google_search` tool enabled, then returns compact JSON results with source
titles and URLs. It is designed for agent workflows that want source-backed web
lookup without keeping an MCP server loaded.

## Install

```bash
git clone https://github.com/clavulin/groundfetch.git
cd groundfetch
python3 -m pip install .
```

Or run directly from the checkout:

```bash
python3 -m groundfetch --query "OpenAI models official docs" --limit 5
```

## Configure

GroundFetch only reads `GROUNDFETCH_*` settings.

Create `~/.config/groundfetch/.env`:

```dotenv
GROUNDFETCH_API_KEY=...
GROUNDFETCH_MODEL=gemini-3.1-flash-lite
```

Optional settings:

```dotenv
GROUNDFETCH_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GROUNDFETCH_TIMEOUT=30
GROUNDFETCH_USER_AGENT=groundfetch/0.1
```

Local project `.env` files are also loaded after the user-level config, without
overriding live environment variables.

## Use

```bash
groundfetch --query "Cloudflare Workers cron triggers official docs" --limit 3
```

Example output:

```json
{
  "success": true,
  "provider": "groundfetch",
  "providersUsed": ["gemini"],
  "data": {
    "web": [
      {
        "title": "Example",
        "url": "https://example.com",
        "description": "Short grounded summary from the model response.",
        "position": 1,
        "provider": "groundfetch"
      }
    ]
  }
}
```

## Codex Skill

The repo includes a Codex skill at `skills/groundfetch`.

Install it by copying or symlinking that directory into your Codex skills
directory:

```bash
ln -s "$PWD/skills/groundfetch" ~/.codex/skills/groundfetch
```

Then invoke it with `$groundfetch`.

## Environment Contract

GroundFetch reads `GROUNDFETCH_*` settings only.
