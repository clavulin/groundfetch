---
name: groundfetch
description: Use GroundFetch for lightweight grounded web search through a Gemini-compatible google_search endpoint without loading an MCP server. Trigger when the user asks for source-backed web lookup, current facts, citation discovery, or external search results and a CLI-based path is preferred.
metadata:
  short-description: Lightweight grounded web search
---

# GroundFetch

Use the bundled CLI instead of a search MCP server unless the user explicitly
asks for MCP.

## Tool

Run from a GroundFetch checkout:

```bash
PYTHONPATH=/path/to/groundfetch/src python3 -m groundfetch --query "search terms" --limit 5
```

If GroundFetch is installed as a package, run:

```bash
groundfetch --query "search terms" --limit 5
```

## Configuration

GroundFetch only reads `GROUNDFETCH_*` settings:

- `GROUNDFETCH_API_KEY`
- `GROUNDFETCH_AUTH` (`api_key` or `oauth`; defaults to `oauth` when OAuth token settings are present, otherwise `api_key`)
- `GROUNDFETCH_OAUTH_TOKEN` (OAuth bearer access token)
- `GROUNDFETCH_OAUTH_TOKEN_COMMAND` (credential helper that prints an access token)
- `GROUNDFETCH_OAUTH_PROJECT` (optional `x-goog-user-project` header value)
- `GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT` (optional; defaults to 10 seconds)
- `GROUNDFETCH_BASE_URL` (optional; defaults to `https://generativelanguage.googleapis.com/v1beta`)
- `GROUNDFETCH_MODEL`
- `GROUNDFETCH_TIMEOUT`
- `GROUNDFETCH_USER_AGENT`

It loads live environment variables, then `~/.config/groundfetch/.env`, then
`./.env`, without overriding live env.

For Antigravity-style OAuth, do not scrape private keyrings. Use
`GROUNDFETCH_OAUTH_TOKEN_COMMAND` only if the login tool exposes a supported
command that prints an access token.

## Rules

- Use concise, source-seeking queries.
- Keep `--limit` between 1 and 20.
- Treat `data.web[]` titles and URLs as the source list.
- If required configuration is missing, report the exact blocker instead of guessing.
