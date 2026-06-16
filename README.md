# GroundFetch

Lightweight grounded web search for coding agents.

GroundFetch calls grounded search providers and returns compact JSON results
with source titles and URLs. It supports Gemini `generateContent`,
Antigravity's Cloud Code PA wrapper, and Grok's CLI chat proxy Responses API.
It is designed for agent workflows that want source-backed web lookup without
keeping an MCP server loaded.

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

If you are asking Codex to install from just the repository URL, paste this:

```text
Install GroundFetch from https://github.com/clavulin/groundfetch for this user.
Clone the repo if needed, install it with Python, symlink `skills/groundfetch`
into `~/.codex/skills/groundfetch`, and verify `groundfetch --help` works.
Do not invent credentials; if configuration is missing, report the exact
`GROUNDFETCH_*` variables needed from README.md.
```

If you are asking Claude Code to install from just the repository URL, paste
this:

```text
Install GroundFetch from https://github.com/clavulin/groundfetch for this user.
Clone the repo if needed and install it with Python. Copy `skills/groundfetch`
into `~/.claude/skills/groundfetch` (copy, do not symlink), then delete the
Codex-only `agents/openai.yaml` from that copy so only the Claude-relevant skill
files are installed. Verify `groundfetch --help` works. Do not invent
credentials; if configuration is missing, report the exact `GROUNDFETCH_*`
variables needed from README.md.
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
GROUNDFETCH_PROVIDER=gemini
# Run multiple providers concurrently and merge/dedupe results by URL:
# GROUNDFETCH_PROVIDERS=gemini,grok
GROUNDFETCH_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GROUNDFETCH_TIMEOUT=30
GROUNDFETCH_USER_AGENT=groundfetch/0.1
GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT=10
```

### Antigravity auth

GroundFetch can also use Antigravity OAuth auth JSON files compatible with
CLIProxyAPI.
This sends requests to Antigravity's Cloud Code PA `v1internal:generateContent`
endpoint instead of the standard Gemini API.

Create an auth file directly:

```bash
export GROUNDFETCH_ANTIGRAVITY_CLIENT_ID='your-google-oauth-client-id'
export GROUNDFETCH_ANTIGRAVITY_CLIENT_SECRET='your-google-oauth-client-secret'
groundfetch --login-antigravity
```

For remote shells or browser sessions where localhost cannot call back into the
script, use manual callback mode. GroundFetch prints the OAuth URL, you open it
in any browser, then paste the final `http://localhost:.../oauth-callback?...`
URL back into the script:

```bash
groundfetch --login-antigravity --antigravity-manual-callback
```

For non-interactive use, pass the final callback URL directly:

```bash
groundfetch --login-antigravity --antigravity-callback-url 'http://localhost:51121/oauth-callback?code=...&state=...'
```

Or create an Antigravity auth file with CLIProxyAPI. Then configure GroundFetch:

```dotenv
GROUNDFETCH_PROVIDER=antigravity
GROUNDFETCH_ANTIGRAVITY_AUTH_FILE=~/.cli-proxy-api/antigravity-you@example.com.json
GROUNDFETCH_MODEL=gemini-3-pro
```

Optional Antigravity settings:

```dotenv
GROUNDFETCH_ANTIGRAVITY_BASE_URL=https://daily-cloudcode-pa.googleapis.com,https://cloudcode-pa.googleapis.com
GROUNDFETCH_ANTIGRAVITY_USER_AGENT=antigravity/2.0.11 darwin/arm64
GROUNDFETCH_ANTIGRAVITY_CLIENT_ID=your-google-oauth-client-id
GROUNDFETCH_ANTIGRAVITY_CLIENT_SECRET=your-google-oauth-client-secret
```

GroundFetch uses existing Antigravity access tokens without OAuth client
settings. The client id and secret are required only for `--login-antigravity`
and for refreshing expired Antigravity access tokens with the stored
`refresh_token`. It discovers `project_id` via `loadCodeAssist` when missing
and falls back to `onboardUser` for first-use accounts.

### Grok auth

GroundFetch can use an existing Grok CLI login. Run `grok login` first; the CLI
stores session credentials in `~/.grok/auth.json`. GroundFetch reads the active
`https://auth.x.ai::<uuid>` entry, uses its `key` as a bearer token, and checks
`expires_at`. Expired Grok tokens are not refreshed by GroundFetch; run
`grok login` again.

```dotenv
GROUNDFETCH_PROVIDER=grok
GROUNDFETCH_GROK_AUTH_FILE=~/.grok/auth.json
GROUNDFETCH_GROK_BASE_URL=https://cli-chat-proxy.grok.com/v1
GROUNDFETCH_GROK_MODEL=grok-build
GROUNDFETCH_GROK_USER_AGENT=grok-cli/0.2.54
GROUNDFETCH_GROK_CLIENT_VERSION=0.2.54
```

The Grok provider sends `POST /v1/responses` to the CLI chat proxy with
`tools: [{"type":"web_search"}]`, `X-XAI-Token-Auth: xai-grok-cli`,
`x-grok-model-override`, and `x-grok-client-version`. Results are parsed from
`output_text.annotations` entries of type `url_citation`, with
`web_search_call.action.sources` used as fallback source candidates.

### Provider aggregation

Set `GROUNDFETCH_PROVIDERS=gemini,grok` or pass
`--provider gemini,grok` to run providers concurrently. GroundFetch returns
results from providers that succeeded, omits failed providers from
`providersUsed`, dedupes by exact URL, and interleaves results round-robin in
the requested provider order before renumbering positions.

Local project `.env` files are also loaded after the user-level config, without
overriding live environment variables.

## Use

```bash
groundfetch --query "Cloudflare Workers cron triggers official docs" --limit 3
groundfetch --provider gemini,grok --query "Cloudflare Workers cron triggers official docs" --limit 5
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
        "provider": "gemini"
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
