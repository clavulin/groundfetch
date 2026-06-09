from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

CONFIG_DIR = Path.home() / ".config" / "groundfetch"
ENV_FILE = CONFIG_DIR / ".env"

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = "groundfetch/0.1"
DEFAULT_OAUTH_TOKEN_COMMAND_TIMEOUT = 10

MAX_LIMIT = 20
DESCRIPTION_MAX_LEN = 500
REDIRECT_TIMEOUT = 10

GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
GROUNDING_REDIRECT_PATH_PREFIX = "/grounding-api-redirect/"


class GroundFetchError(RuntimeError):
    """Base exception for GroundFetch failures."""


class ConfigError(GroundFetchError):
    """Configuration is missing or invalid."""


class UpstreamError(GroundFetchError):
    """The upstream search API returned an error."""


class WebResult(TypedDict):
    title: str
    url: str
    description: str
    position: int
    provider: str


class SearchResponse(TypedDict):
    success: bool
    provider: str
    providersUsed: list[str]
    data: dict[str, list[WebResult]]


AUTH_API_KEY = "api_key"
AUTH_OAUTH = "oauth"
AUTH_MODES = {AUTH_API_KEY, AUTH_OAUTH}


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    timeout: int
    user_agent: str
    auth_mode: str = AUTH_API_KEY
    oauth_token: str = ""
    oauth_token_command: str = ""
    oauth_project: str = ""
    oauth_token_command_timeout: int = DEFAULT_OAUTH_TOKEN_COMMAND_TIMEOUT

    @classmethod
    def from_env(cls) -> "Config":
        api_key = os.environ.get("GROUNDFETCH_API_KEY", "").strip()
        oauth_token = os.environ.get("GROUNDFETCH_OAUTH_TOKEN", "").strip()
        oauth_token_command = os.environ.get("GROUNDFETCH_OAUTH_TOKEN_COMMAND", "").strip()
        oauth_project = os.environ.get("GROUNDFETCH_OAUTH_PROJECT", "").strip()

        auth_mode = (
            os.environ.get("GROUNDFETCH_AUTH", "").strip().lower().replace("-", "_")
        )
        if auth_mode and auth_mode not in AUTH_MODES:
            raise ConfigError(
                "GROUNDFETCH_AUTH must be one of "
                f"{', '.join(sorted(AUTH_MODES))}, got {auth_mode!r}"
            )
        if not auth_mode:
            auth_mode = AUTH_OAUTH if oauth_token or oauth_token_command else AUTH_API_KEY

        raw_timeout = os.environ.get("GROUNDFETCH_TIMEOUT", "").strip()
        try:
            timeout = int(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
        except ValueError as exc:
            raise ConfigError(f"GROUNDFETCH_TIMEOUT must be an integer, got {raw_timeout!r}") from exc

        raw_oauth_token_command_timeout = (
            os.environ.get("GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT", "").strip()
        )
        try:
            oauth_token_command_timeout = (
                int(raw_oauth_token_command_timeout)
                if raw_oauth_token_command_timeout
                else DEFAULT_OAUTH_TOKEN_COMMAND_TIMEOUT
            )
        except ValueError as exc:
            raise ConfigError(
                "GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT must be an integer, "
                f"got {raw_oauth_token_command_timeout!r}"
            ) from exc

        if auth_mode == AUTH_API_KEY and not api_key:
            raise ConfigError(
                "GROUNDFETCH_API_KEY is not set "
                f"(looked in env and {ENV_FILE}); set GROUNDFETCH_AUTH=oauth "
                "with GROUNDFETCH_OAUTH_TOKEN or GROUNDFETCH_OAUTH_TOKEN_COMMAND "
                "to use OAuth"
            )
        if auth_mode == AUTH_OAUTH and not (oauth_token or oauth_token_command):
            raise ConfigError(
                "OAuth auth requires GROUNDFETCH_OAUTH_TOKEN or "
                "GROUNDFETCH_OAUTH_TOKEN_COMMAND"
            )

        base_url = (
            os.environ.get("GROUNDFETCH_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
        )
        model = os.environ.get("GROUNDFETCH_MODEL", "").strip() or DEFAULT_MODEL
        user_agent = os.environ.get("GROUNDFETCH_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            user_agent=user_agent,
            auth_mode=auth_mode,
            oauth_token=oauth_token,
            oauth_token_command=oauth_token_command,
            oauth_project=oauth_project,
            oauth_token_command_timeout=oauth_token_command_timeout,
        )

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/models/{self.model}:generateContent"


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load simple KEY=VALUE dotenv files without overriding live env."""
    if not path.exists():
        return

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_default_env() -> None:
    load_dotenv(ENV_FILE)
    load_dotenv(Path.cwd() / ".env")


def normalize(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def is_grounding_redirect(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return (
        parsed.netloc.lower() == GROUNDING_REDIRECT_HOST
        and GROUNDING_REDIRECT_PATH_PREFIX in parsed.path
    )


def resolve_redirect(url: str, user_agent: str) -> str:
    if not is_grounding_redirect(url):
        return url

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=REDIRECT_TIMEOUT) as response:
            resolved = normalize(response.geturl())
            if resolved.startswith(("http://", "https://")):
                return resolved
    except (urllib.error.URLError, TimeoutError):
        pass
    return url


def oauth_authorization_header(config: Config) -> str:
    token = config.oauth_token
    if not token and config.oauth_token_command:
        try:
            args = shlex.split(config.oauth_token_command)
        except ValueError as exc:
            raise ConfigError(
                f"GROUNDFETCH_OAUTH_TOKEN_COMMAND is invalid: {exc}"
            ) from exc
        if not args:
            raise ConfigError("GROUNDFETCH_OAUTH_TOKEN_COMMAND is empty")
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=config.oauth_token_command_timeout,
            )
        except FileNotFoundError as exc:
            raise ConfigError(
                "GROUNDFETCH_OAUTH_TOKEN_COMMAND executable was not found: "
                f"{args[0]!r}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConfigError(
                "GROUNDFETCH_OAUTH_TOKEN_COMMAND timed out after "
                f"{config.oauth_token_command_timeout}s"
            ) from exc

        if result.returncode != 0:
            detail = result.stderr.strip() or "no stderr"
            raise ConfigError(
                "GROUNDFETCH_OAUTH_TOKEN_COMMAND failed with exit "
                f"{result.returncode}: {detail[:500]}"
            )
        token = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""

    if not token:
        raise ConfigError("OAuth token command returned no token")

    return token if token.lower().startswith("bearer ") else f"Bearer {token}"


def build_headers(config: Config) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": config.user_agent,
    }
    if config.auth_mode == AUTH_OAUTH:
        headers["Authorization"] = oauth_authorization_header(config)
        if config.oauth_project:
            headers["x-goog-user-project"] = config.oauth_project
    else:
        headers["x-goog-api-key"] = config.api_key
    return headers


def post_generate_content(config: Config, query: str) -> dict[str, Any]:
    body = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    request = urllib.request.Request(
        config.endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers=build_headers(config),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(f"HTTP {exc.code} from {config.base_url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"connection to {config.base_url} failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("upstream returned invalid JSON") from exc


def extract_summary(candidate: dict[str, Any]) -> str:
    parts = ((candidate.get("content") or {}).get("parts")) or []
    texts = [normalize(part.get("text")) for part in parts if isinstance(part, dict)]
    return "\n".join(text for text in texts if text)


def extract_results(
    candidate: dict[str, Any],
    summary: str,
    limit: int,
    user_agent: str,
) -> list[WebResult]:
    chunks = ((candidate.get("groundingMetadata") or {}).get("groundingChunks")) or []
    description = summary[:DESCRIPTION_MAX_LEN] if summary else ""
    seen: set[str] = set()
    results: list[WebResult] = []

    for chunk in chunks:
        if len(results) >= limit:
            break
        if not isinstance(chunk, dict):
            continue

        web = chunk.get("web") or {}
        url = resolve_redirect(normalize(web.get("uri")), user_agent)
        if not url or url in seen:
            continue

        seen.add(url)
        results.append(
            WebResult(
                title=normalize(web.get("title")) or url,
                url=url,
                description=description,
                position=len(results) + 1,
                provider="groundfetch",
            )
        )

    return results


def parse_response(payload: dict[str, Any], limit: int, user_agent: str) -> SearchResponse:
    if not isinstance(payload, dict):
        raise UpstreamError(f"unexpected response shape: {type(payload).__name__}")

    if payload.get("error"):
        error = payload["error"]
        raise UpstreamError(
            f"API error ({error.get('code', 'unknown')}): {error.get('message', 'unknown')}"
        )

    candidates = payload.get("candidates") or []
    candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    summary = extract_summary(candidate)
    results = extract_results(candidate, summary, limit, user_agent)

    return SearchResponse(
        success=True,
        provider="groundfetch",
        providersUsed=["gemini"],
        data={"web": results},
    )


def search(query: str, *, limit: int = 5, config: Config | None = None) -> SearchResponse:
    if not query or not query.strip():
        raise ConfigError("query must be a non-empty string")

    bounded_limit = max(1, min(limit, MAX_LIMIT))
    cfg = config or Config.from_env()
    payload = post_generate_content(cfg, query.strip())
    return parse_response(payload, bounded_limit, cfg.user_agent)
