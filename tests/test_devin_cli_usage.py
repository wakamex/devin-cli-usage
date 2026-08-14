from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import devin_cli_usage as devin_usage


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class DevinUsageTests(unittest.TestCase):
    def test_default_files_follow_xdg_data_home(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.dict(
                devin_usage.os.environ,
                {"XDG_DATA_HOME": temporary},
                clear=True,
            ),
        ):
            data_dir = Path(temporary) / "devin"
            self.assertEqual(
                devin_usage.get_credentials_file(), data_dir / "credentials.toml"
            )
            self.assertEqual(
                devin_usage.get_usage_file(), data_dir / "usage-limits.json"
            )

    def test_credentials_are_reread_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            credentials = Path(temporary) / "credentials.toml"
            credentials.write_text(
                'windsurf_api_key = "first"\napi_server_url = "https://server.codeium.com"\n'
            )
            with mock.patch.object(
                devin_usage, "DEFAULT_CREDENTIALS_FILE", credentials
            ):
                self.assertEqual(devin_usage.get_credentials()[0], "first")
                credentials.write_text(
                    'windsurf_api_key = "second"\napi_server_url = "https://server.codeium.com"\n'
                )
                self.assertEqual(devin_usage.get_credentials()[0], "second")

    def test_fetch_puts_api_key_in_request_metadata(self):
        payload = {"userStatus": {"planStatus": {}}}

        def fake_urlopen(request, timeout):
            body = json.loads(request.data)
            metadata = body["metadata"]
            self.assertEqual(metadata["apiKey"], "local-key")
            self.assertEqual(metadata["ideName"], "devin")
            self.assertEqual(metadata["ideVersion"], "3000.3.27")
            self.assertNotIn("Authorization", request.headers)
            self.assertEqual(timeout, 15)
            return FakeResponse(payload)

        with (
            mock.patch.object(
                devin_usage,
                "get_credentials",
                return_value=("local-key", "https://server.codeium.com"),
            ),
            mock.patch.object(devin_usage, "_devin_version", return_value="3000.3.27"),
            mock.patch.object(
                devin_usage.urllib.request, "urlopen", side_effect=fake_urlopen
            ),
        ):
            self.assertEqual(devin_usage.fetch_usage(), payload)

    def test_build_normalizes_quota_and_credit_fields(self):
        payload = {
            "planInfo": {"planName": "Pro", "monthlyPromptCredits": 1000},
            "userStatus": {
                "planStatus": {
                    "dailyQuotaRemainingPercent": 75,
                    "dailyQuotaResetAtUnix": 2_000_000_000,
                    "weeklyQuotaRemainingPercent": "50",
                    "availablePromptCredits": "900",
                    "usedPromptCredits": 100,
                    "overageBalanceMicros": "0",
                }
            },
        }
        with mock.patch.object(devin_usage, "fetch_usage", return_value=payload):
            data = devin_usage.build_usage_json()
        self.assertEqual(data["status"], "live")
        self.assertEqual(data["plan"]["name"], "Pro")
        self.assertEqual(data["quotas"]["daily"]["remaining_pct"], 75)
        self.assertEqual(data["quotas"]["weekly"]["remaining_pct"], 50)
        self.assertEqual(data["credits"]["available_prompt"], 900)

    def test_non_https_server_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            credentials = Path(temporary) / "credentials.toml"
            credentials.write_text(
                'windsurf_api_key = "key"\napi_server_url = "http://server.codeium.com"\n'
            )
            with mock.patch.object(
                devin_usage, "DEFAULT_CREDENTIALS_FILE", credentials
            ):
                with self.assertRaises(RuntimeError):
                    devin_usage.get_credentials()

    def test_unauthorized_never_attempts_refresh(self):
        error = urllib.error.HTTPError("https://example.test", 401, "", {}, None)
        with (
            mock.patch.object(
                devin_usage,
                "get_credentials",
                return_value=("expired", "https://server.codeium.com"),
            ),
            mock.patch.object(devin_usage, "_devin_version", return_value="1.0.0"),
            mock.patch.object(devin_usage.urllib.request, "urlopen", side_effect=error),
        ):
            data = devin_usage.build_usage_json()
        self.assertEqual(data["status"], "unavailable")
        self.assertIn("sign in", data["error"])

    def test_stale_cache_is_returned_when_refresh_fails(self):
        cached = {
            "provider": "devin",
            "status": "live",
            "source": "devin_user_status_api",
            "retrieved_at": "2020-01-01T00:00:00+00:00",
            "quotas": {"daily": {"remaining_pct": 50}},
        }
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "usage.json"
            cache.write_text(json.dumps(cached))
            with (
                mock.patch.object(devin_usage, "DEFAULT_USAGE_FILE", cache),
                mock.patch.object(
                    devin_usage,
                    "build_usage_json",
                    return_value={"status": "unavailable", "error": "offline"},
                ),
            ):
                result = devin_usage.get_cached_usage()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["refresh_error"], "offline")


if __name__ == "__main__":
    unittest.main()
