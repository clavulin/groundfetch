import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from groundfetch import cli
from groundfetch import core


class FakeResponse:
    def __init__(self, payload, url="https://example.test"):
        self.payload = payload
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload

    def geturl(self):
        return self.url


def json_text(value):
    return json.dumps(value)


def json_loads(value):
    return json.loads(value.decode("utf-8"))


class ConfigTests(unittest.TestCase):
    def test_config_reads_groundfetch_vars(self):
        env = {
            "GROUNDFETCH_API_KEY": "key",
            "GROUNDFETCH_BASE_URL": "https://example.test/v1beta/",
            "GROUNDFETCH_MODEL": "model",
            "GROUNDFETCH_TIMEOUT": "7",
            "GROUNDFETCH_USER_AGENT": "agent",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.api_key, "key")
        self.assertEqual(config.auth_mode, core.AUTH_API_KEY)
        self.assertEqual(config.base_url, "https://example.test/v1beta")
        self.assertEqual(config.model, "model")
        self.assertEqual(config.timeout, 7)
        self.assertEqual(config.user_agent, "agent")

    def test_config_reads_oauth_token_without_api_key(self):
        env = {
            "GROUNDFETCH_AUTH": "oauth",
            "GROUNDFETCH_OAUTH_TOKEN": "token",
            "GROUNDFETCH_OAUTH_PROJECT": "project",
            "GROUNDFETCH_OAUTH_TOKEN_COMMAND_TIMEOUT": "3",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.api_key, "")
        self.assertEqual(config.auth_mode, core.AUTH_OAUTH)
        self.assertEqual(config.oauth_token, "token")
        self.assertEqual(config.oauth_project, "project")
        self.assertEqual(config.oauth_token_command_timeout, 3)

    def test_config_auto_selects_oauth_when_token_command_is_set(self):
        env = {
            "GROUNDFETCH_OAUTH_TOKEN_COMMAND": "print-token",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.auth_mode, core.AUTH_OAUTH)
        self.assertEqual(config.oauth_token_command, "print-token")

    def test_config_reads_antigravity_provider_without_api_key(self):
        env = {
            "GROUNDFETCH_PROVIDER": "antigravity",
            "GROUNDFETCH_ANTIGRAVITY_AUTH_FILE": "/tmp/auth.json",
            "GROUNDFETCH_ANTIGRAVITY_BASE_URL": "https://daily.test, https://prod.test/",
            "GROUNDFETCH_ANTIGRAVITY_USER_AGENT": "antigravity/test",
            "GROUNDFETCH_ANTIGRAVITY_CLIENT_ID": "client-id",
            "GROUNDFETCH_ANTIGRAVITY_CLIENT_SECRET": "client-secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.provider, core.PROVIDER_ANTIGRAVITY)
        self.assertEqual(config.antigravity_auth_file, "/tmp/auth.json")
        self.assertEqual(config.antigravity_base_urls, ("https://daily.test", "https://prod.test"))
        self.assertEqual(config.antigravity_user_agent, "antigravity/test")
        self.assertEqual(config.antigravity_client_id, "client-id")
        self.assertEqual(config.antigravity_client_secret, "client-secret")

    def test_config_reads_grok_provider_without_api_key(self):
        env = {
            "GROUNDFETCH_PROVIDER": "grok",
            "GROUNDFETCH_GROK_AUTH_FILE": "/tmp/grok-auth.json",
            "GROUNDFETCH_GROK_BASE_URL": "https://cli-chat-proxy.test/v1/",
            "GROUNDFETCH_GROK_MODEL": "grok-test",
            "GROUNDFETCH_GROK_USER_AGENT": "grok-cli/test",
            "GROUNDFETCH_GROK_CLIENT_VERSION": "0.2.test",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.provider, core.PROVIDER_GROK)
        self.assertEqual(config.providers, (core.PROVIDER_GROK,))
        self.assertEqual(config.grok_auth_file, "/tmp/grok-auth.json")
        self.assertEqual(config.grok_base_url, "https://cli-chat-proxy.test/v1")
        self.assertEqual(config.grok_model, "grok-test")
        self.assertEqual(config.grok_user_agent, "grok-cli/test")
        self.assertEqual(config.grok_client_version, "0.2.test")

    def test_config_reads_multi_provider_list(self):
        env = {
            "GROUNDFETCH_PROVIDERS": "gemini, grok, gemini",
            "GROUNDFETCH_GROK_AUTH_FILE": "/tmp/grok-auth.json",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.provider, core.PROVIDER_GEMINI)
        self.assertEqual(config.providers, (core.PROVIDER_GEMINI, core.PROVIDER_GROK))

    def test_config_rejects_http_grok_base_url(self):
        env = {
            "GROUNDFETCH_PROVIDER": "grok",
            "GROUNDFETCH_GROK_BASE_URL": "http://cli-chat-proxy.test/v1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(core.ConfigError, "https URL"):
                core.Config.from_env()

    def test_config_does_not_auto_select_antigravity_for_explicit_auth_dir(self):
        env = {
            "GROUNDFETCH_API_KEY": "key",
            "GROUNDFETCH_ANTIGRAVITY_AUTH_DIR": "/tmp/auths",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.provider, core.PROVIDER_GEMINI)
        self.assertEqual(config.antigravity_auth_dir, "/tmp/auths")

    def test_config_provider_override_wins_for_login(self):
        env = {
            "GROUNDFETCH_PROVIDER": "gemini",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env(provider_override="antigravity")

        self.assertEqual(config.provider, core.PROVIDER_ANTIGRAVITY)

    def test_config_rejects_missing_groundfetch_key(self):
        env = {
            "GROUNDFETCH_BASE_URL": "https://example.test/v1beta",
            "OTHER_API_KEY": "ignored",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(core.ConfigError):
                core.Config.from_env()

    def test_config_rejects_oauth_without_token_or_command(self):
        env = {
            "GROUNDFETCH_AUTH": "oauth",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(core.ConfigError):
                core.Config.from_env()

    def test_config_rejects_unknown_auth_mode(self):
        env = {
            "GROUNDFETCH_AUTH": "magic",
            "GROUNDFETCH_API_KEY": "key",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(core.ConfigError):
                core.Config.from_env()

    def test_config_rejects_unknown_provider(self):
        env = {
            "GROUNDFETCH_PROVIDER": "unknown",
            "GROUNDFETCH_API_KEY": "key",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(core.ConfigError):
                core.Config.from_env()

    def test_config_defaults_groundfetch_base_url(self):
        env = {
            "GROUNDFETCH_API_KEY": "key",
            "OTHER_BASE_URL": "https://ignored.test/v1beta",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = core.Config.from_env()

        self.assertEqual(config.base_url, core.DEFAULT_BASE_URL)

    def test_dotenv_does_not_override_live_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv = Path(tmpdir) / ".env"
            dotenv.write_text(
                "GROUNDFETCH_API_KEY=file-key\nGROUNDFETCH_BASE_URL=https://file.test\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"GROUNDFETCH_API_KEY": "live-key"}, clear=True):
                core.load_dotenv(dotenv)
                self.assertEqual(os.environ["GROUNDFETCH_API_KEY"], "live-key")
                self.assertEqual(os.environ["GROUNDFETCH_BASE_URL"], "https://file.test")


class AuthHeaderTests(unittest.TestCase):
    def test_build_headers_uses_api_key(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
        )

        headers = core.build_headers(config)

        self.assertEqual(headers["x-goog-api-key"], "key")
        self.assertNotIn("Authorization", headers)

    def test_build_headers_uses_oauth_token_and_project(self):
        config = core.Config(
            api_key="",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            auth_mode=core.AUTH_OAUTH,
            oauth_token="token",
            oauth_project="project",
        )

        headers = core.build_headers(config)

        self.assertEqual(headers["Authorization"], "Bearer token")
        self.assertEqual(headers["x-goog-user-project"], "project")
        self.assertNotIn("x-goog-api-key", headers)

    def test_build_headers_preserves_bearer_prefix(self):
        config = core.Config(
            api_key="",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            auth_mode=core.AUTH_OAUTH,
            oauth_token="Bearer token",
        )

        headers = core.build_headers(config)

        self.assertEqual(headers["Authorization"], "Bearer token")

    def test_build_headers_runs_oauth_token_command(self):
        config = core.Config(
            api_key="",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            auth_mode=core.AUTH_OAUTH,
            oauth_token_command="print-token --quiet",
            oauth_token_command_timeout=2,
        )
        completed = mock.Mock(returncode=0, stdout="token\n", stderr="")

        with mock.patch.object(core.subprocess, "run", return_value=completed) as run:
            headers = core.build_headers(config)

        self.assertEqual(headers["Authorization"], "Bearer token")
        run.assert_called_once_with(
            ["print-token", "--quiet"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )


class ProviderTimeoutTests(unittest.TestCase):
    def test_post_generate_content_wraps_timeout(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
        )

        with mock.patch.object(core.urllib.request, "urlopen", side_effect=TimeoutError("slow")):
            with self.assertRaisesRegex(core.UpstreamError, "timed out after 1s"):
                core.post_generate_content(config, "hello")

    def test_post_antigravity_generate_content_wraps_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "antigravity-user@example.test.json"
            auth_file.write_text(
                json_text(
                    {
                        "type": "antigravity",
                        "access_token": "token",
                        "expired": "2999-01-01T00:00:00Z",
                        "project_id": "project",
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_ANTIGRAVITY,
                antigravity_auth_file=str(auth_file),
                antigravity_base_urls=("https://daily.test",),
            )

            with mock.patch.object(
                core.urllib.request,
                "urlopen",
                side_effect=TimeoutError("slow"),
            ):
                with self.assertRaisesRegex(core.UpstreamError, "timed out after 1s"):
                    core.post_antigravity_generate_content(config, "hello")

    def test_post_grok_responses_wraps_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::active": {
                            "key": "token",
                            "expires_at": "2999-01-01T00:00:00Z",
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
                grok_base_url="https://cli-chat-proxy.test/v1",
            )

            with mock.patch.object(
                core.urllib.request,
                "urlopen",
                side_effect=TimeoutError("slow"),
            ):
                with self.assertRaisesRegex(core.UpstreamError, "timed out after 1s"):
                    core.post_grok_responses(config, "hello")


class AntigravityTests(unittest.TestCase):
    def test_build_antigravity_auth_url_matches_google_oauth_shape(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
            antigravity_client_id="client-id",
            antigravity_client_secret="client-secret",
        )
        url = core.build_antigravity_auth_url(
            config,
            "state",
            "http://localhost:51121/oauth-callback",
        )

        parsed = core.urllib.parse.urlparse(url)
        params = core.urllib.parse.parse_qs(parsed.query)

        self.assertEqual(
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
            core.ANTIGRAVITY_AUTH_ENDPOINT,
        )
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["prompt"], ["consent"])
        self.assertEqual(params["state"], ["state"])
        self.assertEqual(
            params["redirect_uri"],
            ["http://localhost:51121/oauth-callback"],
        )
        for scope in core.ANTIGRAVITY_SCOPES:
            self.assertIn(scope, params["scope"][0])

    def test_antigravity_oauth_credentials_are_required_for_login_paths(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
        )

        with self.assertRaises(core.ConfigError):
            core.build_antigravity_auth_url(
                config,
                "state",
                "http://localhost:51121/oauth-callback",
            )

    def test_wait_for_manual_antigravity_callback_parses_pasted_localhost_url(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
            antigravity_client_id="client-id",
            antigravity_client_secret="client-secret",
        )
        output = StringIO()

        with mock.patch.object(core.secrets, "token_urlsafe", return_value="state-token"):
            code, redirect_uri = core.wait_for_manual_antigravity_callback(
                config,
                51121,
                callback_url="http://localhost:51121/oauth-callback?code=auth-code&state=state-token",
                output_stream=output,
            )

        self.assertEqual(code, "auth-code")
        self.assertEqual(redirect_uri, "http://localhost:51121/oauth-callback")
        self.assertIn("Open this URL", output.getvalue())
        self.assertIn("state=state-token", output.getvalue())

    def test_parse_oauth_callback_accepts_query_string_only(self):
        callback = core.parse_oauth_callback("code=auth-code&state=state-token")

        self.assertEqual(callback.code, "auth-code")
        self.assertEqual(callback.state, "state-token")

    def test_parse_oauth_callback_rejects_state_mismatch(self):
        callback = core.parse_oauth_callback(
            "http://localhost:51121/oauth-callback?code=auth-code&state=wrong"
        )

        with self.assertRaises(core.ConfigError):
            core.validate_antigravity_callback(callback, "state-token")

    def test_load_antigravity_auth_requires_explicit_auth_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_ANTIGRAVITY,
                antigravity_auth_dir=tmpdir,
            )

            with self.assertRaises(core.ConfigError):
                core.load_antigravity_auth(config)

    def test_refresh_antigravity_auth_updates_token(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
            antigravity_client_id="client-id",
            antigravity_client_secret="client-secret",
        )
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = request.data.decode("utf-8")
            seen["timeout"] = timeout
            return FakeResponse(
                b'{"access_token":"new-token","refresh_token":"new-refresh","expires_in":3600}'
            )

        with mock.patch.object(core.urllib.request, "urlopen", side_effect=fake_urlopen):
            metadata = core.refresh_antigravity_auth(
                config,
                {"type": "antigravity", "refresh_token": "old-refresh"},
            )

        self.assertEqual(seen["url"], core.ANTIGRAVITY_TOKEN_ENDPOINT)
        self.assertIn("grant_type=refresh_token", seen["body"])
        self.assertIn("client_id=client-id", seen["body"])
        self.assertIn("client_secret=client-secret", seen["body"])
        self.assertIn("refresh_token=old-refresh", seen["body"])
        self.assertEqual(seen["timeout"], 1)
        self.assertEqual(metadata["access_token"], "new-token")
        self.assertEqual(metadata["refresh_token"], "new-refresh")
        self.assertEqual(metadata["type"], "antigravity")

    def test_antigravity_body_wraps_gemini_request(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="gemini-3-pro",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
        )

        body = core.antigravity_body(config, "hello", "project")

        self.assertEqual(body["project"], "project")
        self.assertEqual(body["model"], "gemini-3-pro")
        self.assertEqual(body["requestType"], "agent")
        self.assertTrue(body["requestId"].startswith("agent-"))
        self.assertEqual(body["request"]["contents"][0]["role"], "user")
        self.assertEqual(body["request"]["contents"][0]["parts"][0]["text"], "hello")
        self.assertEqual(body["request"]["tools"], [{"google_search": {}}])
        self.assertTrue(body["request"]["sessionId"].startswith("-"))

    def test_antigravity_project_id_fetches_from_load_code_assist(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
            antigravity_user_agent="antigravity/test",
        )
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json_loads(request.data)
            seen["timeout"] = timeout
            return FakeResponse(b'{"cloudaicompanionProject":"project"}')

        metadata = {"access_token": "token"}
        with mock.patch.object(core.urllib.request, "urlopen", side_effect=fake_urlopen):
            project_id = core.antigravity_project_id(config, metadata)

        self.assertEqual(project_id, "project")
        self.assertEqual(metadata["project_id"], "project")
        self.assertEqual(
            seen["url"],
            "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist",
        )
        self.assertEqual(seen["headers"]["Authorization"], "Bearer token")
        self.assertEqual(seen["body"], {"metadata": {"ideType": "ANTIGRAVITY"}})

    def test_antigravity_project_id_falls_back_to_onboard_user(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
            antigravity_user_agent="antigravity/1.22.0 darwin/arm64",
        )
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.header_items()),
                    "body": json_loads(request.data),
                    "timeout": timeout,
                }
            )
            if request.full_url.endswith(":loadCodeAssist"):
                return FakeResponse(b'{"allowedTiers":[{"id":"free-tier","isDefault":true}]}')
            return FakeResponse(
                b'{"done":true,"response":{"cloudaicompanionProject":{"id":"project"}}}'
            )

        metadata = {"access_token": "token"}
        with mock.patch.object(core.urllib.request, "urlopen", side_effect=fake_urlopen):
            project_id = core.antigravity_project_id(config, metadata)

        self.assertEqual(project_id, "project")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[1]["url"],
            "https://daily-cloudcode-pa.googleapis.com/v1internal:onboardUser",
        )
        self.assertEqual(calls[1]["body"]["tier_id"], "free-tier")
        self.assertEqual(calls[1]["body"]["metadata"]["ide_version"], "1.22.0")
        self.assertEqual(calls[1]["headers"]["X-goog-api-client"], "gl-node/22.21.1")

    def test_post_antigravity_generate_content_uses_cli_proxy_auth_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "antigravity-user@example.test.json"
            auth_file.write_text(
                json_text(
                    {
                        "type": "antigravity",
                        "access_token": "token",
                        "refresh_token": "refresh",
                        "expired": "2999-01-01T00:00:00Z",
                        "project_id": "project",
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_ANTIGRAVITY,
                antigravity_auth_file=str(auth_file),
                antigravity_base_urls=("https://daily.test",),
                antigravity_user_agent="antigravity/test",
            )
            seen = {}

            def fake_urlopen(request, timeout):
                seen["url"] = request.full_url
                seen["headers"] = dict(request.header_items())
                seen["body"] = json_loads(request.data)
                seen["timeout"] = timeout
                return FakeResponse(
                    json_text(
                        {
                            "response": {
                                "candidates": [
                                    {
                                        "content": {"parts": [{"text": "summary"}]},
                                        "groundingMetadata": {
                                            "groundingChunks": [
                                                {"web": {"title": "One", "uri": "https://one.test"}}
                                            ]
                                        },
                                    }
                                ]
                            }
                        }
                    ).encode("utf-8")
                )

            with mock.patch.object(core.urllib.request, "urlopen", side_effect=fake_urlopen):
                payload = core.post_antigravity_generate_content(config, "hello")

        self.assertEqual(seen["url"], "https://daily.test/v1internal:generateContent")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer token")
        self.assertEqual(seen["headers"]["User-agent"], "antigravity/test")
        self.assertEqual(seen["timeout"], 1)
        self.assertEqual(seen["body"]["project"], "project")
        self.assertEqual(seen["body"]["request"]["contents"][0]["parts"][0]["text"], "hello")
        self.assertIn("candidates", payload)

    def test_search_uses_antigravity_provider(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_ANTIGRAVITY,
        )
        payload = {"candidates": [{"groundingMetadata": {"groundingChunks": []}}]}

        with mock.patch.object(core, "post_antigravity_generate_content", return_value=payload) as post:
            result = core.search("hello", config=config)

        post.assert_called_once_with(config, "hello")
        self.assertEqual(result["providersUsed"], ["antigravity"])

    def test_login_antigravity_saves_cli_proxy_compatible_auth_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_ANTIGRAVITY,
                antigravity_auth_dir=tmpdir,
                antigravity_client_id="client-id",
                antigravity_client_secret="client-secret",
            )

            with (
                mock.patch.object(
                    core,
                    "wait_for_antigravity_callback",
                    return_value=("code", "http://localhost:51121/oauth-callback"),
                ) as wait,
                mock.patch.object(
                    core,
                    "exchange_antigravity_code",
                    return_value={
                        "access_token": "token",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    },
                ) as exchange,
                mock.patch.object(
                    core,
                    "fetch_antigravity_email",
                    return_value="user@example.test",
                ) as email,
                mock.patch.object(
                    core,
                    "antigravity_project_id",
                    return_value="project",
                ) as project,
            ):
                result = core.login_antigravity(config, callback_port=51121)

            saved = json.loads(result.auth_file.read_text(encoding="utf-8"))

        wait.assert_called_once_with(config, 51121, 10)
        exchange.assert_called_once_with(config, "code", "http://localhost:51121/oauth-callback")
        email.assert_called_once_with(config, "token")
        project.assert_called_once()
        self.assertEqual(result.email, "user@example.test")
        self.assertEqual(result.project_id, "project")
        self.assertEqual(result.auth_file.name, "antigravity-user@example.test.json")
        self.assertEqual(saved["type"], "antigravity")
        self.assertEqual(saved["access_token"], "token")
        self.assertEqual(saved["refresh_token"], "refresh")
        self.assertEqual(saved["email"], "user@example.test")
        self.assertEqual(saved["project_id"], "project")

    def test_login_antigravity_manual_callback_uses_pasted_url_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_ANTIGRAVITY,
                antigravity_auth_dir=tmpdir,
                antigravity_client_id="client-id",
                antigravity_client_secret="client-secret",
            )

            with (
                mock.patch.object(
                    core,
                    "wait_for_manual_antigravity_callback",
                    return_value=("code", "http://localhost:51121/oauth-callback"),
                ) as manual_wait,
                mock.patch.object(core, "wait_for_antigravity_callback") as server_wait,
                mock.patch.object(
                    core,
                    "exchange_antigravity_code",
                    return_value={
                        "access_token": "token",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    },
                ),
                mock.patch.object(core, "fetch_antigravity_email", return_value="user@example.test"),
                mock.patch.object(core, "antigravity_project_id", return_value="project"),
            ):
                result = core.login_antigravity(
                    config,
                    callback_port=51121,
                    manual_callback=True,
                    callback_url="http://localhost:51121/oauth-callback?code=code&state=state",
                )

        manual_wait.assert_called_once_with(
            config,
            51121,
            callback_url="http://localhost:51121/oauth-callback?code=code&state=state",
        )
        server_wait.assert_not_called()
        self.assertEqual(result.email, "user@example.test")


class GrokTests(unittest.TestCase):
    def test_load_grok_auth_picks_active_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::expired": {
                            "key": "old-token",
                            "expires_at": "2000-01-01T00:00:00.123456789Z",
                        },
                        "https://auth.x.ai::active": {
                            "key": "active-token",
                            "refresh_token": "refresh",
                            "expires_at": "2999-01-01T00:00:00.123456789Z",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
            )

            metadata = core.load_grok_auth(config)

        self.assertEqual(metadata["key"], "active-token")

    def test_load_grok_auth_picks_latest_parseable_active_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::first": {
                            "key": "first-token",
                            "expires_at": "2999-01-01T00:00:00Z",
                        },
                        "https://auth.x.ai::second": {
                            "key": "second-token",
                            "expires_at": "2999-01-02T00:00:00Z",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
            )

            metadata = core.load_grok_auth(config)

        self.assertEqual(metadata["key"], "second-token")

    def test_load_grok_auth_unparseable_expiry_does_not_outrank_future_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::zzz-unparseable": {
                            "key": "unparseable-token",
                            "expires_at": "not-a-date",
                        },
                        "https://auth.x.ai::aaa-future": {
                            "key": "future-token",
                            "expires_at": "2999-01-01T00:00:00Z",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
            )

            metadata = core.load_grok_auth(config)

        self.assertEqual(metadata["key"], "future-token")

    def test_load_grok_auth_handles_numeric_epoch_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::expired": {
                            "key": "expired-token",
                            "expires_at": 946684800,
                        },
                        "https://auth.x.ai::future": {
                            "key": "future-token",
                            "expires_at": 32503680000,
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
            )

            metadata = core.load_grok_auth(config)

        self.assertEqual(metadata["key"], "future-token")

    def test_load_grok_auth_expiry_error_tells_user_to_relogin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::expired": {
                            "key": "old-token",
                            "expires_at": "2000-01-01T00:00:00.123456789Z",
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
            )

            with self.assertRaisesRegex(core.ConfigError, "grok login"):
                core.load_grok_auth(config)

    def test_post_grok_responses_rejects_non_https_base_url(self):
        config = core.Config(
            api_key="",
            base_url=core.DEFAULT_BASE_URL,
            model="model",
            timeout=1,
            user_agent="agent",
            provider=core.PROVIDER_GROK,
            grok_base_url="http://cli-chat-proxy.test/v1",
        )

        with self.assertRaisesRegex(core.ConfigError, "https URL"):
            core.post_grok_responses(config, "hello")

    def test_post_grok_responses_uses_cli_proxy_auth_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = Path(tmpdir) / "auth.json"
            auth_file.write_text(
                json_text(
                    {
                        "https://auth.x.ai::active": {
                            "key": "token",
                            "expires_at": "2999-01-01T00:00:00Z",
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = core.Config(
                api_key="",
                base_url=core.DEFAULT_BASE_URL,
                model="model",
                timeout=1,
                user_agent="agent",
                provider=core.PROVIDER_GROK,
                grok_auth_file=str(auth_file),
                grok_base_url="https://cli-chat-proxy.test/v1",
                grok_model="grok-test",
                grok_user_agent="grok-cli/test",
                grok_client_version="0.2.test",
            )
            seen = {}

            def fake_urlopen(request, timeout):
                seen["url"] = request.full_url
                seen["headers"] = dict(request.header_items())
                seen["body"] = json_loads(request.data)
                seen["timeout"] = timeout
                return FakeResponse(b'{"output":[]}')

            with mock.patch.object(core.urllib.request, "urlopen", side_effect=fake_urlopen):
                payload = core.post_grok_responses(config, "hello")

        self.assertEqual(payload, {"output": []})
        self.assertEqual(seen["url"], "https://cli-chat-proxy.test/v1/responses")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer token")
        self.assertEqual(seen["headers"]["X-xai-token-auth"], "xai-grok-cli")
        self.assertEqual(seen["headers"]["X-grok-model-override"], "grok-test")
        self.assertEqual(seen["headers"]["X-grok-client-version"], "0.2.test")
        self.assertEqual(seen["body"]["model"], "grok-test")
        self.assertEqual(seen["body"]["input"], "hello")
        self.assertEqual(seen["body"]["tools"], [{"type": "web_search"}])
        self.assertEqual(seen["body"]["stream"], False)
        self.assertEqual(seen["timeout"], 1)

    def test_parse_grok_response_uses_citations_then_search_sources(self):
        payload = {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "type": "search",
                        "sources": [
                            {"type": "url", "url": "https://fallback.test"},
                            {"type": "url", "url": "https://one.test"},
                        ],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "summary",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://one.test",
                                    "title": "One",
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://two.test",
                                    "title": "Two",
                                },
                            ],
                        }
                    ],
                },
            ]
        }

        result = core.parse_grok_response(payload, limit=3)
        web = result["data"]["web"]

        self.assertEqual(result["providersUsed"], ["grok"])
        self.assertEqual([item["url"] for item in web], [
            "https://one.test",
            "https://two.test",
            "https://fallback.test",
        ])
        self.assertEqual(web[0]["title"], "One")
        self.assertEqual(web[0]["description"], "summary")
        self.assertEqual(web[0]["provider"], "grok")

    def test_parse_grok_response_applies_limit(self):
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "summary",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://one.test",
                                    "title": "One",
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://two.test",
                                    "title": "Two",
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        result = core.parse_grok_response(payload, limit=1)

        self.assertEqual([item["url"] for item in result["data"]["web"]], ["https://one.test"])

    def test_parse_grok_response_raises_on_error_field(self):
        payload = {"error": {"message": "bad request"}}

        with self.assertRaisesRegex(core.UpstreamError, "bad request"):
            core.parse_grok_response(payload, limit=5)

    def test_parse_grok_response_tolerates_malformed_or_empty_output(self):
        malformed = core.parse_grok_response({"output": {"not": "a list"}}, limit=5)
        empty = core.parse_grok_response({"output": []}, limit=5)

        self.assertEqual(malformed["data"]["web"], [])
        self.assertEqual(empty["data"]["web"], [])


class CliTests(unittest.TestCase):
    def test_cli_login_antigravity_prints_result_json(self):
        result = core.AntigravityLoginResult(
            auth_file=Path("/tmp/antigravity-user@example.test.json"),
            email="user@example.test",
            project_id="project",
        )
        stdout = StringIO()

        with (
            mock.patch.object(cli, "load_default_env"),
            mock.patch.object(cli.Config, "from_env") as from_env,
            mock.patch.object(cli, "login_antigravity", return_value=result) as login,
            redirect_stdout(stdout),
        ):
            status = cli.main(["--login-antigravity", "--antigravity-callback-port", "0"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(status, 0)
        from_env.assert_called_once_with(provider_override="antigravity")
        login.assert_called_once_with(
            from_env.return_value,
            callback_port=0,
            manual_callback=False,
            callback_url="",
        )
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["provider"], "antigravity")
        self.assertEqual(payload["authFile"], "/tmp/antigravity-user@example.test.json")
        self.assertEqual(payload["email"], "user@example.test")
        self.assertEqual(payload["projectId"], "project")

    def test_cli_login_antigravity_passes_manual_callback_args(self):
        result = core.AntigravityLoginResult(
            auth_file=Path("/tmp/antigravity-user@example.test.json"),
            email="user@example.test",
            project_id="project",
        )
        stdout = StringIO()
        callback_url = "http://localhost:51121/oauth-callback?code=code&state=state"

        with (
            mock.patch.object(cli, "load_default_env"),
            mock.patch.object(cli.Config, "from_env") as from_env,
            mock.patch.object(cli, "login_antigravity", return_value=result) as login,
            redirect_stdout(stdout),
        ):
            status = cli.main(
                [
                    "--login-antigravity",
                    "--antigravity-manual-callback",
                    "--antigravity-callback-url",
                    callback_url,
                ]
            )

        self.assertEqual(status, 0)
        login.assert_called_once_with(
            from_env.return_value,
            callback_port=51121,
            manual_callback=True,
            callback_url=callback_url,
        )

    def test_cli_provider_override_accepts_comma_list(self):
        stdout = StringIO()
        result = {
            "success": True,
            "provider": "groundfetch",
            "providersUsed": ["gemini", "grok"],
            "data": {"web": []},
        }

        with (
            mock.patch.object(cli, "load_default_env"),
            mock.patch.object(cli.Config, "from_env") as from_env,
            mock.patch.object(cli, "search", return_value=result) as search,
            redirect_stdout(stdout),
        ):
            status = cli.main(["--query", "hello", "--provider", "gemini,grok"])

        self.assertEqual(status, 0)
        from_env.assert_called_once_with(provider_override="gemini,grok")
        search.assert_called_once_with("hello", limit=5, config=from_env.return_value)
        self.assertEqual(json.loads(stdout.getvalue())["providersUsed"], ["gemini", "grok"])


class ParseTests(unittest.TestCase):
    def test_parse_response_deduplicates_and_limits_results(self):
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "summary"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "One", "uri": "https://one.test"}},
                            {"web": {"title": "One Again", "uri": "https://one.test"}},
                            {"web": {"title": "Two", "uri": "https://two.test"}},
                        ]
                    },
                }
            ]
        }

        result = core.parse_response(payload, limit=2, user_agent="test")
        web = result["data"]["web"]

        self.assertEqual(result["provider"], "groundfetch")
        self.assertEqual(len(web), 2)
        self.assertEqual(web[0]["url"], "https://one.test")
        self.assertEqual(web[1]["url"], "https://two.test")
        self.assertEqual(web[0]["description"], "summary")

    def test_search_clamps_limit_and_strips_query(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
        )
        payload = {"candidates": [{"groundingMetadata": {"groundingChunks": []}}]}
        with mock.patch.object(core, "post_generate_content", return_value=payload) as post:
            result = core.search("  hello  ", limit=99, config=config)

        self.assertTrue(result["success"])
        post.assert_called_once_with(config, "hello")

    def test_search_aggregates_providers_with_dedupe_and_round_robin_order(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            providers=(core.PROVIDER_GEMINI, core.PROVIDER_GROK),
        )
        gemini_payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "gemini summary"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "One", "uri": "https://one.test"}},
                            {"web": {"title": "Shared", "uri": "https://shared.test"}},
                        ]
                    },
                }
            ]
        }
        grok_payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "grok summary",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://shared.test",
                                    "title": "Shared Grok",
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://two.test",
                                    "title": "Two",
                                },
                            ],
                        }
                    ],
                }
            ]
        }

        with (
            mock.patch.object(core, "post_generate_content", return_value=gemini_payload),
            mock.patch.object(core, "post_grok_responses", return_value=grok_payload),
        ):
            result = core.search("hello", limit=5, config=config)

        web = result["data"]["web"]
        self.assertEqual(result["providersUsed"], ["gemini", "grok"])
        self.assertEqual([item["url"] for item in web], [
            "https://one.test",
            "https://shared.test",
            "https://two.test",
        ])
        self.assertEqual([item["position"] for item in web], [1, 2, 3])
        self.assertEqual([item["provider"] for item in web], ["gemini", "grok", "grok"])

    def test_search_aggregation_returns_partial_success_when_one_provider_fails(self):
        config = core.Config(
            api_key="",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            providers=(core.PROVIDER_GEMINI, core.PROVIDER_GROK),
        )
        grok_payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "grok summary",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://two.test",
                                    "title": "Two",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        with (
            mock.patch.object(core, "post_generate_content") as gemini_post,
            mock.patch.object(core, "post_grok_responses", return_value=grok_payload),
            redirect_stderr(StringIO()),
        ):
            result = core.search("hello", limit=5, config=config)

        gemini_post.assert_not_called()
        self.assertEqual(result["providersUsed"], ["grok"])
        self.assertEqual(result["data"]["web"][0]["url"], "https://two.test")
        self.assertEqual(result["data"]["web"][0]["provider"], "grok")

    def test_search_aggregation_records_unexpected_worker_exception(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            providers=(core.PROVIDER_GEMINI, core.PROVIDER_GROK),
        )
        grok_result = {
            "success": True,
            "provider": "groundfetch",
            "providersUsed": [core.PROVIDER_GROK],
            "data": {
                "web": [
                    {
                        "title": "Two",
                        "url": "https://two.test",
                        "description": "",
                        "position": 1,
                        "provider": core.PROVIDER_GROK,
                    }
                ]
            },
        }

        def fake_search_with_provider(config, query, limit, provider):
            if provider == core.PROVIDER_GEMINI:
                raise TimeoutError("slow")
            return grok_result

        stderr = StringIO()
        with (
            mock.patch.object(
                core,
                "search_with_provider",
                side_effect=fake_search_with_provider,
            ),
            redirect_stderr(stderr),
        ):
            result = core.search("hello", limit=5, config=config)

        self.assertEqual(result["providersUsed"], ["grok"])
        self.assertIn("provider gemini failed", stderr.getvalue())
        self.assertIn("gemini failed: slow", stderr.getvalue())

    def test_search_aggregation_all_providers_fail_raises_first_provider_error(self):
        config = core.Config(
            api_key="key",
            base_url="https://example.test/v1beta",
            model="model",
            timeout=1,
            user_agent="agent",
            providers=(core.PROVIDER_GROK, core.PROVIDER_GEMINI),
        )

        def fake_search_with_provider(config, query, limit, provider):
            if provider == core.PROVIDER_GROK:
                raise TimeoutError("slow")
            raise core.ConfigError("gemini missing")

        with mock.patch.object(
            core,
            "search_with_provider",
            side_effect=fake_search_with_provider,
        ):
            with self.assertRaisesRegex(core.UpstreamError, "grok failed: slow"):
                core.search("hello", limit=5, config=config)


if __name__ == "__main__":
    unittest.main()
