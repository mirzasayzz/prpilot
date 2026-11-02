"""
Vercel serverless function: queued webhook worker endpoint.

Called by the operator's scheduler (see NOTES.md), not by GitHub
directly. It takes one stored webhook event and runs it through
api/review_worker.process_event.

Authentication:
- If CRON_SECRET is set, the request must carry header
  X-Cron-Secret exactly equal to it, or an Authorization header
  "Bearer <CRON_SECRET>" (the form Vercel Cron sends), compared with
  hmac.compare_digest. Anything else gets 401.
- If CRON_SECRET is not set, every request gets 401. There is no
  unauthenticated mode, because this endpoint can post reviews and
  spend LLM quota.
- GET is supported for Vercel Cron only: an authorised GET runs one
  sweep (oldest pending event). POST with a delivery id is the
  normal path; POST with an empty body is also a sweep.

Request body (JSON):
- {"delivery_id": "<X-GitHub-Delivery value>"} processes that event.
- {} or no delivery_id processes the oldest pending event (sweep
  mode), so a scheduler that cannot pass a per-event id can still
  drain the queue one event per call. Sweep mode uses the
  get_oldest_pending_event helper in db/client.py.

Retry handling:
- process_event returns processed, skipped, or failed.
- processed and skipped both mark the event done: the worker already
  set status processed, or set it to processed with a skip reason.
- failed increments attempts. After 3 attempts the event is marked
  dead_letter and will not be retried. The generic reason is stored,
  never exception text.
- An already processed event returns 200 without reprocessing.

This endpoint never returns exception text and never posts anything
to GitHub itself; all GitHub output happens inside review_worker.
"""

import asyncio
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_ATTEMPTS = 3


def _db(fn, *args, **kwargs):
    return asyncio.run(fn(*args, **kwargs))


def _authorised(handler):
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        return False
    presented = handler.headers.get("X-Cron-Secret", "")
    if presented:
        return hmac.compare_digest(secret, presented)
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return hmac.compare_digest(secret, auth[len("Bearer "):])
    return False


class handler(BaseHTTPRequestHandler):
    """Worker endpoint handler."""

    def log_message(self, *args):
        pass

    def _write_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not _authorised(self):
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
        self._process_data(data)

    def do_GET(self):
        """Vercel Cron sends GET: an authorised GET is one sweep."""
        if not _authorised(self):
            self._write_json({"error": "Unauthorised"}, status=401)
            return
        self._process_data({})

    def _process_data(self, data):
        delivery_id = data.get("delivery_id")
        try:
            from db.client import (
                get_oldest_pending_event,
                get_webhook_event,
                update_webhook_event,
            )
            from api.review_worker import process_event

            if not delivery_id:
                pending = _db(get_oldest_pending_event)
                if not pending:
                    self._write_json({"status": "empty"})
                    return
                delivery_id = pending.get("delivery_id")
            event = _db(get_webhook_event, delivery_id)
            if not event:
                self._write_json({"error": "Event not found"}, status=404)
                return
            if event.get("status") == "processed":
                self._write_json({"status": "already_processed"})
                return
            if event.get("status") == "dead_letter":
                self._write_json({"status": "dead_letter"})
                return

            result = process_event(delivery_id)
            if result.get("status") in ("processed", "skipped"):
                self._write_json(
                    {"status": result["status"], "delivery_id": delivery_id}
                )
                return

            # Failed: count the attempt, dead-letter after the limit.
            attempts = int(event.get("attempts") or 0) + 1
            if attempts >= MAX_ATTEMPTS:
                _db(
                    update_webhook_event, delivery_id,
                    status="dead_letter", attempts=attempts,
                    error_message="max_attempts_reached",
                )
                self._write_json(
                    {"status": "dead_letter", "delivery_id": delivery_id}
                )
            else:
                _db(
                    update_webhook_event, delivery_id,
                    status="failed", attempts=attempts,
                    error_message=result.get("reason") or "review_failed",
                )
                self._write_json(
                    {"status": "failed", "delivery_id": delivery_id,
                     "attempts": attempts}
                )
        except Exception:
            self._write_json({"error": "Could not process event"}, status=500)

