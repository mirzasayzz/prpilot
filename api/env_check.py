"""Startup environment validation for PRPilot.

This module never raises on import and never returns a secret value.
It reports only variable names, so its output is safe to include in a
health response or a startup log.

Required variables are the ones the running service needs to do its
job. Optional variables enable extra providers or tune limits, and
their absence is reported separately so a missing optional variable
does not make the service look broken.

Note on scope: GITHUB_APP_ID, GITHUB_PRIVATE_KEY,
GITHUB_WEBHOOK_SECRET, SUPABASE_URL, SUPABASE_SERVICE_KEY, and
ENCRYPTION_KEY are referenced by code read in this track
(api/webhook.py, db/client.py). CONFIG_TOKEN_SECRET and CRON_SECRET
are listed as required here because the engineering brief names them
for this helper; their consumers live in modules owned by other
tracks (api/config.py as read in this track has no token check, and
api/process.py was not in this track's read list), so the merger
should confirm those consumers before treating a missing value as a
production blocker. See NOTES.md.
"""

import os

REQUIRED_VARS = (
    "GITHUB_APP_ID",
    "GITHUB_PRIVATE_KEY",
    "GITHUB_WEBHOOK_SECRET",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "ENCRYPTION_KEY",
    "CONFIG_TOKEN_SECRET",
    "CRON_SECRET",
)

OPTIONAL_VARS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEYS",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY_1",
    "OPENROUTER_API_KEY_2",
    "LLMAPI_API_KEY",
    "PRPILOT_OWNER_LOGINS",
    "FREE_DAILY_LIMIT",
    "USAGE_WINDOW_HOURS",
)

LLM_VARS = (
    "GEMINI_API_KEY",
    "GEMINI_API_KEYS",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY_1",
    "OPENROUTER_API_KEY_2",
    "LLMAPI_API_KEY",
)


def _is_set(env, name):
    value = env.get(name)
    return value is not None and str(value).strip() != ""


def validate(env=None):
    """Return a dict describing which variables are set.

    The returned dict contains only names, never values:

        {
            "ok": bool,                 # True when no required var is missing
            "missing": [names],         # required vars that are not set
            "present": [names],         # required vars that are set
            "optional_missing": [names],
            "optional_present": [names],
            "llm_configured": bool,     # True when at least one LLM key is set
        }
    """
    if env is None:
        env = os.environ
    missing = [name for name in REQUIRED_VARS if not _is_set(env, name)]
    present = [name for name in REQUIRED_VARS if _is_set(env, name)]
    optional_missing = [name for name in OPTIONAL_VARS if not _is_set(env, name)]
    optional_present = [name for name in OPTIONAL_VARS if _is_set(env, name)]
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "present": present,
        "optional_missing": optional_missing,
        "optional_present": optional_present,
        "llm_configured": any(_is_set(env, name) for name in LLM_VARS),
    }
