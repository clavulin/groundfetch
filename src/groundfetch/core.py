from __future__ import annotations

import json
import os
import http.server
import queue
import secrets
import shlex
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
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
DEFAULT_OAUTH_TOKEN_COMMAND_TIMEOUT = 10
DEFAULT_ANTIGRAVITY_AUTH_DIR = Path.home() / ".cli-proxy-api"
DEFAULT_ANTIGRAVITY_USER_AGENT = "antigravity/1.21.9 darwin/arm64"
DEFAULT_ANTIGRAVITY_CALLBACK_PORT = 51121

MAX_LIMIT = 20
DESCRIPTION_MAX_LEN = 500
REDIRECT_TIMEOUT = 10
ANTIGRAVITY_REFRESH_SKEW = timedelta(minutes=5)

GROUNDING_REDIRECT_HOST = "vertexaisearch.cloud.google.com"
GROUNDING_REDIRECT_PATH_PREFIX = "/grounding-api-redirect/"

PROVIDER_GEMINI = "gemini"
PROVIDER_ANTIGRAVITY = "antigravity"
PROVIDERS = {PROVIDER_GEMINI, PROVIDER_ANTIGRAVITY}

ANTIGRAVITY_CLIENT_ID_ENV = "GROUNDFETCH_ANTIGRAVITY_CLIENT_ID"
ANTIGRAVITY_CLIENT_SECRET_ENV = "GROUNDFETCH_ANTIGRAVITY_CLIENT_SECRET"
ANTIGRAVITY_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
ANTIGRAVITY_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ANTIGRAVITY_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo?alt=json"
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
ANTIGRAVITY_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
)


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
class AntigravityLoginResult:
    auth_file: Path
    email: str
    project_id: str


@dataclass(frozen=True)
class AntigravityOAuthCredentials:
    client_id: str
    client_secret: str


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
    provider: str = PROVIDER_GEMINI
    antigravity_auth_file: str = ""
    antigravity_auth_dir: str = str(DEFAULT_ANTIGRAVITY_AUTH_DIR)
    antigravity_base_urls: tuple[str, ...] = ANTIGRAVITY_DEFAULT_BASE_URLS
    antigravity_user_agent: str = DEFAULT_ANTIGRAVITY_USER_AGENT
    antigravity_client_id: str = ""
    antigravity_client_secret: str = ""

    @classmethod
    def from_env(
        cls,
        *,
        default_provider: str | None = None,
        provider_override: str | None = None,
    ) -> "Config":
        api_key = os.environ.get("GROUNDFETCH_API_KEY", "").strip()
        oauth_token = os.environ.get("GROUNDFETCH_OAUTH_TOKEN", "").strip()
        oauth_token_command = os.environ.get("GROUNDFETCH_OAUTH_TOKEN_COMMAND", "").strip()
        oauth_project = os.environ.get("GROUNDFETCH_OAUTH_PROJECT", "").strip()
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

        provider = (provider_override or "").strip().lower().replace("-", "_")
        if not provider:
            provider = (
                os.environ.get("GROUNDFETCH_PROVIDER", "").strip().lower().replace("-", "_")
            )
        if not provider:
            explicit_antigravity_dir = bool(
                os.environ.get("GROUNDFETCH_ANTIGRAVITY_AUTH_DIR", "").strip()
            )
            if default_provider:
                provider = default_provider
            elif antigravity_auth_file or explicit_antigravity_dir:
                provider = PROVIDER_ANTIGRAVITY
            else:
                provider = PROVIDER_GEMINI
        if provider not in PROVIDERS:
            raise ConfigError(
                "GROUNDFETCH_PROVIDER must be one of "
                f"{', '.join(sorted(PROVIDERS))}, got {provider!r}"
            )

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

        if provider == PROVIDER_GEMINI and auth_mode == AUTH_API_KEY and not api_key:
            raise ConfigError(
                "GROUNDFETCH_API_KEY is not set "
                f"(looked in env and {ENV_FILE}); set GROUNDFETCH_AUTH=oauth "
                "with GROUNDFETCH_OAUTH_TOKEN or GROUNDFETCH_OAUTH_TOKEN_COMMAND "
                "to use OAuth"
            )
        if provider == PROVIDER_GEMINI and auth_mode == AUTH_OAUTH and not (
            oauth_token or oauth_token_command
        ):
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
            provider=provider,
            antigravity_auth_file=antigravity_auth_file,
            antigravity_auth_dir=antigravity_auth_dir,
            antigravity_base_urls=antigravity_base_urls,
            antigravity_user_agent=antigravity_user_agent,
            antigravity_client_id=antigravity_client_id,
            antigravity_client_secret=antigravity_client_secret,
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

    auth_dir = expand_path(config.antigravity_auth_dir)
    try:
        candidates = sorted(auth_dir.glob("antigravity*.json"))
    except OSError as exc:
        raise ConfigError(f"could not list Antigravity auth dir {auth_dir}: {exc}") from exc

    usable: list[Path] = []
    for candidate in candidates:
        try:
            payload = read_json_file(candidate)
        except ConfigError:
            continue
        if normalize(payload.get("type")) == PROVIDER_ANTIGRAVITY:
            usable.append(candidate)

    if not usable:
        raise ConfigError(
            "no Antigravity auth JSON found; set GROUNDFETCH_ANTIGRAVITY_AUTH_FILE "
            "or run CLIProxyAPI's antigravity login"
        )
    return usable[0]


def parse_rfc3339(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
            f"Antigravity OAuth login and token refresh require {ANTIGRAVITY_CLIENT_ID_ENV} "
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


def save_auth_metadata(path: Path, metadata: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, separators=(",", ":"))
    except OSError as exc:
        raise ConfigError(f"could not write Antigravity auth file {path}: {exc}") from exc


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


def build_antigravity_auth_url(config: Config, state: str, redirect_uri: str) -> str:
    credentials = antigravity_oauth_credentials(config)
    params = urllib.parse.urlencode(
        {
            "access_type": "offline",
            "client_id": credentials.client_id,
            "prompt": "consent",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(ANTIGRAVITY_SCOPES),
            "state": state,
        }
    )
    return f"{ANTIGRAVITY_AUTH_ENDPOINT}?{params}"


class AntigravityCallbackHandler(http.server.BaseHTTPRequestHandler):
    result_queue: queue.Queue[dict[str, str]]

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/oauth-callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        result = {
            "code": params.get("code", [""])[0],
            "state": params.get("state", [""])[0],
            "error": params.get("error", [""])[0],
        }
        self.result_queue.put(result)
        ok = bool(result["code"] and not result["error"])
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "Login successful. You can close this window." if ok else "Login failed."
        self.wfile.write(f"<h1>{message}</h1>".encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        return


def wait_for_antigravity_callback(config: Config, port: int, timeout: int) -> tuple[str, str]:
    antigravity_oauth_credentials(config)
    result_queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1)
    handler = type(
        "GroundFetchAntigravityCallbackHandler",
        (AntigravityCallbackHandler,),
        {"result_queue": result_queue},
    )
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        raise ConfigError(f"could not start Antigravity OAuth callback server: {exc}") from exc
    actual_port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return_state = secrets.token_urlsafe(24)
    redirect_uri = f"http://localhost:{actual_port}/oauth-callback"
    auth_url = build_antigravity_auth_url(config, return_state, redirect_uri)
    print(f"Open this URL to authenticate Antigravity:\n{auth_url}", file=sys.stderr)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    try:
        result = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise ConfigError("Antigravity OAuth login timed out") from exc
    finally:
        server.shutdown()
        server.server_close()

    if result.get("error"):
        raise ConfigError(f"Antigravity OAuth login failed: {result['error']}")
    if result.get("state") != return_state:
        raise ConfigError("Antigravity OAuth login failed: state mismatch")
    code = result.get("code", "")
    if not code:
        raise ConfigError("Antigravity OAuth login failed: missing authorization code")
    return code, redirect_uri


def exchange_antigravity_code(config: Config, code: str, redirect_uri: str) -> dict[str, Any]:
    credentials = antigravity_oauth_credentials(config)
    form = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        ANTIGRAVITY_TOKEN_ENDPOINT,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(f"Antigravity token exchange failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"Antigravity token exchange failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Antigravity token exchange returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise UpstreamError("Antigravity token exchange returned unexpected JSON")
    if not normalize(payload.get("access_token")):
        raise UpstreamError("Antigravity token exchange returned no access_token")
    return payload


def fetch_antigravity_email(config: Config, access_token: str) -> str:
    request = urllib.request.Request(
        ANTIGRAVITY_USERINFO_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "User-Agent": config.antigravity_user_agent,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise UpstreamError(f"Antigravity userinfo failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise UpstreamError(f"Antigravity userinfo failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpstreamError("Antigravity userinfo returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise UpstreamError("Antigravity userinfo returned unexpected JSON")
    email = normalize(payload.get("email"))
    if not email:
        raise UpstreamError("Antigravity userinfo returned no email")
    return email


def credential_file_name(email: str) -> str:
    email = email.strip()
    return f"antigravity-{email}.json" if email else "antigravity.json"


def login_antigravity(config: Config, *, callback_port: int = DEFAULT_ANTIGRAVITY_CALLBACK_PORT) -> AntigravityLoginResult:
    code, redirect_uri = wait_for_antigravity_callback(config, callback_port, config.timeout * 10)
    token_payload = exchange_antigravity_code(config, code, redirect_uri)
    access_token = normalize(token_payload.get("access_token"))
    email = fetch_antigravity_email(config, access_token)
    metadata = refresh_metadata_from_token_payload(token_payload, {"type": PROVIDER_ANTIGRAVITY})
    metadata["email"] = email
    project_id = antigravity_project_id(config, metadata)
    metadata["project_id"] = project_id
    auth_path = expand_path(config.antigravity_auth_dir) / credential_file_name(email)
    save_auth_metadata(auth_path, metadata)
    return AntigravityLoginResult(auth_file=auth_path, email=email, project_id=project_id)


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
        except json.JSONDecodeError as exc:
            raise UpstreamError("Antigravity returned invalid JSON") from exc

    if last_error:
        raise last_error
    raise UpstreamError("Antigravity request failed")


def unwrap_antigravity_response(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload, dict) else None
    return response if isinstance(response, dict) else payload


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
    results = extract_results(candidate, summary, limit, user_agent)

    return SearchResponse(
        success=True,
        provider="groundfetch",
        providersUsed=[provider_used],
        data={"web": results},
    )


def search(query: str, *, limit: int = 5, config: Config | None = None) -> SearchResponse:
    if not query or not query.strip():
        raise ConfigError("query must be a non-empty string")

    bounded_limit = max(1, min(limit, MAX_LIMIT))
    cfg = config or Config.from_env()
    if cfg.provider == PROVIDER_ANTIGRAVITY:
        payload = post_antigravity_generate_content(cfg, query.strip())
        return parse_response(
            payload,
            bounded_limit,
            cfg.user_agent,
            provider_used=PROVIDER_ANTIGRAVITY,
        )
    payload = post_generate_content(cfg, query.strip())
    return parse_response(payload, bounded_limit, cfg.user_agent)
