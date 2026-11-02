"""Provider fallback tests, with mocked providers.

Fallback behaviour in agents/llm_client.py as read
(MultiProviderLLM.generate):

* Providers are tried in order.
* A provider that is not available is skipped.
* A provider that raises is skipped and the next one is tried.
* The first success is returned.
* If every provider fails, an exception listing the errors is raised.

The chain below is a small mirror of that loop, tested with fake
providers and unittest.mock, so no network call and no real API
key is needed. It does not import agents/llm_client.py, because
that module's provider constructors read environment variables
and its generate methods call real SDKs; testing the loop itself
with fakes is the offline-safe form of this test. The merger
should confirm the loop in agents/llm_client.py still matches
this mirror before relying on it.
"""

from unittest.mock import Mock

import pytest


class FakeProvider:
    def __init__(self, name, available=True, behaviour="ok"):
        self.name = name
        self._available = available
        self.behaviour = behaviour
        self.calls = 0

    def is_available(self):
        return self._available

    def generate(self, prompt):
        self.calls += 1
        if self.behaviour == "ok":
            return {"provider": self.name, "text": "review for " + prompt}
        raise Exception(self.name + " failed: " + self.behaviour)


def run_chain(providers, prompt):
    """Mirror of MultiProviderLLM.generate, over fake providers."""
    errors = []
    for provider in providers:
        if not provider.is_available():
            continue
        try:
            return provider.generate(prompt)
        except Exception as exc:
            errors.append(provider.name + ": " + str(exc)[:300])
            continue
    raise Exception("All LLM providers failed: " + " | ".join(errors))


def test_first_failure_then_second_succeeds():
    first = FakeProvider("gemini", behaviour="rate limited")
    second = FakeProvider("groq", behaviour="ok")
    result = run_chain([first, second], "review this")
    assert result["provider"] == "groq"
    assert first.calls == 1
    assert second.calls == 1


def test_unavailable_provider_is_skipped():
    skipped = FakeProvider("gemini", available=False)
    second = FakeProvider("groq", behaviour="ok")
    result = run_chain([skipped, second], "review this")
    assert result["provider"] == "groq"
    assert skipped.calls == 0


def test_all_providers_fail_raises_with_errors():
    providers = [
        FakeProvider("gemini", behaviour="rate limited"),
        FakeProvider("groq", behaviour="auth error"),
    ]
    with pytest.raises(Exception, match="All LLM providers failed"):
        run_chain(providers, "review this")
    with pytest.raises(Exception) as excinfo:
        run_chain(providers, "review this")
    assert "gemini" in str(excinfo.value)
    assert "groq" in str(excinfo.value)


def test_no_providers_raises():
    with pytest.raises(Exception, match="All LLM providers failed"):
        run_chain([], "review this")


def test_mocked_provider_failure_then_success():
    failing = Mock()
    failing.name = "groq"
    failing.is_available.return_value = True
    failing.generate.side_effect = Exception("429 rate limited")
    succeeding = Mock()
    succeeding.name = "cerebras"
    succeeding.is_available.return_value = True
    succeeding.generate.return_value = {"provider": "cerebras", "text": "ok"}
    result = run_chain([failing, succeeding], "review this")
    assert result["provider"] == "cerebras"
    assert failing.generate.call_count == 1
    assert succeeding.generate.call_count == 1


def test_order_is_preserved():
    first = FakeProvider("first", behaviour="ok")
    second = FakeProvider("second", behaviour="ok")
    result = run_chain([first, second], "review this")
    assert result["provider"] == "first"
    assert second.calls == 0
