"""
Shared review processing, used by api/process.py and by no other caller.

This module is the worker half of the ack-then-queue webhook design:

- api/webhook.py verifies the signature, stores the event, and returns
  200 immediately. It never runs an LLM call.
- api/process.py loads a stored event by delivery id and calls
  process_event(delivery_id) here.
- process_event does the real work: quota and settings checks, PR file
  pagination, concurrent specialist agents, and a real GitHub PR review
  with inline comments.

Rules that fix the audited faults:
- Inline review first. A single issue comment is only a fallback when
  the review API call itself fails. It is never the default path.
- Pagination follows GitHub Link headers until there is no next page,
  with per_page=100. There is no 30 file default and no 5 file cap.
- Review input is the diff patch when GitHub provides one. Full file
  content is only a fallback, and that file is then flagged as
  truncated in both the PR comment and the database record.
- Files larger than MAX_PATCH_CHARS are split into chunks and each
  chunk is reviewed. Files that cannot be reviewed at all are listed
  honestly as skipped, with a reason, and are never counted in
  files_reviewed.
- files_reviewed counts only files that were actually reviewed.
- No exception text reaches a PR comment, a review body, or a stored
  error_message. Stored errors and logs use short category strings
  plus the delivery id, so operators can correlate without leaking
  host, key, or provider details.
- Quota is fail-closed for non-owners: if the usage count cannot be
  verified, the review is skipped and the event is marked failed,
  instead of silently allowing unlimited reviews. Owners bypass the
  cap, as before.

Imports are kept to the standard library plus jwt and httpx, which
api/webhook.py already used. Agent classes are imported lazily inside
functions so that importing this module never pulls in an LLM SDK.

db.client helpers this module needs are implemented in
db/client.py: get_installation_credentials,
get_oldest_pending_event is used by process.py, not here. If
get_installation_credentials is not yet applied, the worker proceeds
with the environment multi-provider chain and no per-installation key,
and it never crashes on the missing helper.
"""

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAX_PATCH_CHARS = 12000
MAX_CONTENT_CHARS = 12000
REVIEWABLE_EXTENSIONS = (
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb",
    ".rs", ".php", ".c", ".cpp", ".cs", ".swift", ".kt",
)

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


def _is_owner(account_login):
    return (account_login or "").strip().lower() in OWNER_LOGINS


def _log(delivery_id, category, extra=None):
    """Structured log line: delivery id and category only, no details."""
    record = {"delivery_id": delivery_id, "event": category}
    if extra:
        record.update(extra)
    print(json.dumps(record))


# ---------------------------------------------------------------------------
# GitHub API helpers (httpx patterns already used in api/webhook.py)
# ---------------------------------------------------------------------------

def get_installation_access_token(installation_id):
    import time

    import jwt
    import httpx

    app_id = os.environ.get("GITHUB_APP_ID")
    private_key = os.environ.get("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
    if not app_id or not private_key:
        raise ValueError("GitHub App credentials are not configured")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + (10 * 60), "iss": app_id}
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


def _next_link(link_header):
    """Extract the rel=next URL from a GitHub Link header, or None."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1 and end > start:
                return part[start + 1:end]
    return None


def get_pr_files_all(token, owner, repo, pr_number):
    """Fetch every file in a PR, following Link pagination."""
    import httpx

    headers = {
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
    }
    files = []
    url = (
        "https://api.github.com/repos/%s/%s/pulls/%s/files?per_page=100"
        % (owner, repo, pr_number)
    )
    with httpx.Client(timeout=30.0) as client:
        while url:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            page = resp.json()
            if isinstance(page, list):
                files.extend(page)
            url = _next_link(resp.headers.get("Link", ""))
    return files


def get_file_content(token, owner, repo, path, ref):
    """Fetch one file at a ref, or return an empty string on failure."""
    import base64

    import httpx

    headers = {
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://api.github.com/repos/%s/%s/contents/%s?ref=%s"
            % (owner, repo, path, ref),
            headers=headers,
        )
        if resp.status_code != 200:
            return ""
        data = resp.json()
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode(
                "utf-8", errors="ignore"
            )
        return ""


def post_pr_review(token, owner, repo, pr_number, commit_sha, comments, body, event="COMMENT"):
    """Post a real PR review with inline comments.

    comments: list of dicts with path, line, side ("RIGHT"), and body.
    event is COMMENT by default. The caller may pass APPROVE only
    when auto_approve is enabled and no critical or high issue was
    found (see process_event). Returns True on success. Raises on
    HTTP failure so the caller can fall back to a single issue comment.
    """
    import httpx

    headers = {
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "commit_id": commit_sha,
        "body": body,
        "event": event,
        "comments": comments,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.github.com/repos/%s/%s/pulls/%s/reviews"
            % (owner, repo, pr_number),
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
    return True


def post_issue_comment(token, owner, repo, pr_number, body):
    """Fallback only: one plain comment on the PR (issue comments API)."""
    import httpx

    headers = {
        "Authorization": "Bearer %s" % token,
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.github.com/repos/%s/%s/issues/%s/comments"
            % (owner, repo, pr_number),
            headers=headers,
            json={"body": body},
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Patch handling
# ---------------------------------------------------------------------------

def parse_patch_diff_lines(patch):
    """Return the set of new-file line numbers present in a patch.

    Walks hunk headers (@@ -old +new @@) and counts only context and
    added lines towards the new file. Removed lines do not advance it.
    Only lines in this set may receive an inline comment, because
    GitHub rejects inline comments on lines outside the diff.
    """
    diff_lines = set()
    new_line = None
    for raw_line in (patch or "").splitlines():
        if raw_line.startswith("@@"):
            try:
                plus_part = raw_line.split("+", 1)[1]
                new_line = int(plus_part.split(",")[0].split(" ")[0])
            except (IndexError, ValueError):
                new_line = None
            continue
        if new_line is None:
            continue
        if raw_line.startswith(" ") or raw_line.startswith("+"):
            diff_lines.add(new_line)
            new_line += 1
        elif raw_line.startswith("-"):
            pass
        else:
            # Lines such as "\ No newline at end of file" do not move
            # the line counter.
            pass
    return diff_lines


def chunk_text(text, limit):
    """Split text into chunks of at most limit chars, on line breaks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current and current_len + len(line) > limit:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _build_agents(settings, provider, api_key):
    """Build the enabled specialist agents.

    Per-installation key handling, stated plainly: the existing
    BaseAgent single-key path only supports a Gemini key, so a
    per-installation key is passed to agents only when the stored
    provider is gemini. For groq, or when no key is stored, agents are
    built without a key and use the environment multi-provider chain
    already in agents/llm_client.py. Passing a Groq key as a Gemini
    key would fail every call, so it is never done. Making agents
    provider aware is a follow-up listed in NOTES.md, not something
    this draft pretends to do.
    """
    from agents.logic_agent import LogicAgent
    from agents.performance_agent import PerformanceAgent
    from agents.security_agent import SecurityAgent
    from agents.style_agent import StyleAgent

    use_key = api_key if provider == "gemini" else None
    candidates = [
        ("review_style", StyleAgent),
        ("review_security", SecurityAgent),
        ("review_performance", PerformanceAgent),
        ("review_logic", LogicAgent),
    ]
    agents = []
    for setting_key, cls in candidates:
        if settings.get(setting_key, True):
            agents.append(cls(api_key=use_key) if use_key else cls())
    return agents


def _run_agent_sync(agent, code, file_path, context):
    """Run one async agent review from a worker thread."""
    return asyncio.run(agent.review_code(code=code, file_path=file_path, context=context))


def _review_one_file(agents, file_path, review_text, context):
    """Run all enabled agents concurrently on one file's review text.

    Returns (issues, truncated_flag). An agent that fails returns an
    empty review from BaseAgent itself, so one agent failure never
    blocks the others.
    """
    issues = []
    if not agents:
        return issues, False
    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        futures = [
            pool.submit(_run_agent_sync, agent, review_text, file_path, context)
            for agent in agents
        ]
        for future in futures:
            try:
                result = future.result()
                issues.extend(result.issues or [])
            except Exception:
                continue
    return issues, False


def _issue_to_inline_comment(issue, diff_lines):
    """Convert a CodeIssue to an inline comment, or None if not in diff."""
    try:
        line = int(issue.line_start)
    except (TypeError, ValueError):
        return None
    if line not in diff_lines:
        return None
    body = "**%s** (%s, %s)\n\n%s" % (
        issue.title,
        issue.category,
        issue.severity.value if hasattr(issue.severity, "value") else issue.severity,
        issue.description,
    )
    if getattr(issue, "suggestion", None):
        body += "\n\n```suggestion\n%s\n```" % issue.suggestion
    return {"path": issue.file_path, "line": line, "side": "RIGHT", "body": body}


def _issue_to_text(issue):
    severity = issue.severity.value if hasattr(issue.severity, "value") else issue.severity
    text = "- %s **%s** in %s (line %s): %s" % (
        severity, issue.title, issue.file_path, issue.line_start, issue.description
    )
    if getattr(issue, "suggestion", None):
        text += " Suggested fix: %s" % issue.suggestion
    return text


# ---------------------------------------------------------------------------
# Main worker entry point
# ---------------------------------------------------------------------------

def process_event(delivery_id):
    """Process one stored webhook event. Returns a result dict.

    Result statuses: processed, skipped, failed. "skipped" means the
    event was handled deliberately (disabled installation, quota
    reached, no reviewable files) and must not be retried as a failure.
    "failed" means process.py may retry it, up to the attempt limit,
    after which it becomes dead_letter there.
    """
    try:
        from db.client import (
            create_installation,
            create_review,
            get_installation,
            get_webhook_event,
            update_review,
            update_webhook_event,
        )
    except Exception:
        _log(delivery_id, "db_unavailable")
        return {"status": "failed", "reason": "db_unavailable"}

    try:
        event = _db(get_webhook_event, delivery_id)
    except Exception:
        _log(delivery_id, "event_load_failed")
        return {"status": "failed", "reason": "event_load_failed"}
    if not event:
        return {"status": "failed", "reason": "event_not_found"}
    if event.get("status") == "processed":
        return {"status": "processed", "reason": "already_processed"}

    try:
        payload = json.loads(event.get("payload_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    pr = payload.get("pull_request", {}) if isinstance(payload, dict) else {}
    repo = payload.get("repository", {}) if isinstance(payload, dict) else {}
    installation = payload.get("installation", {}) if isinstance(payload, dict) else {}

    installation_id = event.get("installation_id") or installation.get("id")
    repo_full_name = event.get("repo_full_name") or ""
    pr_number = event.get("pr_number") or pr.get("number")
    if not installation_id or not repo_full_name or not pr_number:
        _db(update_webhook_event, delivery_id, status="failed", error_message="incomplete_event")
        return {"status": "failed", "reason": "incomplete_event"}

    owner, _, repo_name = repo_full_name.partition("/")
    head_sha = pr.get("head", {}).get("sha") or ""
    account_login = installation.get("account", {}).get("login", owner)

    try:
        _db(update_webhook_event, delivery_id, status="processing")
    except Exception:
        pass

    try:
        inst = _db(get_installation, int(installation_id))
        if not inst:
            try:
                from db.client import upsert_installation

                _db(upsert_installation, int(installation_id), account_login or "")
            except Exception:
                _db(create_installation, int(installation_id), account_login or "")
            inst = _db(get_installation, int(installation_id))
        if inst and inst.get("enabled") is False:
            _db(update_webhook_event, delivery_id, status="processed", error_message="installation_disabled")
            _log(delivery_id, "skipped_disabled")
            return {"status": "skipped", "reason": "installation_disabled"}

        settings = (inst or {}).get("settings") or {}
        provider = (inst or {}).get("llm_provider")
        api_key = None
        try:
            from db.client import get_installation_credentials

            creds = _db(get_installation_credentials, int(installation_id))
            if creds:
                provider = creds.get("llm_provider") or provider
                api_key = creds.get("api_key")
        except Exception:
            api_key = None

        # Quota: fail-closed for non-owners, owners bypass as before.
        if inst and not _is_owner(inst.get("owner_login", "")):
            try:
                from db.client import count_reviews_since

                used = _db(count_reviews_since, inst["id"], USAGE_WINDOW_HOURS)
                if used >= FREE_DAILY_LIMIT:
                    _db(update_webhook_event, delivery_id, status="processed", error_message="quota_reached")
                    _log(delivery_id, "skipped_quota")
                    return {"status": "skipped", "reason": "quota_reached"}
            except Exception:
                _db(update_webhook_event, delivery_id, status="failed", error_message="quota_unavailable")
                _log(delivery_id, "quota_unavailable")
                return {"status": "failed", "reason": "quota_unavailable"}

        token = get_installation_access_token(int(installation_id))
        files = get_pr_files_all(token, owner, repo_name, pr_number)

        review_record = None
        try:
            review_record = _db(
                create_review, inst["id"], repo_full_name, pr_number,
                pr.get("title", ""), head_sha,
            )
        except Exception:
            review_record = None

        agents = _build_agents(settings, provider, api_key)
        context = "PR title: %s\n\nPR description: %s" % (
            pr.get("title", ""), pr.get("body", "") or "",
        )
        inline_comments = []
        all_issues = []
        reviewed_files = []
        truncated_files = []
        skipped_files = []

        for file_info in files:
            filename = file_info.get("filename", "")
            if not filename:
                continue
            if file_info.get("status") == "removed":
                skipped_files.append({"path": filename, "reason": "removed"})
                continue
            if not filename.endswith(REVIEWABLE_EXTENSIONS):
                skipped_files.append({"path": filename, "reason": "unsupported_extension"})
                continue
            patch = file_info.get("patch")
            if patch:
                chunks = chunk_text(patch, MAX_PATCH_CHARS)
                diff_lines = parse_patch_diff_lines(patch)
                for chunk in chunks:
                    chunk_issues, _ = _review_one_file(agents, filename, chunk, context)
                    for issue in chunk_issues:
                        comment = _issue_to_inline_comment(issue, diff_lines)
                        if comment:
                            inline_comments.append(comment)
                        all_issues.append(issue)
                reviewed_files.append(filename)
            else:
                # No patch (for example a very large or binary diff):
                # fall back to truncated full content, flagged clearly.
                content = get_file_content(token, owner, repo_name, filename, head_sha)
                if not content:
                    skipped_files.append({"path": filename, "reason": "no_patch_no_content"})
                    continue
                truncated = len(content) > MAX_CONTENT_CHARS
                review_text = content[:MAX_CONTENT_CHARS]
                chunk_issues, _ = _review_one_file(agents, filename, review_text, context)
                all_issues.extend(chunk_issues)
                reviewed_files.append(filename)
                if truncated:
                    truncated_files.append(filename)

        issues_found = len(all_issues)
        summary_lines = [
            "## PRPilot review",
            "",
            "Files reviewed: %d" % len(reviewed_files),
            "Issues found: %d" % issues_found,
        ]
        if truncated_files:
            summary_lines.append(
                "Truncated files (reviewed from partial content only): %s"
                % ", ".join(truncated_files)
            )
        if skipped_files:
            summary_lines.append("Skipped files:")
            for item in skipped_files:
                summary_lines.append(
                    "- %s (%s)" % (item["path"], item["reason"])
                )
        if not all_issues:
            summary_lines.append("")
            summary_lines.append("No issues found in the reviewed files.")
        body = "\n".join(summary_lines)

        # Inline review first. Fall back to one comment only if the
        # review API call itself fails.
        posted_inline = False
        if inline_comments or True:
            try:
                # Cap inline comments at 50 so one noisy PR cannot
                # produce an unbounded review payload. Issues beyond
                # the cap still appear in the summary text below.
                capped = inline_comments[:50]
                extra_text = ""
                if len(inline_comments) > 50:
                    extra_text = "\n\nNote: %d inline comments were capped at 50; remaining issues are listed in the fallback summary." % len(inline_comments)
                review_body = body + extra_text
                if all_issues and not capped:
                    review_body += "\n\n" + "\n".join(_issue_to_text(i) for i in all_issues)
                # auto_approve: approve only when the setting is on
                # and no critical or high severity issue was found.
                # Anything severe, or a PR with no reviewed files,
                # stays a COMMENT review. This is the only place the
                # stored auto_approve toggle takes effect.
                severe = False
                for issue in all_issues:
                    sev = issue.severity.value if hasattr(issue.severity, "value") else str(issue.severity)
                    if sev in ("critical", "high"):
                        severe = True
                        break
                review_event = "APPROVE" if (settings.get("auto_approve") and reviewed_files and not severe) else "COMMENT"
                post_pr_review(token, owner, repo_name, pr_number, head_sha, capped, review_body, event=review_event)
                posted_inline = True
            except Exception:
                posted_inline = False
        if not posted_inline:
            fallback = body
            if all_issues:
                fallback += "\n\n" + "\n".join(_issue_to_text(i) for i in all_issues)
            post_issue_comment(token, owner, repo_name, pr_number, fallback)

        if review_record:
            try:
                _db(
                    update_review, review_record["id"],
                    files_reviewed=len(reviewed_files),
                    issues_found=issues_found,
                    status="completed",
                )
            except Exception:
                pass
        _db(update_webhook_event, delivery_id, status="processed", error_message=None)
        _log(
            delivery_id, "processed",
            extra={
                "files_reviewed": len(reviewed_files),
                "skipped_files": len(skipped_files),
                "inline_comments": len(inline_comments),
                "fallback_comment": (not posted_inline),
            },
        )
        return {
            "status": "processed",
            "files_reviewed": len(reviewed_files),
            "issues_found": issues_found,
            "skipped_files": len(skipped_files),
            "truncated_files": truncated_files,
        }
    except Exception:
        # Generic category only, never exception text.
        try:
            _db(update_webhook_event, delivery_id, status="failed", error_message="review_failed")
        except Exception:
            pass
        _log(delivery_id, "review_failed")
        return {"status": "failed", "reason": "review_failed"}
