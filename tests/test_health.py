"""Health endpoint tests, against the drafted api/index.py.

These tests load api/index.py from the draft directory (or the
repo root, see conftest). If that file cannot be found, the tests
are skipped with a clear reason.

Rules tested:

* All required variables present: status is "healthy".
* Any required variable missing: status is "degraded", and the
  missing list contains names only.
* The output never contains a secret value, even when the test
  uses a distinctive fake secret.
* Supabase reachability is honestly reported as "not_checked".
* A missing LLM key is reported in its check but does not by
  itself change the top-level status when required variables
  are complete, because providers are optional in the chain.
"""

import json

import pytest

from conftest import find_repo_file, load_module_from_path

REQUIRED = {
    "GITHUB_APP_ID": "test-app-id",
    "GITHUB_PRIVATE_KEY": "test-private-key-value",
    "GITHUB_WEBHOOK_SECRET": "test-webhook-secret-value",
    "SUPABASE_URL": "https://example.test",
    "SUPABASE_SERVICE_KEY": "test-supabase-service-key",
    "ENCRYPTION_KEY": "test-encryption-key-value",
    "CONFIG_TOKEN_SECRET": "test-config-token-secret",
    "CRON_SECRET": "test-cron-secret-value",
}


def _load_index():
    path = find_repo_file("api/index.py")
    if path is None:
        pytest.skip("api/index.py not found")
    return load_module_from_path("prpilot_api_index", path)


def test_healthy_when_all_required_present(monkeypatch):
    module = _load_index()
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    payload = module.build_health()
    assert payload["status"] == "healthy"
    assert payload["missing"] == []
    assert payload["version"] == "1.0.0"
    assert payload["checks"]["supabase_reachability"]["status"] == "not_checked"


def test_degraded_when_required_missing(monkeypatch):
    module = _load_index()
    for name, value in REQUIRED.items():
        if name != "GITHUB_WEBHOOK_SECRET":
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    payload = module.build_health()
    assert payload["status"] == "degraded"
    assert payload["missing"] == ["GITHUB_WEBHOOK_SECRET"]


def test_output_never_contains_secret_values(monkeypatch):
    module = _load_index()
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    payload = module.build_health()
    dumped = json.dumps(payload)
    for value in REQUIRED.values():
        assert value not in dumped
    # Names may appear, values must not.
    assert "GITHUB_WEBHOOK_SECRET" in dumped or payload["missing"] == []


def test_llm_missing_is_reported_not_fatal(monkeypatch):
    module = _load_index()
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "OPENROUTER_API_KEY_1",
        "OPENROUTER_API_KEY_2",
        "LLMAPI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    payload = module.build_health()
    assert payload["status"] == "healthy"
    assert payload["checks"]["llm_env"]["status"] == "missing"
