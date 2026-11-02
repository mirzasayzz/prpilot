"""
Vercel serverless function: GitHub App installation callback.

Replaces the original handler, which redirected to the config page with
a bare installation_id in the URL. That id is public knowledge for any
installed app, so it was never authentication.

New flow:
1. GitHub redirects here with installation_id and setup_action.
2. This handler verifies the installation is real by asking GitHub for
   an installation access token, using the same JWT flow already used
   in api/webhook.py. A made up installation id fails here.
   (No new SDK is introduced: jwt and httpx were already used there.)
3. Only on success, it issues a short lived signed config token
   (see api/auth.py) and redirects to
   /config.html?config_token=<token>.
4. Every failure path shows the same generic message. Exception text
   is never reflected to the browser, because it can leak host, key,
   or account details.

The installation access token obtained in step 2 is used only as proof
that the installation exists. It is discarded immediately and is never
put in a URL, a cookie, or a page.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse, quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GENERIC_ERROR_LOCATION = "/?error=install_failed"


def get_installation_access_token(installation_id):
    """Obtain a GitHub installation access token, or raise on failure.

    This is the JWT pattern already used in api/webhook.py: sign a JWT
    with GITHUB_APP_ID and GITHUB_PRIVATE_KEY, then exchange it for an
    installation token. The caller uses success alone as proof that the
    installation exists; the token itself is discarded.
    """
    import time

    import jwt
    import httpx

    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
    if not app_id or not private_key:
        raise ValueError("GitHub App credentials are not configured")
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id,
    }
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")
    headers = {
        "Authorization": "Bearer %s" % jwt_token,
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(
            "https://api.github.com/app/installations/%s/access_tokens"
            % installation_id,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["token"]


class handler(BaseHTTPRequestHandler):
    """Handle GitHub App installation callbacks."""

    def log_message(self, *args):
        # Keep serverless logs free of query strings, which may contain
        # a token if a user pastes a URL. Log only the method and path.
        pass

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            installation_id = params.get("installation_id", [None])[0]
            if not installation_id or not str(installation_id).isdigit():
                self._redirect(GENERIC_ERROR_LOCATION)
                return
            # Proof the installation is real. Any failure, including a
            # 404 for an unknown installation, lands in the generic path.
            token = get_installation_access_token(int(installation_id))
            if not token:
                self._redirect(GENERIC_ERROR_LOCATION)
                return
            from api.auth import issue_token

            config_token = issue_token(installation_id)
            if not config_token:
                self._redirect(GENERIC_ERROR_LOCATION)
                return
            self._redirect(
                "/config.html?config_token=%s" % quote(config_token, safe="")
            )
        except Exception:
            # Generic error only. Never include exception text, which
            # could leak configuration or account details.
            try:
                self._redirect(GENERIC_ERROR_LOCATION)
            except Exception:
                pass
