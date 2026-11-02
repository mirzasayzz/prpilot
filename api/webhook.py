"""
Vercel serverless function: GitHub webhook handler, ack-then-queue.

Replaces the original handler, which ran LLM calls inline, posted one
combined issue comment, reviewed at most 5 files truncated to 3000
chars, and leaked exception text in its 500 response.

New behaviour:
- Verify the HMAC signature, exactly as before.
- Accept only pull_request events with action opened, synchronize,
  or reopened. Everything else returns 200 and is ignored.
- Store the event in Supabase (see db/migrations/001) with the
  X-GitHub-Delivery header as the idempotency key. If that delivery
  id is already stored, return 200 immediately without reprocessing
  and without storing a duplicate.
- Return 200 immediately after storing. No LLM call, no GitHub
  comment, and no review runs in this handler. Processing happens in
  api/process.py, which calls api/review_worker.process_event.
- Generic responses only. No exception text is ever returned.

If storing fails, the handler returns 500 with a generic body, so
GitHub will redeliver. That is deliberate: a lost event is worse
than a redelivery, and redelivery is safe because delivery id dedup
prevents double processing.
"""

import hashlib
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACCEPTED_ACTIONS = ("opened", "synchronize", "reopened")


def verify_signature(payload, signature):
    """Verify a GitHub webhook signature. False when secret is missing."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler."""

    def log_message(self, *args):
        pass

    def _write_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""

        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, signature):
            self._write_json({"error": "Invalid signature"}, status=401)
            return

        delivery_id = self.headers.get("X-GitHub-Delivery", "")
        if not delivery_id:
            self._write_json({"error": "Missing delivery id"}, status=400)
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._write_json({"error": "Invalid JSON"}, status=400)
            return

        event_type = self.headers.get("X-GitHub-Event", "")
        if event_type != "pull_request":
            self._write_json({"message": "Event ignored"})
            return

        action = payload.get("action", "")
        if action not in ACCEPTED_ACTIONS:
            self._write_json({"message": "Action ignored"})
            return

        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        installation = payload.get("installation", {})
        pr_number = pr.get("number")
        owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        installation_id = installation.get("id")
        if not all([pr_number, owner, repo_name, installation_id]):
            self._write_json({"error": "Missing PR data"}, status=400)
            return

        repo_full_name = "%s/%s" % (owner, repo_name)
        try:
            import asyncio

            from db.client import get_webhook_event, store_webhook_event

            def _db(fn, *args, **kwargs):
                return asyncio.run(fn(*args, **kwargs))

            existing = _db(get_webhook_event, delivery_id)
            if existing:
                # Idempotency: already stored, never process twice.
                self._write_json({"status": "already_queued"})
                return
            _db(
                store_webhook_event,
                delivery_id,
                int(installation_id),
                repo_full_name,
                int(pr_number),
                action,
                json.dumps(payload),
            )
        except Exception:
            # Generic 500 only, so GitHub redelivers. Dedup on
            # redelivery prevents a duplicate review.
            self._write_json({"error": "Could not queue event"}, status=500)
            return

        self._write_json({"status": "queued", "delivery_id": delivery_id})

    def do_GET(self):
        """Health check endpoint."""
        self._write_json({"status": "healthy", "service": "PRPilot Webhook"})
