"""
Supabase database client with encryption helpers for storing API keys securely.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from cryptography.fernet import Fernet
from supabase import create_client, Client

# Initialize Supabase client
_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """Get or create Supabase client instance."""
    global _supabase_client
    if _supabase_client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _supabase_client = create_client(url, key)
    return _supabase_client


def get_fernet() -> Fernet:
    """Get Fernet encryption instance."""
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise ValueError("ENCRYPTION_KEY must be set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for storage."""
    fernet = get_fernet()
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key from storage."""
    fernet = get_fernet()
    return fernet.decrypt(encrypted_key.encode()).decode()


# ============= Installation Operations =============

async def get_installation(github_installation_id: int) -> Optional[dict]:
    """Get installation by GitHub installation ID."""
    supabase = get_supabase()
    result = supabase.table("installations").select("*").eq(
        "github_installation_id", github_installation_id
    ).execute()
    return result.data[0] if result.data else None


async def create_installation(
    github_installation_id: int,
    owner_login: str,
    owner_type: str = "User"
) -> dict:
    """Create a new installation record."""
    supabase = get_supabase()
    result = supabase.table("installations").insert({
        "github_installation_id": github_installation_id,
        "owner_login": owner_login,
        "owner_type": owner_type,
    }).execute()
    return result.data[0]


async def update_installation_api_key(
    github_installation_id: int,
    api_key: str
) -> dict:
    """Update the API key for an installation (encrypts before storing)."""
    supabase = get_supabase()
    encrypted = encrypt_api_key(api_key)
    result = supabase.table("installations").update({
        "api_key_encrypted": encrypted
    }).eq("github_installation_id", github_installation_id).execute()
    return result.data[0] if result.data else None


async def get_installation_api_key(github_installation_id: int) -> Optional[str]:
    """Get and decrypt the API key for an installation."""
    installation = await get_installation(github_installation_id)
    if installation and installation.get("api_key_encrypted"):
        return decrypt_api_key(installation["api_key_encrypted"])
    return None


async def update_installation_settings(
    github_installation_id: int,
    settings: dict
) -> dict:
    """Update settings for an installation."""
    supabase = get_supabase()
    result = supabase.table("installations").update({
        "settings": settings
    }).eq("github_installation_id", github_installation_id).execute()
    return result.data[0] if result.data else None


# ============= Review Operations =============

async def create_review(
    installation_id: str,
    repo_full_name: str,
    pr_number: int,
    pr_title: str = None,
    commit_sha: str = None
) -> dict:
    """Create a new review record."""
    supabase = get_supabase()
    result = supabase.table("reviews").insert({
        "installation_id": installation_id,
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "pr_title": pr_title,
        "commit_sha": commit_sha,
        "status": "pending"
    }).execute()
    return result.data[0]


async def update_review(
    review_id: str,
    files_reviewed: int = None,
    issues_found: int = None,
    issues_by_type: dict = None,
    review_duration_ms: int = None,
    status: str = None,
    error_message: str = None
) -> dict:
    """Update a review record with results."""
    supabase = get_supabase()
    update_data = {}
    if files_reviewed is not None:
        update_data["files_reviewed"] = files_reviewed
    if issues_found is not None:
        update_data["issues_found"] = issues_found
    if issues_by_type is not None:
        update_data["issues_by_type"] = issues_by_type
    if review_duration_ms is not None:
        update_data["review_duration_ms"] = review_duration_ms
    if status is not None:
        update_data["status"] = status
    if error_message is not None:
        update_data["error_message"] = error_message
    
    result = supabase.table("reviews").update(update_data).eq("id", review_id).execute()
    return result.data[0] if result.data else None


async def get_review_stats(installation_id: str, days: int = 30) -> dict:
    """Get review statistics for an installation."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result = supabase.table("reviews").select("*").eq(
        "installation_id", installation_id
    ).gte(
        "created_at", cutoff
    ).execute()
    
    reviews = result.data or []
    total_issues = sum(r.get("issues_found", 0) for r in reviews)
    
    return {
        "total_reviews": len(reviews),
        "total_issues_found": total_issues,
        "avg_issues_per_review": total_issues / len(reviews) if reviews else 0
    }


async def count_reviews_since(installation_id: str, hours: int = 24) -> int:
    """Count review records for an installation within the last N hours (usage limiting).

    Uses a server-side COUNT when the client reports one, and falls back
    to counting returned rows. This is a count query, not a fetch of
    every review row, so quota checks stay cheap as history grows.
    """
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    query = supabase.table("reviews").select("id", count="exact").eq(
        "installation_id", installation_id
    ).gte(
        "created_at", cutoff
    )
    result = query.execute()
    count = getattr(result, "count", None)
    if count is not None:
        return int(count)
    return len(result.data or [])


# ============= Config provider, webhook queue, dashboard =============
# Added by the industry-upgrades branch. All functions follow the
# existing style in this file (async, Supabase service client).

_UNSET = object()


async def update_installation_llm_provider(
    github_installation_id: int, provider: str
) -> Optional[dict]:
    """Persist the provider choice for an installation (gemini/groq only)."""
    if provider not in ("gemini", "groq"):
        raise ValueError("provider must be gemini or groq")
    supabase = get_supabase()
    result = supabase.table("installations").update({
        "llm_provider": provider
    }).eq("github_installation_id", github_installation_id).execute()
    return result.data[0] if result.data else None


async def clear_installation_api_key(
    github_installation_id: int
) -> Optional[dict]:
    """Clear only the stored API key. Provider, settings and enabled stay."""
    supabase = get_supabase()
    result = supabase.table("installations").update({
        "api_key_encrypted": None
    }).eq("github_installation_id", github_installation_id).execute()
    return result.data[0] if result.data else None


async def get_installation_credentials(
    github_installation_id: int
) -> Optional[dict]:
    """Return stored provider and decrypted key, or None if no row.

    Decryption failure returns a None key instead of raising, so the
    worker falls back to the environment provider chain.
    """
    installation = await get_installation(github_installation_id)
    if not installation:
        return None
    api_key = None
    encrypted = installation.get("api_key_encrypted")
    if encrypted:
        try:
            api_key = decrypt_api_key(encrypted)
        except Exception:
            api_key = None
    return {
        "llm_provider": installation.get("llm_provider"),
        "api_key": api_key,
    }


async def upsert_installation(
    github_installation_id: int,
    owner_login: str,
    owner_type: str = "User"
) -> dict:
    """Create or update an installation row by GitHub installation id.

    This avoids the get-then-insert race in concurrent webhooks, where
    two events for a new installation could both try to insert and one
    would hit the UNIQUE constraint on github_installation_id.
    """
    supabase = get_supabase()
    result = supabase.table("installations").upsert({
        "github_installation_id": github_installation_id,
        "owner_login": owner_login,
        "owner_type": owner_type,
    }, on_conflict="github_installation_id").execute()
    return result.data[0]


async def store_webhook_event(
    delivery_id: str,
    installation_id: int,
    repo_full_name: str,
    pr_number: int,
    event_action: str,
    payload_json: str
) -> dict:
    """Store a webhook event as pending. Existing delivery ids are untouched."""
    existing = await get_webhook_event(delivery_id)
    if existing:
        return existing
    supabase = get_supabase()
    try:
        result = supabase.table("webhook_events").insert({
            "delivery_id": delivery_id,
            "installation_id": installation_id,
            "repo_full_name": repo_full_name,
            "pr_number": pr_number,
            "event_action": event_action,
            "payload_json": payload_json,
            "status": "pending",
            "attempts": 0,
        }).execute()
        return result.data[0]
    except Exception:
        existing = await get_webhook_event(delivery_id)
        if existing:
            return existing
        raise


async def get_webhook_event(delivery_id: str) -> Optional[dict]:
    """Get a webhook event row by delivery id, or None."""
    supabase = get_supabase()
    result = supabase.table("webhook_events").select("*").eq(
        "delivery_id", delivery_id
    ).execute()
    return result.data[0] if result.data else None


async def update_webhook_event(
    delivery_id: str,
    status: str = None,
    attempts: int = None,
    error_message=_UNSET
) -> Optional[dict]:
    """Update a webhook event. Only supplied fields change, except that
    an explicitly passed error_message of None clears the stored error
    (used when an event reaches processed). Callers that omit
    error_message leave the stored value untouched."""
    supabase = get_supabase()
    update_data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if status is not None:
        update_data["status"] = status
    if attempts is not None:
        update_data["attempts"] = attempts
    if error_message is not _UNSET:
        update_data["error_message"] = error_message
    result = supabase.table("webhook_events").update(update_data).eq(
        "delivery_id", delivery_id
    ).execute()
    return result.data[0] if result.data else None


async def get_oldest_pending_event() -> Optional[dict]:
    """Return the oldest pending webhook event, or None."""
    supabase = get_supabase()
    result = supabase.table("webhook_events").select("*").eq(
        "status", "pending"
    ).order("created_at").limit(1).execute()
    return result.data[0] if result.data else None


async def list_recent_reviews(installation_id: str, limit: int = 20) -> list:
    """Return recent review rows, newest first, with no key material."""
    supabase = get_supabase()
    result = supabase.table("reviews").select(
        "repo_full_name, pr_number, pr_title, files_reviewed,"
        " issues_found, status, created_at"
    ).eq("installation_id", installation_id).order(
        "created_at", desc=True
    ).limit(limit).execute()
    return result.data or []
