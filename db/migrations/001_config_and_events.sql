-- PRPilot migration 001: config provider column and webhook event queue.
--
-- Apply manually in Supabase (SQL editor or psql). Do NOT apply by
-- running this file against production from an unverified script.
-- This file is a draft only and was not applied to live Supabase.
--
-- What this migration does, and what it deliberately does not do:
-- 1. Adds llm_provider to installations, so api/config.py can persist
--    the provider choice separately from the encrypted API key.
-- 2. Creates webhook_events, the ack-then-queue store. delivery_id is
--    the primary key, so a redelivered GitHub webhook with the same
--    X-GitHub-Delivery value cannot create a second row. That is the
--    idempotency guarantee the worker relies on.
-- 3. Adds payload_json. The task column list for webhook_events did
--    not include a payload column, but without one the worker cannot
--    recover the PR, repo, installation, and head SHA after the
--    webhook handler has already returned 200. payload_json is
--    therefore required, not optional, and is documented here as an
--    addition to that list.
-- 4. It does NOT add a unique constraint on reviews, and it does NOT
--    add an index on reviews(installation_id, created_at). The
--    reviews table column names could not be verified in this
--    drafting run (db/schema.sql was not readable: GitHub returned
--    HTTP 429, see NOTES.md), and inventing a column name would make
--    this migration fail or, worse, silently create the wrong
--    constraint. The commented block at the end is the intended
--    follow-up: confirm the reviews columns in db/schema.sql, then
--    uncomment and adjust it. Duplicate PR reviews are still
--    prevented in the meantime by the webhook_events primary key:
--    one delivery id is processed once, so one webhook delivery
--    cannot create two reviews.

ALTER TABLE installations
  ADD COLUMN IF NOT EXISTS llm_provider TEXT;

-- Keep the provider value honest at the database level as well as in
-- the API. Existing rows keep NULL (meaning "not set") on this step.
ALTER TABLE installations
  ADD CONSTRAINT installations_llm_provider_check
  CHECK (llm_provider IS NULL OR llm_provider IN ('gemini', 'groq'))
  NOT VALID;

CREATE TABLE IF NOT EXISTS webhook_events (
  delivery_id TEXT PRIMARY KEY,
  installation_id BIGINT NOT NULL,
  repo_full_name TEXT NOT NULL,
  pr_number INT NOT NULL,
  event_action TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'processing', 'processed', 'failed', 'dead_letter')),
  attempts INT NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS webhook_events_pending_idx
  ON webhook_events (status, created_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS webhook_events_installation_idx
  ON webhook_events (installation_id, created_at);

-- Deliberately NOT added, after verifying db/schema.sql: a unique
-- constraint on reviews (installation_id, repo_full_name, pr_number)
-- would break legitimate repeat reviews of the same PR (each
-- synchronize creates a new review row). Duplicate processing is
-- prevented by webhook_events.delivery_id as primary key instead.
-- The composite index for quota queries is in migration 002.
