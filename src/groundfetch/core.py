from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

CONFIG_DIR = Path.home() / ".config" / "groundfetch"
ENV_FILE = CONFIG_DIR / ".env"

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT = 30
DEFAULT_USER_AGENT = "groundfetch/0.1"
DEFAULT_ANTIGRAVITY_AUTH_DIR = Path.home() / ".cli-proxy-api"
DEFAULT_ANTIGRAVITY_USER_AGENT = "antigravity/2.0.11 darwin/arm64"
DEFAULT_GROK_AUTH_FILE = Path.home() / ".grok" / "auth.json"
DEFAULT_GROK_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
DEFAULT_GROK_API_BASE_URL = "https://api.x.ai/v1"
DEFAULT_GROK_MODEL = "grok-build"
DEFAULT_GROK_USER_AGENT = "grok-cli/0.2.54"
DEFAULT_GROK_CLIENT_VERSION = "0.2.54"

MAX_LIMIT = 20
DESCRIPTION_MAX_LEN = 500
REDIRECT_TIMEOUT = 10
ANTIGRAVITY_REFRESH_SKEW = timedelta(minutes=5)

GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
GROUNDING_REDIRECT_PATH_PREFIX = "/grounding-api-redirect/"

PROVIDER_GEMINI = "gemini"
PROVIDER_ANTIGRAVITY = "antigravity"
PROVIDER_GROK = "grok"
PROVIDERS = {PROVIDER_GEMINI, PROVIDER_ANTIGRAVITY, PROVIDER_GROK}

ANTIGRAVITY_CLIENT_ID_ENV = "GROUNDFETCH_ANTIGRAVITY_CLIENT_ID"
ANTIGRAVITY_CLIENT_SECRET_ENV = "GROUNDFETCH_ANTIGRAVITY_CLIENT_SECRET"
ANTIGRAVITY_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ANTIGRAVITY_GENERATE_PATH = "/v1internal:generateContent"
ANTIGRAVITY_LOAD_CODE_ASSIST_PATH = "/v1internal:loadCodeAssist"
ANTIGRAVITY_ONBOARD_USER_PATH = "/v1internal:onboardUser"
ANTIGRAVITY_DEFAULT_BASE_URLS = (
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
)
ANTIGRAVITY_PROJECT_BASE_URL = "https://cloudcode-pa.googleapis.com"
ANTIGRAVITY_DAILY_BASE_URL = "https://daily-cloudcode-pa.googleapis.com"
ANTIGRAVITY_NODE_API_CLIENT_UA = "google-api-nodejs-client/10.3.0"
ANTIGRAVITY_GOOG_API_CLIENT_UA = "gl-node/22.21.1"

GROK_RESPONSES_PATH = "/responses"
GROK_TOKEN_AUTH_HEADER = "xai-grok-cli"


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


@dataclass(frozen=True)
class AntigravityOAuthCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    model: str
    timeout: int
    user_agent: str
    provider: str = PROVIDER_GEMINI
    antigravity_auth_file: str = ""
    antigravity_auth_dir: str = str(DEFAULT_ANTIGRAVITY_AUTH_DIR)
    antigravity_base_urls: tuple[str, ...] = ANTIGRAVITY_DEFAULT_BASE_URLS
    antigravity_user_agent: str = DEFAULT_ANTIGRAVITY_USER_AGENT
    antigravity_client_id: str = ""
    antigravity_client_secret: str = ""
    grok_auth_file: str = str(DEFAULT_GROK_AUTH_FILE)
    grok_api_key: str = ""
    grok_base_url: str = DEFAULT_GROK_BASE_URL
    grok_model: str = DEFAULT_GROK_MODEL
    grok_user_agent: str = DEFAULT_GROK_USER_AGENT
    grok_client_version: str = DEFAULT_GROK_CLIENT_VERSION
    providers: tuple[str, ...] = (PROVIDER_GEMINI,)

    @classmethod
    def from_env(
        cls,
        *,
        default_provider: str | None = None,
        provider_override: str | None = None,
    ) -> "Config":
        api_key = os.environ.get("GROUNDFETCH_API_KEY", "").strip()
        antigravity_auth_file = os.environ.get("GROUNDFETCH_ANTIGRAVITY_AUTH_FILE", "").strip()
        antigravity_auth_dir = (
            os.environ.get("GROUNDFETCH_ANTIGRAVITY_AUTH_DIR", "").strip()
            or str(DEFAULT_ANTIGRAVITY_AUTH_DIR)
        )
        antigravity_client_id = os.environ.get(ANTIGRAVITY_CLIENT_ID_ENV, "").strip()
        antigravity_client_secret = os.environ.get(ANTIGRAVITY_CLIENT_SECRET_ENV, "").strip()
        antigravity_user_agent = (
            os.environ.get("GROUNDFETCH_ANTIGRAVITY_USER_AGENT", "").strip()
            or DEFAULT_ANTIGRAVITY_USER_AGENT
        )
        antigravity_base_urls = parse_antigravity_base_urls(
            os.environ.get("GROUNDFETCH_ANTIGRAVITY_BASE_URL", "")
        )
        grok_auth_file = (
            os.environ.get("GROUNDFETCH_GROK_AUTH_FILE", "").strip()
            or str(DEFAULT_GROK_AUTH_FILE)
        )
        grok_api_key = os.environ.get("GROUNDFETCH_GROK_API_KEY", "").strip()
        raw_grok_base_url = os.environ.get("GROUNDFETCH_GROK_BASE_URL", "").strip().rstrip("/")
        if raw_grok_base_url:
            grok_base_url = raw_grok_base_url
        elif grok_api_key:
            grok_base_url = DEFAULT_GROK_API_BASE_URL
        else:
            grok_base_url = DEFAULT_GROK_BASE_URL
        grok_model = os.environ.get("GROUNDFETCH_GROK_MODEL", "").strip() or DEFAULT_GROK_MODEL
        grok_user_agent = (
            os.environ.get("GROUNDFETCH_GROK_USER_AGENT", "").strip()
            or DEFAULT_GROK_USER_AGENT
        )
        grok_client_version = (
            os.environ.get("GROUNDFETCH_GROK_CLIENT_VERSION", "").strip()
            or DEFAULT_GROK_CLIENT_VERSION
        )

        provider_source = (provider_override or "").strip()
        if not provider_source:
            provider_source = os.environ.get("GROUNDFETCH_PROVIDERS", "").strip()
        if not provider_source:
            provider_source = os.environ.get("GROUNDFETCH_PROVIDER", "").strip()
        if provider_source:
            providers = parse_providers(provider_source)
            provider = providers[0]
        else:
            if default_provider:
                provider = default_provider
            elif antigravity_auth_file:
                provider = PROVIDER_ANTIGRAVITY
            else:
                provider = PROVIDER_GEMINI
            providers = (provider,)
        if PROVIDER_GROK in providers:
            parsed_grok_base_url = urllib.parse.urlparse(grok_base_url)
            if parsed_grok_base_url.scheme != "https" or not parsed_grok_base_url.netloc:
                raise ConfigError("GROUNDFETCH_GROK_BASE_URL must be an https URL")

        raw_timeout = os.environ.get("GROUNDFETCH_TIMEOUT", "").strip()
        try:
            timeout = int(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT
        except ValueError as exc:
            raise ConfigError(f"GROUNDFETCH_TIMEOUT must be an integer, got {raw_timeout!r}") from exc

        if providers == (PROVIDER_GEMINI,) and not api_key:
            raise ConfigError(
                "GROUNDFETCH_API_KEY is not set "
                f"(looked in env and {ENV_FILE})"
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
            provider=provider,
            antigravity_auth_file=antigravity_auth_file,
            antigravity_auth_dir=antigravity_auth_dir,
            antigravity_base_urls=antigravity_base_urls,
            antigravity_user_agent=antigravity_user_agent,
            antigravity_client_id=antigravity_client_id,
            antigravity_client_secret=antigravity_client_secret,
            grok_auth_file=grok_auth_file,
            grok_api_key=grok_api_key,
            grok_base_url=grok_base_url,
            grok_model=grok_model,
            grok_user_agent=grok_user_agent,
            grok_client_version=grok_client_version,
            providers=providers,
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


def parse_antigravity_base_urls(raw: str) -> tuple[str, ...]:
    values = [
        value.strip().rstrip("/")
        for value in raw.split(",")
        if value.strip().rstrip("/")
    ]
    return tuple(values) or ANTIGRAVITY_DEFAULT_BASE_URLS


def parse_providers(raw: str) -> tuple[str, ...]:
    providers: list[str] = []
    seen: set[str] = set()
    for value in raw.split(","):
        provider = value.strip().lower().replace("-", "_")
        if not provider:
            continue
        if provider not in PROVIDERS:
            raise ConfigError(
                "GROUNDFETCH_PROVIDER/GROUNDFETCH_PROVIDERS must contain only "
                f"{', '.join(sorted(PROVIDERS))}, got {provider!r}"
            )
        if provider not in seen:
            seen.add(provider)
            providers.append(provider)
    if not providers:
        raise ConfigError("provider list must include at least one provider")
    return tuple(providers)


def selected_providers(config: Config) -> tuple[str, ...]:
    if config.providers == (PROVIDER_GEMINI,) and config.provider != PROVIDER_GEMINI:
        return (config.provider,)
    return config.providers


def expand_path(path: str) -> Path:
    return Path(path).expanduser()


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


def build_headers(config: Config) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": config.user_agent,
        "x-goog-api-key": config.api_key,
    }


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
    except TimeoutError as exc:
        raise UpstreamError(
            f"{config.endpoint} timed out after {config.timeout}s"
        ) from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("upstream returned invalid JSON") from exc


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"auth file not found: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"could not read auth file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"auth file is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"auth file must contain a JSON object: {path}")
    return payload


def find_antigravity_auth_file(config: Config) -> Path:
    if config.antigravity_auth_file:
        return expand_path(config.antigravity_auth_file)

    raise ConfigError(
        "GROUNDFETCH_ANTIGRAVITY_AUTH_FILE is required; point it at an existing "
        "Antigravity OAuth auth JSON (for example one produced by CLIProxyAPI)"
    )


def parse_rfc3339(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if "." in value:
        dot = value.find(".")
        end = dot + 1
        while end < len(value) and value[end].isdigit():
            end += 1
        if end - dot > 7:
            value = value[: dot + 7] + value[end:]
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_grok_expires_at(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            epoch = float(stripped)
        except ValueError:
            return parse_rfc3339(stripped)
    else:
        return None

    if epoch > 1_000_000_000_000:
        epoch = epoch / 1000
    try:
        return datetime.fromtimestamp(epoch, timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def antigravity_token_expired(metadata: dict[str, Any]) -> bool:
    expired = parse_rfc3339(normalize(metadata.get("expired")))
    if expired is None:
        return True
    return expired <= datetime.now(timezone.utc) + ANTIGRAVITY_REFRESH_SKEW


def antigravity_oauth_credentials(config: Config) -> AntigravityOAuthCredentials:
    client_id = normalize(config.antigravity_client_id)
    client_secret = normalize(config.antigravity_client_secret)
    if not client_id or not client_secret:
        raise ConfigError(
            f"Refreshing an expired Antigravity access token requires {ANTIGRAVITY_CLIENT_ID_ENV} "
            f"and {ANTIGRAVITY_CLIENT_SECRET_ENV}"
        )
    return AntigravityOAuthCredentials(client_id=client_id, client_secret=client_secret)


def refresh_antigravity_auth(config: Config, metadata: dict[str, Any]) -> dict[str, Any]:
    refresh_token = normalize(metadata.get("refresh_token"))
    if not refresh_token:
        raise ConfigError("Antigravity auth is expired and has no refresh_token")
    credentials = antigravity_oauth_credentials(config)

    form = urllib.parse.urlencode(
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ANTIGRAVITY_TOKEN_ENDPOINT,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Go-http-client/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(f"Antigravity OAuth refresh failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"Antigravity OAuth refresh failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Antigravity OAuth refresh returned invalid JSON") from exc

    if not isinstance(token_payload, dict):
        raise UpstreamError("Antigravity OAuth refresh returned unexpected JSON")

    access_token = normalize(token_payload.get("access_token"))
    if not access_token:
        raise UpstreamError("Antigravity OAuth refresh returned no access_token")

    return refresh_metadata_from_token_payload(token_payload, metadata)


def write_auth_metadata(path: Path, metadata: dict[str, Any]) -> None:
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, separators=(",", ":"))
    except OSError:
        pass


def load_antigravity_auth(config: Config) -> tuple[dict[str, Any], Path]:
    path = find_antigravity_auth_file(config)
    metadata = read_json_file(path)
    if normalize(metadata.get("type")) != PROVIDER_ANTIGRAVITY:
        raise ConfigError(f"auth file is not an Antigravity auth file: {path}")

    if antigravity_token_expired(metadata):
        metadata = refresh_antigravity_auth(config, metadata)
        write_auth_metadata(path, metadata)

    if not normalize(metadata.get("access_token")):
        raise ConfigError(f"Antigravity auth file has no access_token: {path}")
    return metadata, path


def refresh_metadata_from_token_payload(
    token_payload: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(metadata)
    try:
        expires_in = int(token_payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    now = datetime.now(timezone.utc)
    updated["type"] = PROVIDER_ANTIGRAVITY
    updated["access_token"] = normalize(token_payload.get("access_token"))
    if normalize(token_payload.get("refresh_token")):
        updated["refresh_token"] = normalize(token_payload.get("refresh_token"))
    updated["expires_in"] = expires_in
    updated["timestamp"] = int(now.timestamp() * 1000)
    updated["expired"] = (now + timedelta(seconds=expires_in)).isoformat().replace(
        "+00:00", "Z"
    )
    return updated


def antigravity_project_id(config: Config, metadata: dict[str, Any]) -> str:
    project_id = normalize(metadata.get("project_id"))
    if project_id:
        return project_id

    token = normalize(metadata.get("access_token"))
    request = urllib.request.Request(
        ANTIGRAVITY_PROJECT_BASE_URL + ANTIGRAVITY_LOAD_CODE_ASSIST_PATH,
        data=json.dumps({"metadata": {"ideType": "ANTIGRAVITY"}}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": config.antigravity_user_agent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(
            f"Antigravity project discovery failed: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"Antigravity project discovery failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Antigravity project discovery returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise UpstreamError("Antigravity project discovery returned unexpected JSON")

    project_id = extract_antigravity_project_id(payload)
    if not project_id:
        project_id = onboard_antigravity_user(
            config,
            metadata,
            default_antigravity_tier_id(payload),
        )
    if not project_id:
        raise UpstreamError("Antigravity project discovery returned no project_id")
    metadata["project_id"] = project_id
    return project_id


def default_antigravity_tier_id(payload: dict[str, Any]) -> str:
    tiers = payload.get("allowedTiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict) or tier.get("isDefault") is not True:
                continue
            tier_id = normalize(tier.get("id"))
            if tier_id:
                return tier_id
    current_tier = payload.get("currentTier")
    if isinstance(current_tier, dict):
        tier_id = normalize(current_tier.get("id"))
        if tier_id:
            return tier_id
    return "free-tier"


def antigravity_control_user_agent(config: Config) -> str:
    user_agent = config.antigravity_user_agent
    if "google-api-nodejs-client/" in user_agent.lower():
        return user_agent
    return f"{user_agent} {ANTIGRAVITY_NODE_API_CLIENT_UA}"


def antigravity_version_from_user_agent(user_agent: str) -> str:
    prefix = "antigravity/"
    lower = user_agent.lower()
    if not lower.startswith(prefix):
        return "1.21.9"
    rest = user_agent[len(prefix):].strip()
    return rest.split()[0] if rest else "1.21.9"


def onboard_antigravity_user(
    config: Config,
    metadata: dict[str, Any],
    tier_id: str,
) -> str:
    token = normalize(metadata.get("access_token"))
    user_agent = antigravity_control_user_agent(config)
    body = {
        "tier_id": tier_id,
        "metadata": {
            "ide_type": "ANTIGRAVITY",
            "ide_version": antigravity_version_from_user_agent(user_agent),
            "ide_name": "antigravity",
        },
    }
    request = urllib.request.Request(
        ANTIGRAVITY_DAILY_BASE_URL + ANTIGRAVITY_ONBOARD_USER_PATH,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
            "X-Goog-Api-Client": ANTIGRAVITY_GOOG_API_CLIENT_UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(
            f"Antigravity onboardUser failed: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"Antigravity onboardUser failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Antigravity onboardUser returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise UpstreamError("Antigravity onboardUser returned unexpected JSON")

    response = payload.get("response")
    if isinstance(response, dict):
        project_id = extract_antigravity_project_id(response)
        if project_id:
            return project_id
    return extract_antigravity_project_id(payload)


def extract_antigravity_project_id(payload: dict[str, Any]) -> str:
    for key in ("cloudaicompanionProject", "projectId", "project"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            project_id = normalize(value.get("id"))
            if project_id:
                return project_id
    return ""


def stable_session_id(body: dict[str, Any]) -> str:
    contents = body.get("contents")
    if isinstance(contents, list):
        for content in contents:
            if not isinstance(content, dict) or content.get("role") != "user":
                continue
            parts = content.get("parts")
            if isinstance(parts, list) and parts and isinstance(parts[0], dict):
                text = normalize(parts[0].get("text"))
                if text:
                    digest = sha256(text.encode("utf-8")).digest()
                    value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
                    return f"-{value}"
    value = uuid4().int % 9_000_000_000_000_000_000
    return f"-{value}"


def antigravity_body(config: Config, query: str, project_id: str) -> dict[str, Any]:
    request_body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    return {
        "project": project_id,
        "request": {
            **request_body,
            "sessionId": stable_session_id(request_body),
        },
        "model": config.model,
        "userAgent": "antigravity",
        "requestType": "agent",
        "requestId": f"agent-{uuid4()}",
    }


def post_antigravity_generate_content(config: Config, query: str) -> dict[str, Any]:
    metadata, auth_path = load_antigravity_auth(config)
    project_id = antigravity_project_id(config, metadata)
    write_auth_metadata(auth_path, metadata)

    body = antigravity_body(config, query, project_id)
    token = normalize(metadata.get("access_token"))
    last_error: GroundFetchError | None = None
    for base_url in config.antigravity_base_urls:
        endpoint = base_url.rstrip("/") + ANTIGRAVITY_GENERATE_PATH
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": config.antigravity_user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise UpstreamError("Antigravity returned unexpected JSON")
                return unwrap_antigravity_response(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = UpstreamError(f"HTTP {exc.code} from {endpoint}: {detail}")
            if exc.code != 429:
                break
        except urllib.error.URLError as exc:
            last_error = UpstreamError(f"connection to {endpoint} failed: {exc.reason}")
        except TimeoutError as exc:
            last_error = UpstreamError(f"{endpoint} timed out after {config.timeout}s")
        except json.JSONDecodeError as exc:
            raise UpstreamError("Antigravity returned invalid JSON") from exc

    if last_error:
        raise last_error
    raise UpstreamError("Antigravity request failed")


def unwrap_antigravity_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload, dict) else None
    return response if isinstance(response, dict) else payload


def load_grok_auth(config: Config) -> dict[str, Any]:
    path = expand_path(config.grok_auth_file)
    payload = read_json_file(path)
    candidates: list[tuple[int, datetime, str, dict[str, Any]]] = []
    expired_with_token = False
    now = datetime.now(timezone.utc)

    for key, value in payload.items():
        if not isinstance(key, str) or not key.startswith("https://auth.x.ai::"):
            continue
        if not isinstance(value, dict) or not normalize(value.get("key")):
            continue
        expires_at = parse_grok_expires_at(value.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            expired_with_token = True
            continue
        expiry_priority = 1 if expires_at is not None else 0
        sort_expiry = expires_at or datetime.min.replace(tzinfo=timezone.utc)
        candidates.append((expiry_priority, sort_expiry, key, value))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates[0][3]

    if expired_with_token:
        raise ConfigError(
            f"Grok auth token in {path} is expired; run `grok login` to re-authenticate"
        )
    raise ConfigError(f"Grok auth file has no active https://auth.x.ai session token: {path}")


def validate_grok_base_url(config: Config) -> None:
    parsed = urllib.parse.urlparse(config.grok_base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError("GROUNDFETCH_GROK_BASE_URL must be an https URL")


def grok_body(config: Config, query: str) -> dict[str, Any]:
    return {
        "model": config.grok_model,
        "input": query,
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "stream": False,
    }


def build_grok_headers(config: Config, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": config.grok_user_agent,
        "X-XAI-Token-Auth": GROK_TOKEN_AUTH_HEADER,
        "x-grok-model-override": config.grok_model,
        "x-grok-client-version": config.grok_client_version,
    }


def build_grok_api_headers(config: Config, token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": config.grok_user_agent,
    }


def post_grok_responses(config: Config, query: str) -> dict[str, Any]:
    validate_grok_base_url(config)
    if config.grok_api_key:
        token = config.grok_api_key
        headers = build_grok_api_headers(config, token)
    else:
        metadata = load_grok_auth(config)
        token = normalize(metadata.get("key"))
        headers = build_grok_headers(config, token)
    endpoint = config.grok_base_url.rstrip("/") + GROK_RESPONSES_PATH
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(grok_body(config, query)).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise UpstreamError("Grok returned unexpected JSON")
            return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(f"HTTP {exc.code} from {endpoint}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"connection to {endpoint} failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise UpstreamError(f"{endpoint} timed out after {config.timeout}s") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Grok returned invalid JSON") from exc


def extract_summary(candidate: dict[str, Any]) -> str:
    parts = ((candidate.get("content") or {}).get("parts")) or []
    texts = [normalize(part.get("text")) for part in parts if isinstance(part, dict)]
    return "\n".join(text for text in texts if text)


def extract_results(
    candidate: dict[str, Any],
    summary: str,
    limit: int,
    user_agent: str,
    provider_used: str,
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
                provider=provider_used,
            )
        )

    return results


def grok_output_text(payload: dict[str, Any]) -> str:
    texts: list[str] = []
    output = payload.get("output") or []
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            text = normalize(part.get("text"))
            if text:
                texts.append(text)
    return "\n".join(texts)


def iter_grok_source_candidates(payload: dict[str, Any]) -> list[dict[str, str]]:
    annotation_candidates: list[dict[str, str]] = []
    search_candidates: list[dict[str, str]] = []
    output = payload.get("output") or []
    if not isinstance(output, list):
        return []

    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content") or []
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                annotations = part.get("annotations") or []
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        continue
                    if annotation.get("type") != "url_citation":
                        continue
                    url = normalize(annotation.get("url"))
                    if url:
                        annotation_candidates.append(
                            {"url": url, "title": normalize(annotation.get("title"))}
                        )
        if item.get("type") != "web_search_call":
            continue
        action = item.get("action") or {}
        if not isinstance(action, dict):
            continue
        sources = action.get("sources") or []
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = normalize(source.get("url"))
            if url:
                search_candidates.append({"url": url, "title": normalize(source.get("title"))})
    return annotation_candidates + search_candidates


def parse_grok_response(payload: dict[str, Any], limit: int) -> SearchResponse:
    if not isinstance(payload, dict):
        raise UpstreamError(f"unexpected Grok response shape: {type(payload).__name__}")
    if payload.get("error"):
        error = payload["error"]
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or "unknown"
        else:
            message = str(error)
        raise UpstreamError(f"Grok API error: {message}")

    summary = grok_output_text(payload)
    description = summary[:DESCRIPTION_MAX_LEN] if summary else ""
    seen: set[str] = set()
    results: list[WebResult] = []
    for candidate in iter_grok_source_candidates(payload):
        if len(results) >= limit:
            break
        url = candidate["url"]
        if url in seen:
            continue
        seen.add(url)
        title = candidate.get("title") or url
        if title.isdigit():
            title = url
        results.append(
            WebResult(
                title=title,
                url=url,
                description=description,
                position=len(results) + 1,
                provider=PROVIDER_GROK,
            )
        )

    return SearchResponse(
        success=True,
        provider="groundfetch",
        providersUsed=[PROVIDER_GROK],
        data={"web": results},
    )


def parse_response(
    payload: dict[str, Any],
    limit: int,
    user_agent: str,
    *,
    provider_used: str = PROVIDER_GEMINI,
) -> SearchResponse:
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
    results = extract_results(candidate, summary, limit, user_agent, provider_used)

    return SearchResponse(
        success=True,
        provider="groundfetch",
        providersUsed=[provider_used],
        data={"web": results},
    )


def validate_gemini_auth(config: Config) -> None:
    if not config.api_key:
        raise ConfigError(
            "GROUNDFETCH_API_KEY is not set "
            f"(looked in env and {ENV_FILE})"
        )


def search_with_provider(config: Config, query: str, limit: int, provider: str) -> SearchResponse:
    provider_config = (
        config
        if config.provider == provider
        else replace(config, provider=provider, providers=(provider,))
    )
    if provider == PROVIDER_ANTIGRAVITY:
        payload = post_antigravity_generate_content(provider_config, query)
        return parse_response(
            payload,
            limit,
            provider_config.user_agent,
            provider_used=PROVIDER_ANTIGRAVITY,
        )
    if provider == PROVIDER_GROK:
        payload = post_grok_responses(provider_config, query)
        return parse_grok_response(payload, limit)
    validate_gemini_auth(provider_config)
    payload = post_generate_content(provider_config, query)
    return parse_response(payload, limit, provider_config.user_agent)


def merge_provider_responses(
    responses: dict[str, SearchResponse],
    provider_order: tuple[str, ...],
    limit: int,
) -> SearchResponse:
    providers_used = [provider for provider in provider_order if provider in responses]
    web_by_provider = [
        list(responses[provider]["data"].get("web", []))
        for provider in providers_used
    ]
    seen: set[str] = set()
    merged: list[WebResult] = []
    index = 0
    while len(merged) < limit and any(index < len(items) for items in web_by_provider):
        for items in web_by_provider:
            if len(merged) >= limit:
                break
            if index >= len(items):
                continue
            item = items[index]
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            updated = WebResult(
                title=item["title"],
                url=item["url"],
                description=item["description"],
                position=len(merged) + 1,
                provider=item["provider"],
            )
            merged.append(updated)
        index += 1

    return SearchResponse(
        success=True,
        provider="groundfetch",
        providersUsed=providers_used,
        data={"web": merged},
    )


def aggregate_search(
    config: Config,
    query: str,
    limit: int,
    providers: tuple[str, ...],
) -> SearchResponse:
    responses: dict[str, SearchResponse] = {}
    errors: dict[str, GroundFetchError] = {}
    lock = threading.Lock()

    def run(provider: str) -> None:
        try:
            response = search_with_provider(config, query, limit, provider)
        except GroundFetchError as exc:
            with lock:
                errors[provider] = exc
            return
        except Exception as exc:
            with lock:
                errors[provider] = UpstreamError(f"{provider} failed: {exc}")
            return
        with lock:
            responses[provider] = response

    threads = [threading.Thread(target=run, args=(provider,)) for provider in providers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    if responses:
        for provider in providers:
            if provider in errors:
                print(
                    f"groundfetch warning: provider {provider} failed: {errors[provider]}",
                    file=sys.stderr,
                )
        return merge_provider_responses(responses, providers, limit)

    for provider in providers:
        if provider in errors:
            raise errors[provider]
    raise UpstreamError("all providers failed")


def search(query: str, *, limit: int = 5, config: Config | None = None) -> SearchResponse:
    if not query or not query.strip():
        raise ConfigError("query must be a non-empty string")

    bounded_limit = max(1, min(limit, MAX_LIMIT))
    cfg = config or Config.from_env()
    providers = selected_providers(cfg)
    stripped_query = query.strip()
    if len(providers) > 1:
        return aggregate_search(cfg, stripped_query, bounded_limit, providers)
    return search_with_provider(cfg, stripped_query, bounded_limit, providers[0])
