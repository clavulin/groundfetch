import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from groundfetch import core


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
        self.assertEqual(config.base_url, "https://example.test/v1beta")
        self.assertEqual(config.model, "model")
        self.assertEqual(config.timeout, 7)
        self.assertEqual(config.user_agent, "agent")

    def test_config_rejects_missing_groundfetch_key(self):
        env = {
            "GROUNDFETCH_BASE_URL": "https://example.test/v1beta",
            "OTHER_API_KEY": "ignored",
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


if __name__ == "__main__":
    unittest.main()
