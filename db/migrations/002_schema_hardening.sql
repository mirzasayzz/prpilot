-- Migration 002: schema hardening for PRPilot reviews.
-- FILE ONLY. Do NOT run this file against a live database as part
-- of this draft. Apply it only through the normal migration review
-- process, after checking it against the current Supabase schema.
--
-- This migration assumes db/schema.sql as read: the reviews table
-- has an installation_id column, a created_at column, and a status
-- column whose documented values are pending, completed, and failed.
-- If the live schema differs, stop and update this file first.

-- Composite index for the common query pattern in
-- db/client.py count_reviews_since: reviews for one installation
-- in a time window, ordered by creation time.
-- The existing single-column index on reviews(installation_id)
-- is kept; this composite index is additional, not a replacement.
CREATE INDEX IF NOT EXISTS idx_reviews_installation_created_at
    ON reviews (installation_id, created_at);

-- Status check constraint, added only if it does not already exist.
-- The status column exists in db/schema.sql with a default of
-- pending and documented values pending, completed, and failed.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'reviews_status_check'
    ) THEN
        ALTER TABLE reviews
            ADD CONSTRAINT reviews_status_check
            CHECK (status IN ('pending', 'completed', 'failed')) NOT VALID;
    END IF;
END
$$;

-- Note on dedup: no unique constraint is added on reviews.
-- Repeat reviews of one PR are legitimate, so dedup lives on
-- webhook_events.delivery_id (migration 001), not on reviews.
