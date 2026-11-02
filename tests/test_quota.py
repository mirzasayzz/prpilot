"""Daily quota tests, mirroring api/webhook.py.

Rules in api/webhook.py as read:

* FREE_DAILY_LIMIT defaults to 25 and USAGE_WINDOW_HOURS to 24.
* An owner login bypasses the limit entirely.
* Otherwise a review is allowed only while used < limit, where
  used is the COUNT of review records in the window
  (db/client.py count_reviews_since).
* If there is no installation id, or the database lookup fails,
  the webhook code fails open and allows the review rather than
  breaking the flow.

The functions below are small, pure mirrors of those rules so
the boundary behaviour can be tested without a database or
network. The database counting itself (count_reviews_since) is
not tested here because it needs Supabase.
"""

FREE_DAILY_LIMIT = 25


def is_owner(account_login, owner_logins):
    owners = {login.strip().lower() for login in owner_logins if login.strip()}
    return (account_login or "").strip().lower() in owners


def quota_allowed(used, limit=FREE_DAILY_LIMIT, owner=False):
    if owner:
        return True
    return used < limit


def usage_allowed(installation_id, owner_login, owner_logins, count_fn, limit=FREE_DAILY_LIMIT):
    """Mirror of api/webhook.py _usage_allowed, with fail-open."""
    if not installation_id:
        return True
    try:
        if is_owner(owner_login, owner_logins):
            return True
        used = count_fn(installation_id)
        return used < limit
    except Exception:
        return True


def test_default_limit_is_25():
    assert FREE_DAILY_LIMIT == 25


def test_under_limit_allowed():
    assert quota_allowed(0) is True
    assert quota_allowed(24) is True


def test_at_limit_blocked():
    assert quota_allowed(25) is False
    assert quota_allowed(26) is False


def test_owner_bypass():
    assert quota_allowed(1000, owner=True) is True
    assert is_owner("mirzasayzz", ["mirzasayzz"]) is True
    assert is_owner("MirzaSayzz", ["mirzasayzz"]) is True
    assert is_owner("someone-else", ["mirzasayzz"]) is False


def test_owner_bypass_in_usage_allowed():
    calls = []

    def count_fn(installation_id):
        calls.append(installation_id)
        return 999

    assert (
        usage_allowed("inst-1", "mirzasayzz", ["mirzasayzz"], count_fn) is True
    )
    assert calls == []


def test_count_based_usage():
    assert usage_allowed("inst-1", "other", ["mirzasayzz"], lambda _: 24) is True
    assert usage_allowed("inst-1", "other", ["mirzasayzz"], lambda _: 25) is False


def test_missing_installation_fails_open():
    def count_fn(_):
        raise AssertionError("should not be called")

    assert usage_allowed(None, "other", ["mirzasayzz"], count_fn) is True


def test_database_error_fails_open():
    def count_fn(_):
        raise RuntimeError("database down")

    assert usage_allowed("inst-1", "other", ["mirzasayzz"], count_fn) is True
