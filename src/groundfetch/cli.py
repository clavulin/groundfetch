from __future__ import annotations

import argparse
import json
import sys

from groundfetch.core import GroundFetchError, load_default_env, search


def main(argv: list[str] | None = None) -> int:
    load_default_env()

    parser = argparse.ArgumentParser(description="Run a lightweight grounded web search.")
    parser.add_argument("--query", "-q", required=True, help="Search query text")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Maximum results, 1-20")
    args = parser.parse_args(argv)

    try:
        result = search(args.query, limit=args.limit)
    except GroundFetchError as exc:
        print(f"groundfetch error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
