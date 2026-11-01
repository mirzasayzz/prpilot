"""Main API entrypoint for Vercel: real health endpoint.

This is a stdlib http.server handler, not FastAPI. The old docstring
claiming FastAPI detection was wrong and has been removed.

GET /api/health (also / and /health) returns a JSON object with a
top-level status of "healthy" or "degraded" and one check per area.
Only variable names appear in the output, never values, and no
exception text is ever included.

Supabase reachability is reported honestly as "not_checked":
db/client.py as read provides no cheap read-only health probe, and
this endpoint does not run a Supabase query. Adding a real probe is
a follow-up, not something this file pretends to do. The same
applies to GitHub and LLM reachability: this endpoint checks that
the needed environment variables are present, it does not call
GitHub or any LLM provider.

HTTP status: 200 when healthy, 503 when degraded, so a load
balancer or uptime check can use the code as well as the body.
Callers that only need the body should read the "status" field.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from api.env_check import validate as _validate_env
except Exception:
    try:
        from env_check import validate as _validate_env
    except Exception:
        _validate_env = None

try:
    from api.logging_util import get_logger, log_event
except Exception:
    try:
        from logging_util import get_logger, log_event
    except Exception:
        get_logger = None
        log_event = None

VERSION = "1.0.0"
SERVICE = "PRPilot API"

_GITHUB_VARS = ("GITHUB_APP_ID", "GITHUB_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET")
_SUPABASE_VARS = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
_LLM_VARS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEYS",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY_1",
    "OPENROUTER_API_KEY_2",
    "LLMAPI_API_KEY",
)


def _is_set(env, name):
    value = env.get(name)
    return value is not None and str(value).strip() != ""


def _presence_check(env, names):
    present = [name for name in names if _is_set(env, name)]
    missing = [name for name in names if not _is_set(env, name)]
    return {
        "status": "ok" if not missing else "missing",
        "present": present,
        "missing": missing,
    }


def build_health(env=None):
    """Build the health payload. Never includes values or exceptions.

    Returns a dict with "status", "version", "service", "checks",
    and "missing" (required variable names only).
    """
    if env is None:
        env = os.environ
    try:
        if _validate_env is not None:
            validation = _validate_env(env)
            missing = list(validation.get("missing", []))
        else:
            required = (
                "GITHUB_APP_ID",
                "GITHUB_PRIVATE_KEY",
                "GITHUB_WEBHOOK_SECRET",
                "SUPABASE_URL",
                "SUPABASE_SERVICE_KEY",
                "ENCRYPTION_KEY",
                "CONFIG_TOKEN_SECRET",
                "CRON_SECRET",
            )
            missing = [name for name in required if not _is_set(env, name)]

        github = _presence_check(env, _GITHUB_VARS)
        supabase_env = _presence_check(env, _SUPABASE_VARS)
        llm = _presence_check(env, _LLM_VARS)
        encryption = _presence_check(env, ("ENCRYPTION_KEY",))

        checks = {
            "github_app": github,
            "supabase_env": supabase_env,
            "supabase_reachability": {
                "status": "not_checked",
                "detail": (
                    "No cheap read-only probe exists in db/client.py; "
                    "no Supabase query was attempted from this endpoint."
                ),
            },
            "llm_env": llm,
            "encryption_env": encryption,
        }
        # A missing LLM key alone does not degrade the service if
        # the required set is complete, because providers are
        # optional in the fallback chain. Report it, do not fail on it.
        status = "healthy" if not missing else "degraded"
        return {
            "status": status,
            "service": SERVICE,
            "version": VERSION,
            "checks": checks,
            "missing": missing,
            "endpoints": {
                "/api/webhook": "GitHub webhook handler",
                "/api/config": "Configuration API",
                "/api/install": "Installation callback",
                "/api/health": "Health endpoint",
            },
        }
    except Exception:
        # Never leak exception text. A failed check is degraded.
        return {
            "status": "degraded",
            "service": SERVICE,
            "version": VERSION,
            "checks": {
                "health_build": {"status": "error"},
            },
            "missing": [],
            "endpoints": {
                "/api/health": "Health endpoint",
            },
        }


class handler(BaseHTTPRequestHandler):
    """Root API handler."""

    def log_message(self, *args):
        # Keep Vercel logs clean; structured logging happens in do_GET.
        pass

    def _write_json(self, payload, status):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        """Health check endpoint."""
        path = self.path.split("?")[0]
        if path not in ("/", "/api/health", "/health"):
            self._write_json({"error": "Not found"}, status=404)
            return
        payload = build_health()
        http_status = 200 if payload.get("status") == "healthy" else 503
        if log_event is not None and get_logger is not None:
            try:
                logger = get_logger(__name__)
                log_event(
                    logger,
                    "info",
                    "health check",
                    status=payload.get("status"),
                    missing_count=len(payload.get("missing", [])),
                )
            except Exception:
                pass
        self._write_json(payload, status=http_status)
