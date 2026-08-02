"""
Vercel serverless function: Configuration API.
Handles saving installation settings and API keys to Supabase.
"""
import os
import sys
import json
import asyncio
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _db(fn, *args, **kwargs):
    """Run an async db.client coroutine from this sync handler."""
    return asyncio.run(fn(*args, **kwargs))


DEFAULT_SETTINGS = {
    "review_style": True,
    "review_security": True,
    "review_performance": True,
    "review_logic": True,
    "auto_approve": False
}


class handler(BaseHTTPRequestHandler):
    """Handle configuration API requests."""

    def _set_cors_headers(self):
        """Set CORS headers for browser requests."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _write_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        """Get installation settings or health check."""
        # Parse query parameters
        query = self.path.split("?")[1] if "?" in self.path else ""
        params = parse_qs(query)

        installation_id = params.get("installation_id", [None])[0]

        if not installation_id:
            # Health check
            self._write_json({
                "status": "healthy",
                "service": "PRPilot Config API"
            })
            return

        # Read installation from Supabase (best-effort)
        try:
            from db.client import get_installation
            inst = _db(get_installation, int(installation_id))
        except Exception:
            inst = None

        if inst:
            settings = inst.get("settings") or DEFAULT_SETTINGS
            self._write_json({
                "installation_id": installation_id,
                "owner": inst.get("owner_login", ""),
                "enabled": inst.get("enabled", True),
                "has_api_key": bool(inst.get("api_key_encrypted")),
                "settings": settings
            })
        else:
            # No record yet - return defaults
            self._write_json({
                "installation_id": installation_id,
                "owner": "",
                "enabled": True,
                "has_api_key": False,
                "settings": DEFAULT_SETTINGS
            })

    def do_POST(self):
        """Update installation settings and/or API key."""
        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._write_json({"error": "Invalid JSON"}, status=400)
            return

        installation_id = data.get("installation_id")
        if not installation_id:
            self._write_json({"error": "Missing installation_id"}, status=400)
            return

        try:
            from db.client import (
                get_installation, create_installation,
                update_installation_api_key, update_installation_settings
            )

            inst = _db(get_installation, int(installation_id))
            if not inst:
                _db(create_installation, int(installation_id), data.get("owner", ""))

            if data.get("api_key"):
                _db(update_installation_api_key, int(installation_id), data["api_key"])

            if data.get("settings"):
                _db(update_installation_settings, int(installation_id), data["settings"])

            self._write_json({"status": "updated"})
        except Exception as e:
            self._write_json({"error": str(e)}, status=500)
