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
- `GROUNDFETCH_BASE_URL` (optional; defaults to `https://generativelanguage.googleapis.com/v1beta`)
- `GROUNDFETCH_MODEL`
- `GROUNDFETCH_TIMEOUT`
- `GROUNDFETCH_USER_AGENT`

It loads live environment variables, then `~/.config/groundfetch/.env`, then
`./.env`, without overriding live env.

## Rules

- Use concise, source-seeking queries.
- Keep `--limit` between 1 and 20.
- Treat `data.web[]` titles and URLs as the source list.
- If required configuration is missing, report the exact blocker instead of guessing.
