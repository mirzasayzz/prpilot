# Dead code audit (corrected during assembly)

This note corrects an earlier drafting claim. Do not delete files
listed as kept below without checking the imports cited here.

## Kept, not dead

- `github/client.py` and `github/webhook_handler.py`: kept.
  `github/__init__.py` imports `GitHubAppClient`, `PullRequest`,
  `PullRequestFile`, `WebhookPayload`, `verify_webhook_signature`,
  `parse_pull_request_event`, and `is_reviewable_file` from them,
  so they are the package API even though `api/` currently uses
  its own httpx patterns. Wiring `api/review_worker.py` to them
  instead of duplicating their patterns is a follow-up, not a
  deletion. Deleting them would break `import github`.
- `check_db.py`: kept in this branch. It is a local debug script,
  not imported by production code, but deleting local tooling in
  the same PR as a security change would hide the diff. Move or
  delete it in a separate cleanup PR if it is no longer wanted.

## Removed from requirements, not from the repo

- `fastapi`, `uvicorn`, `pydantic`, `PyGithub`: removed from
  `requirements.txt`. No Python file in the repo imports them
  (verified by grep across `api/`, `agents/`, `github/`, `db/`,
  `check_db.py`, and `test_local.py`). The runtime is Vercel
  serverless Python with `http.server`, httpx, and PyJWT.
- `google-generativeai`: removed from `requirements.txt`. It is
  imported only by `agents/key_manager.py` (see below). The live
  agent path uses `google-genai` (lazy `from google import genai`).

## Deleted in this branch

- `agents/key_manager.py`: deleted. It uses the legacy
  `google-generativeai` SDK, is imported by no production code,
  and is superseded by `agents/llm_client.py` (multi-provider
  failover with rotation and cooldowns). If any local script
  imports it, that script must be updated first.
- No other file is deleted in this branch. In particular, the
  12.3 MB presentation file in the repo root is not moved or
  deleted here: binary files cannot be moved through the GitHub
  text-file API, so that move needs `git mv` locally.
