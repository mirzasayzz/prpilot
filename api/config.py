"""
Vercel serverless function: Configuration API.

Replaces the original handler, which accepted a bare installation_id
and sent Access-Control-Allow-Origin: *.

New rules:
- GET and POST both require a valid signed config token (see
  api/auth.py), supplied as a config_token query parameter or as an
  Authorization Bearer token. There is no health check shortcut and no
  bare installation_id path: a request without a valid token gets 401.
- The installation id is taken from the verified token, never from the
  request body or from a separate query parameter. A body that names a
  different installation is ignored for identity purposes.
- CORS is restricted to the single canonical origin,
  https://prpilot-one.vercel.app. Any other Origin gets no CORS headers
  at all, so a browser on another site cannot read responses.
- llm_provider is persisted and returned. Only "gemini" and "groq"
  are accepted; anything else is a 400. The provider is stored
  separately from the API key, so the dashboard can show which
  provider is selected without ever exposing a key.
- Key deletion: POST with "api_key" present and empty (""), or with
  "delete_api_key" true, clears the stored key. This is the only way
  to remove a key through this endpoint.
- Settings: the stored canonical keys are the original ones,
  review_style, review_security, review_performance, review_logic,
  and auto_approve. For convenience, POST also accepts the short
  names style, security, performance, logic, and GET returns both
  spellings. Unknown settings keys are ignored, never stored.
- Errors are generic. The 500 body never includes exception text.

Existing db.client functions used here (already present in the repo,
seen in the original api/config.py): get_installation,
create_installation, update_installation_api_key,
update_installation_settings. New functions needed are described in
db/client.py: update_installation_llm_provider,
clear_installation_api_key. If those helpers are not yet applied, the
provider and delete paths fail closed with a generic 500 instead of
pretending the change was saved.
"""

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CANONICAL_ORIGIN = "https://prpilot-one.vercel.app"

DEFAULT_SETTINGS = {
    "review_style": True,
    "review_security": True,
    "review_performance": True,
    "review_logic": True,
    "auto_approve": False,
}

SETTING_ALIASES = {
    "style": "review_style",
    "security": "review_security",
    "performance": "review_performance",
    "logic": "review_logic",
}

ALLOWED_PROVIDERS = ("gemini", "groq")


def _db(fn, *args, **kwargs):
    """Run an async db.client coroutine from this sync handler."""
    return asyncio.run(fn(*args, **kwargs))


def _normalise_settings(raw):
    """Map short toggle names to canonical keys, drop unknowns."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key, value in raw.items():
        canonical = SETTING_ALIASES.get(key, key)
        if canonical in DEFAULT_SETTINGS:
            out[canonical] = bool(value)
    return out


def _settings_response(stored):
    """Return settings with both canonical and short toggle names."""
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        for key, value in stored.items():
            canonical = SETTING_ALIASES.get(key, key)
            if canonical in DEFAULT_SETTINGS:
                merged[canonical] = bool(value)
    response = dict(merged)
    for short, canonical in SETTING_ALIASES.items():
        response[short] = merged[canonical]
    return response


class handler(BaseHTTPRequestHandler):
    """Handle configuration API requests."""

    def log_message(self, *args):
        pass

    def _cors_headers(self):
        """Return CORS headers only for the canonical origin, else none."""
        origin = self.headers.get("Origin", "")
        if origin == CANONICAL_ORIGIN:
            return {
                "Access-Control-Allow-Origin": CANONICAL_ORIGIN,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Vary": "Origin",
            }
        return {}

    def _write_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _authenticated_installation_id(self):
        """Return the token installation id, or None when unauthorised."""
        try:
            from api.auth import extract_token, verify_token

            return verify_token(extract_token(self))
        except Exception:
            return None

    def do_OPTIONS(self):
        self.send_response(200)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self):
        installation_id = self._authenticated_installation_id()
        if not installation_id:
            self._write_json({"error": "Unauthorised"}, status=401)
            return
        try:
            from db.client import get_installation

            inst = _db(get_installation, int(installation_id))
        except Exception:
            self._write_json({"error": "Could not load configuration"}, status=500)
            return
        if inst:
            settings = inst.get("settings") or DEFAULT_SETTINGS
            self._write_json(
                {
                    "installation_id": installation_id,
                    "owner": inst.get("owner_login", ""),
                    "enabled": inst.get("enabled", True),
                    "has_api_key": bool(inst.get("api_key_encrypted")),
                    "llm_provider": inst.get("llm_provider") or None,
                    "settings": _settings_response(settings),
                }
            )
        else:
            self._write_json(
                {
                    "installation_id": installation_id,
                    "owner": "",
                    "enabled": True,
                    "has_api_key": False,
                    "llm_provider": None,
                    "settings": _settings_response(DEFAULT_SETTINGS),
                }
            )

    def do_POST(self):
        installation_id = self._authenticated_installation_id()
        if not installation_id:
            self._write_json({"error": "Unauthorised"}, status=401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._write_json({"error": "Invalid JSON"}, status=400)
            return
        if not isinstance(data, dict):
            self._write_json({"error": "Invalid JSON"}, status=400)
            return

        # Validate the provider before touching any stored state.
        provider = data.get("llm_provider")
        if provider is not None and provider not in ALLOWED_PROVIDERS:
            self._write_json(
                {"error": "llm_provider must be gemini or groq"}, status=400
            )
            return
        settings = _normalise_settings(data.get("settings"))
        wants_delete = bool(data.get("delete_api_key"))
        api_key_present = "api_key" in data
        api_key_value = data.get("api_key")

        try:
            from db.client import (
                create_installation,
                get_installation,
                update_installation_api_key,
                update_installation_settings,
            )

            inst = _db(get_installation, int(installation_id))
            if not inst:
                _db(
                    create_installation,
                    int(installation_id),
                    data.get("owner", ""),
                )
            if provider is not None:
                from db.client import update_installation_llm_provider

                _db(
                    update_installation_llm_provider,
                    int(installation_id),
                    provider,
                )
            if wants_delete or (api_key_present and api_key_value == ""):
                from db.client import clear_installation_api_key

                _db(clear_installation_api_key, int(installation_id))
            elif api_key_present and api_key_value:
                _db(
                    update_installation_api_key,
                    int(installation_id),
                    api_key_value,
                )
            if settings:
                _db(
                    update_installation_settings,
                    int(installation_id),
                    settings,
                )
            self._write_json({"status": "updated"})
        except Exception:
            # Generic 500 only. Never include exception text.
            self._write_json({"error": "Could not save configuration"}, status=500)
