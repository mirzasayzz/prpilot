"""
Vercel serverless function: read-only dashboard API.

Same token authentication as api/config.py (see api/auth.py): a
valid signed config token, as a config_token query parameter or an
Authorization Bearer token. No token, no data. The installation id
comes from the token, never from the request.

Returns, and nothing more:
- owner login, enabled flag, and llm_provider (or null when unset)
- a settings summary: the four review toggles and auto_approve,
  using the original stored keys review_style, review_security,
  review_performance, review_logic, plus short aliases for the page
- quota for non-owners: used reviews in the last 24 hours, the 25
  per day cap, and remaining count. Owners are reported as unlimited
  with used set to null, so the page can show "Unlimited" instead of
  a misleading number.
- recent reviews, newest first, from existing review records
  (see list_recent_reviews in db/client.py), limited to 20
- counts: total reviews in the window and total issues found across
  the recent reviews shown

Never returned: any API key, encrypted key material, token, or
exception text. CORS follows the same single-origin rule as
api/config.py: https://prpilot-one.vercel.app only.
"""

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

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

OWNER_LOGINS = {
    s.strip().lower()
    for s in os.environ.get("PRPILOT_OWNER_LOGINS", "mirzasayzz").split(",")
    if s.strip()
}

try:
    FREE_DAILY_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", "25"))
except ValueError:
    FREE_DAILY_LIMIT = 25

try:
    USAGE_WINDOW_HOURS = int(os.environ.get("USAGE_WINDOW_HOURS", "24"))
except ValueError:
    USAGE_WINDOW_HOURS = 24


def _db(fn, *args, **kwargs):
    return asyncio.run(fn(*args, **kwargs))


class handler(BaseHTTPRequestHandler):
    """Handle read-only dashboard API requests."""

    def log_message(self, *args):
        pass

    def _cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin == CANONICAL_ORIGIN:
            return {
                "Access-Control-Allow-Origin": CANONICAL_ORIGIN,
                "Access-Control-Allow-Methods": "GET, OPTIONS",
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

    def do_OPTIONS(self):
        self.send_response(200)
        for key, value in self._cors_headers().items():
            self.send_header(key, value)
        self.end_headers()

    def do_GET(self):
        try:
            from api.auth import extract_token, verify_token

            installation_id = verify_token(extract_token(self))
        except Exception:
            installation_id = None
        if not installation_id:
            self._write_json({"error": "Unauthorised"}, status=401)
            return
        try:
            from db.client import (
                count_reviews_since,
                get_installation,
                list_recent_reviews,
            )

            inst = _db(get_installation, int(installation_id))
            if not inst:
                self._write_json(
                    {
                        "installation_id": installation_id,
                        "owner": "",
                        "enabled": True,
                        "llm_provider": None,
                        "settings": dict(DEFAULT_SETTINGS),
                        "quota": {
                            "used": 0,
                            "limit": FREE_DAILY_LIMIT,
                            "remaining": FREE_DAILY_LIMIT,
                            "unlimited": False,
                        },
                        "recent_reviews": [],
                        "counts": {"reviews": 0, "issues_found": 0},
                    }
                )
                return
            stored = inst.get("settings") or {}
            settings = dict(DEFAULT_SETTINGS)
            for key, value in stored.items():
                canonical = SETTING_ALIASES.get(key, key)
                if canonical in DEFAULT_SETTINGS:
                    settings[canonical] = bool(value)
            for short, canonical in SETTING_ALIASES.items():
                settings[short] = settings[canonical]

            owner_login = inst.get("owner_login", "")
            is_owner = owner_login.strip().lower() in OWNER_LOGINS
            used = None
            if not is_owner:
                try:
                    used = _db(count_reviews_since, inst["id"], USAGE_WINDOW_HOURS)
                except Exception:
                    used = None
            if is_owner:
                quota = {
                    "used": None,
                    "limit": None,
                    "remaining": None,
                    "unlimited": True,
                }
            elif used is None:
                quota = {
                    "used": None,
                    "limit": FREE_DAILY_LIMIT,
                    "remaining": None,
                    "unlimited": False,
                }
            else:
                quota = {
                    "used": int(used),
                    "limit": FREE_DAILY_LIMIT,
                    "remaining": max(0, FREE_DAILY_LIMIT - int(used)),
                    "unlimited": False,
                }

            try:
                recent = _db(list_recent_reviews, inst["id"], 20)
            except Exception:
                recent = []
            safe_reviews = []
            total_issues = 0
            for row in recent or []:
                if not isinstance(row, dict):
                    continue
                issues = row.get("issues_found") or 0
                try:
                    issues = int(issues)
                except (TypeError, ValueError):
                    issues = 0
                total_issues += issues
                safe_reviews.append(
                    {
                        "repo_full_name": row.get("repo_full_name", ""),
                        "pr_number": row.get("pr_number"),
                        "pr_title": row.get("pr_title", ""),
                        "files_reviewed": row.get("files_reviewed"),
                        "issues_found": issues,
                        "status": row.get("status", ""),
                        "created_at": row.get("created_at"),
                    }
                )
            self._write_json(
                {
                    "installation_id": installation_id,
                    "owner": owner_login,
                    "enabled": inst.get("enabled", True),
                    "llm_provider": inst.get("llm_provider") or None,
                    "settings": settings,
                    "quota": quota,
                    "recent_reviews": safe_reviews,
                    "counts": {
                        "reviews": len(safe_reviews),
                        "issues_found": total_issues,
                    },
                }
            )
        except Exception:
            self._write_json({"error": "Could not load dashboard"}, status=500)
