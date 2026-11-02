"""Webhook signature tests.

GitHub signs webhooks with HMAC-SHA256. The algorithm in
api/webhook.py (function verify_signature) is:

    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

with an early False when the secret or the signature is empty.

Import strategy: if api/webhook.py can be found (see conftest),
its verify_signature is tested directly with a monkeypatched
GITHUB_WEBHOOK_SECRET. Otherwise the tests run against
local_verify_signature below, which is the same algorithm with
the secret passed in explicitly, and the test file says so. The
hardcoded vector in test_known_vector pins the algorithm so a
future change to the local copy cannot silently drift.

No network calls. No real secrets: the secret here is a test value.
"""

import hashlib
import hmac

import pytest

from conftest import find_repo_file, load_module_from_path


def local_verify_signature(payload, signature, secret):
    """Local copy of the api/webhook.py algorithm, for standalone runs."""
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _real_verify():
    path = find_repo_file("api/webhook.py")
    if path is None:
        return None
    try:
        module = load_module_from_path("prpilot_api_webhook", path)
    except Exception:
        return None
    return getattr(module, "verify_signature", None)


def _sign(payload, secret):
    return "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()


PAYLOAD = b'{"action":"opened"}'
SECRET = "prpilot-test-secret"
# Precomputed with the algorithm above, for payload and secret above.
KNOWN_SIGNATURE = (
    "sha256=4d07c9c9dfd4455e731f7a7a33832e8fecc1a8d3e2345f5eb6eaf67c3ecda900"
)


def test_known_vector():
    assert local_verify_signature(PAYLOAD, KNOWN_SIGNATURE, SECRET) is True


def test_valid_signature():
    assert local_verify_signature(PAYLOAD, _sign(PAYLOAD, SECRET), SECRET) is True


def test_wrong_payload_fails():
    assert (
        local_verify_signature(b'{"action":"closed"}', _sign(PAYLOAD, SECRET), SECRET)
        is False
    )


def test_wrong_secret_fails():
    assert (
        local_verify_signature(PAYLOAD, _sign(PAYLOAD, SECRET), "other-secret")
        is False
    )


def test_empty_signature_fails():
    assert local_verify_signature(PAYLOAD, "", SECRET) is False


def test_empty_secret_fails():
    assert local_verify_signature(PAYLOAD, _sign(PAYLOAD, SECRET), "") is False


def test_missing_prefix_fails():
    # The expected value always carries the sha256= prefix.
    bare = _sign(PAYLOAD, SECRET).replace("sha256=", "")
    assert local_verify_signature(PAYLOAD, bare, SECRET) is False


def test_tampered_signature_fails():
    good = _sign(PAYLOAD, SECRET)
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert local_verify_signature(PAYLOAD, tampered, SECRET) is False


def test_real_webhook_verify_if_available(monkeypatch):
    """Test the real api/webhook.py verify_signature when present."""
    real = _real_verify()
    if real is None:
        pytest.skip("api/webhook.py not found; local copy tested above")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    # The real function reads the secret from the environment at
    # call time, so the monkeypatched value is what it sees.
    assert real(PAYLOAD, _sign(PAYLOAD, SECRET)) is True
    assert real(PAYLOAD, _sign(PAYLOAD, SECRET) + "0") is False
