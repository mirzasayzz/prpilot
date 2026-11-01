# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project does not
yet use a formal versioning release process. The health endpoint
reports version 1.0.0, and that number is kept here until a release
process is agreed.

## Unreleased

### Added

* Real health endpoint in api/index.py with per-check results for
  GitHub App, Supabase, LLM, and encryption environment presence,
  reporting degraded status when a required variable is missing
  and reporting Supabase reachability honestly as not_checked.
* Startup environment validation helper in api/env_check.py
  listing required and optional variables without returning values.
* Structured JSON logging helper in api/logging_util.py with
  redaction of key-like values.
* Offline pytest suite in tests/ covering webhook signatures,
  daily quota boundaries, Link header pagination, agent response
  parsing, provider fallback, and the health endpoint.
* Continuous integration in .github/workflows/ci.yml for Python
  3.11 and 3.12, running compile checks and pytest, with lint as
  a non-blocking step.
* SECURITY.md, CONTRIBUTING.md, and this CHANGELOG.md.
* Database migration file db/migrations/002_schema_hardening.sql
  with a composite index on reviews and a status check
  constraint. The file is not applied by this change.
* Full .env.example grouped by GitHub App, Supabase, encryption,
  LLM providers, config token, cron, owner logins, and daily limit.

### Changed

* requirements.txt is now fully pinned and keeps only packages
  imported by code read in this track, plus python-dotenv for the
  local test harness.
* requirements-dev.txt is new, for pytest, httpx for tests, and ruff.

### Removed

* fastapi, uvicorn, pydantic, and PyGithub from requirements.txt.
  No file read in this track imports them, and the runtime uses
  http.server, httpx, and PyJWT, not those packages.
* google-generativeai from requirements.txt. It is imported only
  by agents/key_manager.py, which is listed for deletion in
  DEAD_CODE.md.

### Notes

* No Dockerfile is included in this change. See Dockerfile.NOTE.md
  for why a clean Dockerfile was not feasible without a server
  entrypoint, and what must exist before one is added.
* The Vercel cron snippet and the testing guide corrections are
  provided as snippet files in this draft, not applied to
  vercel.json or docs/TESTING_GUIDE.md by this change.
