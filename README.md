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

API key auth is the default. To use an OAuth access token instead:

```dotenv
GROUNDFETCH_AUTH=oauth
GROUNDFETCH_OAUTH_TOKEN=ya29...
GROUNDFETCH_OAUTH_PROJECT=my-google-cloud-project
```

Or point GroundFetch at a credential helper that prints an access token to
stdout:

```dotenv
GROUNDFETCH_AUTH=oauth
GROUNDFETCH_OAUTH_TOKEN_COMMAND="gcloud auth application-default print-access-token"
GROUNDFETCH_OAUTH_PROJECT=my-google-cloud-project
```

`GROUNDFETCH_OAUTH_PROJECT` is sent as `x-goog-user-project` when set, which is
commonly required for Gemini API OAuth quota/billing. GroundFetch intentionally
does not scrape private keyrings. If Antigravity or another OAuth login tool
exposes a supported token-printing helper, set `GROUNDFETCH_OAUTH_TOKEN_COMMAND`
to that command.

When `GROUNDFETCH_AUTH` is omitted, OAuth is selected automatically if
`GROUNDFETCH_OAUTH_TOKEN` or `GROUNDFETCH_OAUTH_TOKEN_COMMAND` is set; otherwise
API key auth is used.

Optional settings:

```dotenv
GROUNDFETCH_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GROUNDFETCH_TIMEOUT=30
GROUNDFETCH_USER_AGENT=groundfetch/0.1
GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT=10
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

## Agent Skill

The repo ships one tool-neutral skill at `skills/groundfetch/`. Codex and Claude
Code read the same `SKILL.md`; each ignores the other's extra files, so there is
only one copy of the instructions to maintain.

### Codex

Symlink the skill into your Codex skills directory, then invoke it with
`$groundfetch`:

```bash
ln -s "$PWD/skills/groundfetch" ~/.codex/skills/groundfetch
```

Codex-specific interface and policy live in `skills/groundfetch/agents/openai.yaml`.

### Claude Code

Quickest path — install the single skill at user scope (available in every
project). Claude auto-triggers it from the skill `description`:

```bash
ln -s "$PWD/skills/groundfetch" ~/.claude/skills/groundfetch
```

Or load the whole repo as a Claude Code plugin via `.claude-plugin/plugin.json`,
which auto-discovers the skill under `skills/`:

```bash
claude --plugin-dir "$PWD"   # loads the plugin for the current session
```

For a persistent, shareable install, the repo doubles as a single-plugin
marketplace (`.claude-plugin/marketplace.json`). Add it from GitHub, then
install:

```bash
claude plugin marketplace add clavulin/groundfetch
claude plugin install groundfetch@clavulin
```

Plugin skills are namespaced, so the skill is invoked as `groundfetch:groundfetch`
(or auto-triggered from its `description`). See the
[Claude Code plugin docs](https://code.claude.com/docs/en/plugins-reference).

## Environment Contract

GroundFetch reads `GROUNDFETCH_*` settings only.
