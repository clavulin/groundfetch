from __future__ import annotations

import argparse
import json
import sys

from groundfetch.core import Config, GroundFetchError, load_default_env, search


def main(argv: list[str] | None = None) -> int:
    load_default_env()

    parser = argparse.ArgumentParser(description="Run a lightweight grounded web search.")
    parser.add_argument("--query", "-q", help="Search query text")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Maximum results, 1-20")
    parser.add_argument(
        "--provider",
        help="Provider or comma-separated providers: gemini, antigravity, grok",
    )
    args = parser.parse_args(argv)

    if not args.query:
        parser.error("--query is required")

    try:
        config = Config.from_env(provider_override=args.provider) if args.provider else None
        result = search(args.query, limit=args.limit, config=config)
    except GroundFetchError as exc:
        print(f"groundfetch error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
