from __future__ import annotations

import argparse
import json
import sys

from groundfetch.core import Config, GroundFetchError, load_default_env, login_antigravity, search


def main(argv: list[str] | None = None) -> int:
    load_default_env()

    parser = argparse.ArgumentParser(description="Run a lightweight grounded web search.")
    parser.add_argument("--query", "-q", help="Search query text")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Maximum results, 1-20")
    parser.add_argument(
        "--login-antigravity",
        action="store_true",
        help="Run Antigravity OAuth login and save a CLIProxyAPI-compatible auth JSON",
    )
    parser.add_argument(
        "--antigravity-callback-port",
        type=int,
        default=51121,
        help="Local OAuth callback port for --login-antigravity",
    )
    parser.add_argument(
        "--antigravity-manual-callback",
        action="store_true",
        help="Print the Antigravity OAuth URL and read the final localhost callback URL from stdin",
    )
    parser.add_argument(
        "--antigravity-callback-url",
        default="",
        help="Complete Antigravity localhost callback URL to exchange without running a local server",
    )
    args = parser.parse_args(argv)

    try:
        if args.login_antigravity:
            config = Config.from_env(provider_override="antigravity")
            result = login_antigravity(
                config,
                callback_port=args.antigravity_callback_port,
                manual_callback=args.antigravity_manual_callback,
                callback_url=args.antigravity_callback_url,
            )
            print(
                json.dumps(
                    {
                        "success": True,
                        "provider": "antigravity",
                        "authFile": str(result.auth_file),
                        "email": result.email,
                        "projectId": result.project_id,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if not args.query:
            parser.error("--query is required unless --login-antigravity is used")

        result = search(args.query, limit=args.limit)
    except GroundFetchError as exc:
        print(f"groundfetch error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
