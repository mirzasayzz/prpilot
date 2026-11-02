# Industry upgrades: manual steps and what was not done

This branch changes code only. Nothing in it touches live Supabase,
live Vercel settings, or the GitHub App listing. Apply the steps below
by hand, in order, after reviewing the pull request. Do not merge
without them, or the new code will fail closed in useful ways:
config and the worker return 401 or 500 until their secrets and
tables exist.

## 1. Supabase migrations (apply in order, SQL editor or psql)

1. `db/migrations/001_config_and_events.sql`
   - Adds `installations.llm_provider` (gemini or groq, NULL means not set).
   - Creates `webhook_events` keyed by delivery id, with a payload
     column, status, attempts, and pending/installation indexes.
   - Deliberately adds no unique constraint on `reviews`. Repeat
     reviews of one PR are legitimate (each synchronize creates a
     new review row), so dedup lives on `webhook_events.delivery_id`.
2. `db/migrations/002_schema_hardening.sql`
   - Adds the composite index `reviews (installation_id, created_at)`.
   - Adds a status check constraint as NOT VALID, so existing rows
     are not scanned on apply. Validate it later with
     `ALTER TABLE reviews VALIDATE CONSTRAINT reviews_status_check;`
     after confirming existing statuses are only pending, completed
     or failed.

## 2. Vercel environment variables (new in this branch)

- `CONFIG_TOKEN_SECRET`: a long random secret used only to sign
  config tokens (HMAC). If it is missing, config and dashboard
  return 401 and install redirects to an error page. Generate one
  with a password manager or `openssl rand -hex 32` and set it in
  Vercel only, never in the repo.
- `CRON_SECRET`: a long random secret for `/api/process`. The
  worker accepts `X-Cron-Secret` or `Authorization: Bearer <secret>`.
  If it is missing, every worker request returns 401.
- Existing variables are unchanged. See `.env.example` for the full
  list, with placeholder values only.

## 3. Worker schedule

- `vercel.json` deliberately declares no Vercel cron. A 5 minute
  Vercel cron would fail deployment on a Hobby plan, which only
  allows daily cron. Use an external scheduler instead, for
  example a GitHub Actions cron, cron-job.org, or any scheduler
  that calls `/api/process` every 5 minutes with
  `X-Cron-Secret` or `Authorization: Bearer <CRON_SECRET>`.
  Vercel Cron sends GET, and this branch supports an authorised
  GET sweep (oldest pending event per call), so the same route
  works for both.
- `vercel.json` builds now list only the six handler files in
  `api/` explicitly, instead of `api/*.py`, so helper modules
  (`api/auth.py`, `api/env_check.py`, `api/logging_util.py`,
  `api/review_worker.py`) are bundled as imports, not built as
  separate public functions.
- After the first deploy, check `webhook_events` for rows stuck in
  `failed` or `dead_letter`. Those are the retry and dead-letter
  states, not silent drops.

## 4. Config flow change (breaking, by design)

- Old config URLs with a bare `installation_id` no longer work.
  Install again through the GitHub App, or use the install
  callback, which now verifies the installation and redirects to
  `/config.html?config_token=...`. Tokens expire after 1 hour.
- The dashboard is `/dashboard.html` with the same token. It shows
  owner, status, provider, quota, and recent reviews. It does not
  list installation repositories, because repositories are not
  stored in the database; review rows show the repos that have
  actually been reviewed.

## 5. Known limitations in this branch (not hidden)

- A stored Groq key is saved, format checked, and shown on the
  dashboard, but the current agent path only passes a stored key
  to agents for Gemini. For Groq, agents use the environment
  provider chain. Making agents provider aware is a follow-up.
- Inline comments are capped at 50 per review, stated in the
  review body. Issues beyond the cap are listed in the summary.
- The 12.3 MB presentation file in the repo root was not moved.
  Binary files cannot be moved through the GitHub text-file API,
  so move it with `git mv` locally if you want it under `docs/`.
- No Dockerfile is included. There is no stdlib server entrypoint
  that serves every route, so a Dockerfile would look like a
  working app while most routes were absent. Vercel remains the
  production path. See `docs/DEAD_CODE_AUDIT.md`.
- No billing, pricing, or SOC 2 claim is added. The honest model
  is: free to install, bring your own key, 25 reviews a day for
  non-owner installations by default.

## 6. Testing done in this branch

- `python -m py_compile` on every changed Python file.
- `pytest` in `tests/` with mocked HTTP and no network calls.
  Tests that need real repo modules are skipped with a reason
  when run outside the repo tree.
- HTML files parsed with Python `html.parser`; SVG and sitemap
  parsed as XML; `vercel.json` and CI YAML parsed as JSON/YAML.
- No live Supabase, Vercel, or GitHub App change was made or
  tested. The first live test after deploy should be: install on
  a test repo, open a small PR, confirm a queued event, a worker
  run, and an inline review, then check the dashboard.
