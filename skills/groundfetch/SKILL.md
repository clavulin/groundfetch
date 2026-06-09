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

Run:

```bash
groundfetch --query "search terms" --limit 5
```

## Rules

- Use concise, source-seeking queries.
- Keep `--limit` between 1 and 20.
- Treat `data.web[]` titles and URLs as the source list.
- If required configuration is missing, report the exact blocker instead of guessing.
