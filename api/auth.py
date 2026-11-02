"""
Shared authentication helper for PRPilot config and dashboard endpoints.

Design: stateless signed config token, no database lookup and no session
store. A token proves only that the holder completed a verified install
redirect (see api/install.py) within the last hour. It is not a GitHub
token and it grants no GitHub API access.

Token format:
    <installation_id>.<expiry_unix>.<hmac_hex>

where hmac_hex is HMAC-SHA256, keyed by CONFIG_TOKEN_SECRET, over the
string "<installation_id>.<expiry_unix>".

Rules, all deliberate:
- If CONFIG_TOKEN_SECRET is not set, no token is issued and no token
  verifies. There is no fallback secret and no default value.
- Expiry is 1 hour (3600 seconds) from issue time.
- Verification uses hmac.compare_digest, never ==, for the signature.
- installation_id must be digits only. Anything else is rejected.
- This module never logs a token and never returns one except through
  issue_token, which the install handler calls after verifying the
  installation with GitHub.
"""

import hashlib
import hmac
import os
import time

TOKEN_TTL_SECONDS = 3600


def _secret():
    """Return the signing secret, or an empty string if it is not set."""
    return os.environ.get("CONFIG_TOKEN_SECRET", "")


def issue_token(installation_id):
    """Issue a signed token for an installation, or None if not possible.

    Returns None when the secret is missing or the installation id is
    not a digit string. Callers must treat None as "do not redirect
    with a token" and show a generic error instead.
    """
    secret = _secret()
    installation_id = str(installation_id or "").strip()
    if not secret or not installation_id.isdigit():
        return None
    expiry = int(time.time()) + TOKEN_TTL_SECONDS
    message = "%s.%d" % (installation_id, expiry)
    signature = hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return "%s.%s" % (message, signature)


def verify_token(token):
    """Verify a config token.

    Returns the installation id as a string on success, or None when
    the token is missing, malformed, expired, unsigned with the current
    secret, or built for a non-numeric installation id.
    """
    if not token or not isinstance(token, str):
        return None
    secret = _secret()
    if not secret:
        return None
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    installation_id, expiry_text, signature = parts
    if not installation_id.isdigit():
        return None
    try:
        expiry = int(expiry_text)
    except ValueError:
        return None
    if expiry <= int(time.time()):
        return None
    message = "%s.%s" % (installation_id, expiry_text)
    expected = hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    return installation_id


def extract_token(handler):
    """Extract a config token from a request handler.

    Accepts, in order: the Authorization header as "Bearer <token>", then
    the config_token query parameter. It never accepts a bare
    installation_id as proof of anything.
    """
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        candidate = auth[len("Bearer "):].strip()
        if candidate:
            return candidate
    try:
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(handler.path).query)
        values = query.get("config_token", [])
        if values:
            return values[0]
    except Exception:
        return None
    return None
