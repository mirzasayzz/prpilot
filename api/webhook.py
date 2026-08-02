"""
Vercel serverless function: GitHub webhook handler.
Receives pull_request events, runs AI code review, posts comments,
and stores review records in Supabase.
"""
import os
import sys
import json
import hmac
import hashlib
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler


def _db(fn, *args, **kwargs):
    """Run an async db.client coroutine from this sync handler."""
    return asyncio.run(fn(*args, **kwargs))


# ── Usage limiting ────────────────────────────────────────────────────
# The app owner (mirzasayzz) is unlimited. Every other installation is
# capped at FREE_DAILY_LIMIT reviews per day, tracked in Supabase.
OWNER_LOGINS = {s.strip() for s in os.environ.get("PRPILOT_OWNER_LOGINS", "mirzasayzz").split(",") if s.strip()}

try:
    FREE_DAILY_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", "25"))
except ValueError:
    FREE_DAILY_LIMIT = 25

try:
    USAGE_WINDOW_HOURS = int(os.environ.get("USAGE_WINDOW_HOURS", "24"))
except ValueError:
    USAGE_WINDOW_HOURS = 24


def _is_owner(account_login: str) -> bool:
    """True if the installing account is a PRPilot owner (unlimited)."""
    return (account_login or "").strip().lower() in {o.lower() for o in OWNER_LOGINS}


def _usage_allowed(installation_id) -> bool:
    """Check if this installation is under its daily review cap.
    Owner installations bypass the limit entirely. Best-effort: if the
    DB is unreachable, allow the review rather than break the flow.
    """
    if not installation_id:
        return True
    try:
        from db.client import count_reviews_since, get_installation
        inst = _db(get_installation, installation_id)
        if not inst:
            return True
        if _is_owner(inst.get("owner_login", "")):
            return True
        used = _db(count_reviews_since, inst["id"], USAGE_WINDOW_HOURS)
        return used < FREE_DAILY_LIMIT
    except Exception:
        # Fail-open: never block reviews because usage tracking is down.
        return True


def _store_review_record(installation_id, account_login, repo_full_name, pr_number, pr_title, commit_sha):
    """Create a pending review record in Supabase. Best-effort: never breaks the flow."""
    try:
        from db.client import create_installation, create_review, get_installation
        inst = _db(get_installation, installation_id)
        if not inst:
            _db(create_installation, installation_id, account_login or "")
            inst = _db(get_installation, installation_id)
        record = _db(create_review, inst["id"], repo_full_name, pr_number, pr_title, commit_sha)
        return record
    except Exception:
        return None


def _update_review_record(review_id, **fields):
    """Update a review record. Best-effort: never breaks the flow."""
    try:
        from db.client import update_review
        _db(update_review, review_id, **fields)
    except Exception:
        pass


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature."""
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected, signature)


def get_github_client(installation_id: int):
    """Get authenticated GitHub client for an installation."""
    import jwt
    import time
    import httpx
    
    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
    
    if not app_id or not private_key:
        raise Exception("Missing GITHUB_APP_ID or GITHUB_PRIVATE_KEY")
    
    # Create JWT
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": app_id
    }
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")
    
    # Get installation access token
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json"
    }
    
    with httpx.Client() as client:
        resp = client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers=headers
        )
        resp.raise_for_status()
        token = resp.json()["token"]
    
    return token


def get_pr_files(token: str, owner: str, repo: str, pr_number: int) -> list:
    """Get files changed in a PR."""
    import httpx
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    with httpx.Client() as client:
        resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=headers
        )
        resp.raise_for_status()
        return resp.json()


def get_file_content(token: str, owner: str, repo: str, path: str, ref: str) -> str:
    """Get file content from GitHub."""
    import httpx
    import base64
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    with httpx.Client() as client:
        resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}",
            headers=headers
        )
        if resp.status_code != 200:
            return ""
        
        data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
        return ""


def post_review_comment(token: str, owner: str, repo: str, pr_number: int, body: str):
    """Post a review comment on the PR."""
    import httpx
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    with httpx.Client() as client:
        resp = client.post(
            f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers=headers,
            json={"body": body}
        )
        resp.raise_for_status()


def run_ai_review(code: str, file_path: str) -> str:
    """Run AI review on code and return markdown comment."""
    from agents.llm_client import get_llm_client
    
    client = get_llm_client()
    
    prompt = f"""You are an expert code reviewer. Review this code for:
1. Security issues (hardcoded secrets, vulnerabilities)
2. Bug potential (logic errors, edge cases)
3. Best practices violations

Code file: {file_path}
```
{code[:3000]}
```

If issues found, list them in this format:
### 🔍 Code Review - {file_path}

**Issues Found:**
- 🔴 **Critical**: [description]
- 🟡 **Warning**: [description]
- 💡 **Suggestion**: [description]

If no issues, say "✅ No significant issues found."

Be concise. Focus on real problems, not style nitpicks."""

    try:
        response = client.generate(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Review failed for {file_path}: {str(e)}"


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler."""
    
    def do_POST(self):
        """Handle POST requests (GitHub webhooks)."""
        
        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        # Verify signature
        signature = self.headers.get("X-Hub-Signature-256", "")
        if not verify_signature(body, signature):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid signature"}).encode())
            return
        
        # Parse payload
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return
        
        # Check event type
        event_type = self.headers.get("X-GitHub-Event", "")
        if event_type != "pull_request":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Event ignored"}).encode())
            return
        
        # Check action
        action = payload.get("action", "")
        if action not in ["opened", "synchronize", "reopened"]:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": "Action ignored"}).encode())
            return
        
        # Extract PR info
        pr = payload.get("pull_request", {})
        repo = payload.get("repository", {})
        installation = payload.get("installation", {})
        
        pr_number = pr.get("number")
        head_sha = pr.get("head", {}).get("sha")
        owner = repo.get("owner", {}).get("login")
        repo_name = repo.get("name")
        installation_id = installation.get("id")
        
        if not all([pr_number, owner, repo_name, installation_id]):
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing PR data"}).encode())
            return
        
        # Who installed the app? (the account that owns this installation)
        account_login = installation.get("account", {}).get("login", owner)
        # Only count a review against the quota for new/open PRs, not every
        # synchronize push on the same PR (avoids one noisy PR burning the cap).
        counts_toward_limit = action in ("opened", "reopened")
        if counts_toward_limit and not _is_owner(account_login) and not _usage_allowed(installation_id):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "limit_reached",
                "message": f"Daily review limit ({FREE_DAILY_LIMIT}) reached for this installation. Please try again later or use your own API key."
            }).encode())
            return

        review_record = None
        try:
            # Store a pending review record in Supabase (best-effort)
            repo_full_name = f"{owner}/{repo_name}"
            review_record = _store_review_record(
                installation_id, account_login, repo_full_name, pr_number,
                pr.get("title", ""), head_sha
            )
            token = get_github_client(installation_id)
            
            # Get PR files
            files = get_pr_files(token, owner, repo_name, pr_number)
            
            # Filter to reviewable files
            reviewable_extensions = [".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb"]
            reviewable_files = [
                f for f in files 
                if any(f.get("filename", "").endswith(ext) for ext in reviewable_extensions)
                and f.get("status") != "removed"
            ]
            
            if not reviewable_files:
                if review_record:
                    _update_review_record(review_record["id"], files_reviewed=0,
                                          issues_found=0, status="completed",
                                          error_message="No reviewable files")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"message": "No reviewable files"}).encode())
                return
            
            # Review each file
            reviews = []
            for file_info in reviewable_files[:5]:  # Limit to 5 files
                filename = file_info.get("filename", "")
                content = get_file_content(token, owner, repo_name, filename, head_sha)
                
                if content:
                    review = run_ai_review(content, filename)
                    reviews.append(review)
            
            # Post combined review
            if reviews:
                comment = "## 🤖 PRPilot\n\n" + "\n\n---\n\n".join(reviews)
                post_review_comment(token, owner, repo_name, pr_number, comment)
            
            # Count issues from the review markdown for analytics
            issues_found = sum(text.count("🔴") + text.count("🟡") for text in reviews)
            
            if review_record:
                _update_review_record(review_record["id"],
                                      files_reviewed=len(reviewable_files),
                                      issues_found=issues_found,
                                      status="completed")
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "reviewed",
                "files_reviewed": len(reviewable_files),
                "issues_found": issues_found
            }).encode())
            
        except Exception as e:
            if review_record:
                _update_review_record(review_record["id"], status="failed",
                                      error_message=str(e)[:500])
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
    
    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "healthy",
            "service": "PRPilot Webhook"
        }).encode())
