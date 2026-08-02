"""
Multi-provider LLM client with automatic fallback.

Providers, in fallback order (only those with a configured API key are used):

    1. Gemini      — multi-key rotation + multi-model (gemini-2.5-flash -> gemini-2.0-flash)
    2. Groq        — OpenAI-compatible (llama-3.3-70b-versatile, openai/gpt-oss-120b)
    3. Cerebras    — OpenAI-compatible (gpt-oss-120b, zai-glm-4.7)
    4. OpenRouter  — OpenAI-compatible, two keys (meta-llama/llama-3.3-70b-instruct:free, ...)
    5. SwiftRouter — OpenAI-compatible (glm-4.7, command-r-08-2024)
    6. xAI/Grok    — OpenAI-compatible (grok-4, grok-3)
    7. LLMApi.ai   — backup (gpt-4o)
    8. APIFreeLLM  — backup

If a provider errors, rate-limits (429), or times out, the next available
provider automatically takes over — so PRPilot keeps reviewing even when
free tiers throttle.
"""
import os
import time
from abc import ABC, abstractmethod
from typing import Optional, List, Dict
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Standard response format from any LLM provider."""
    text: str
    provider: str
    model: str
    tokens_used: int = 0


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def generate(self, prompt: str) -> LLMResponse:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini provider with key rotation and multi-model fallback."""

    def __init__(self, api_keys: List[str], models: Optional[List[str]] = None):
        self.api_keys = api_keys
        self.models = models or ["gemini-2.5-flash", "gemini-2.0-flash"]
        self.current_key_index = 0
        self.current_model_index = 0
        self.rate_limited_until: Dict[str, float] = {}  # key -> timestamp
        self._genai = None
        self._model = None

    @property
    def name(self) -> str:
        return "gemini"

    def _key_in_cooldown(self, key: str) -> bool:
        """Non-mutating check: is this key currently cooled down?"""
        until = self.rate_limited_until.get(key, 0)
        return bool(until) and time.time() < until

    def _get_next_available_key(self) -> Optional[str]:
        """Get next available key that isn't in cooldown."""
        for _ in range(len(self.api_keys)):
            key = self.api_keys[self.current_key_index]
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)

            if not self._key_in_cooldown(key):
                return key

        return None  # All keys in cooldown

    def is_available(self) -> bool:
        return len(self.api_keys) > 0 and any(
            not self._key_in_cooldown(k) for k in self.api_keys
        )

    def generate(self, prompt: str) -> LLMResponse:
        from google import genai

        max_attempts = len(self.api_keys) * len(self.models)
        errors = []

        for _ in range(max_attempts):
            key = self._get_next_available_key()
            if not key:
                break

            model = self.models[self.current_model_index]
            self.current_model_index = (self.current_model_index + 1) % len(self.models)

            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                text = response.text
                if not text or not text.strip():
                    errors.append(f"{model}: empty response")
                    continue
                return LLMResponse(
                    text=text,
                    provider="gemini",
                    model=model
                )
            except Exception as e:
                error_msg = str(e)
                low = error_msg.lower()
                code = getattr(e, "code", None)
                code_num = int(code) if code is not None else None

                # grpc StatusCode: 8 = RESOURCE_EXHAUSTED (429), 7 = PERMISSION_DENIED,
                # 16 = UNAUTHENTICATED. Fall back to string checks as a safety net.
                is_rate_limited = (
                    code_num == 8
                    or "ResourceExhausted" in error_msg
                    or "429" in error_msg
                    or "RESOURCE_EXHAUSTED" in error_msg
                    or "rate" in low
                )
                is_auth_error = (
                    code_num in (7, 16)
                    or "API key not valid" in error_msg
                    or "invalid api key" in low
                    or "unauthorized" in low
                    or "forbidden" in low
                )

                if is_rate_limited:
                    # Mark this key as rate limited for 60 seconds
                    self.rate_limited_until[key] = time.time() + 60
                    errors.append(f"{model} (key rate limited)")
                elif is_auth_error:
                    # Bad/revoked key: cool down long so we stop wasting calls
                    self.rate_limited_until[key] = time.time() + 3600
                    errors.append(f"{model} (key auth error)")
                else:
                    errors.append(f"{model}: {error_msg[:150]}")
                continue

        raise Exception(
            f"All Gemini attempts failed: {'; '.join(errors) or 'no keys configured'}"
        )


class OpenAICompatProvider(LLMProvider):
    """
    Generic OpenAI-compatible chat provider.

    Used for Groq, Cerebras, OpenRouter (two keys) and SwiftRouter.
    Supports multi-key rotation, multi-model fallback, per-key rate-limit
    cooldown, and timeouts — so a dead provider is skipped automatically.
    """

    def __init__(
        self,
        name: str,
        api_keys: List[str],
        base_url: str,
        models: List[str],
        timeout: float = 60.0,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self._name = name
        self.api_keys = api_keys
        self.base_url = base_url
        self.models = models or [""]
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.current_key_index = 0
        self.current_model_index = 0
        self.rate_limited_until: Dict[str, float] = {}  # key -> timestamp

    @property
    def name(self) -> str:
        return self._name

    def _key_in_cooldown(self, key: str) -> bool:
        """Non-mutating check: is this key currently cooled down?"""
        until = self.rate_limited_until.get(key, 0)
        return bool(until) and time.time() < until

    def _get_next_available_key(self) -> Optional[str]:
        """Get next available key that isn't in cooldown."""
        for _ in range(len(self.api_keys)):
            key = self.api_keys[self.current_key_index]
            self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)

            if not self._key_in_cooldown(key):
                return key

        return None  # All keys in cooldown

    def is_available(self) -> bool:
        return len(self.api_keys) > 0 and any(
            not self._key_in_cooldown(k) for k in self.api_keys
        )

    def generate(self, prompt: str) -> LLMResponse:
        from openai import OpenAI

        max_attempts = len(self.api_keys) * len(self.models)
        errors = []

        for _ in range(max_attempts):
            key = self._get_next_available_key()
            if not key:
                break

            model = self.models[self.current_model_index]
            self.current_model_index = (self.current_model_index + 1) % len(self.models)

            try:
                client = OpenAI(
                    api_key=key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                    max_retries=0,
                    default_headers=self.extra_headers or None,
                )
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=4096,
                )
                text = response.choices[0].message.content
                if not text or not text.strip():
                    errors.append(f"{model}: empty response")
                    continue
                tokens_used = response.usage.total_tokens if response.usage else 0
                return LLMResponse(
                    text=text,
                    provider=self._name,
                    model=model,
                    tokens_used=tokens_used
                )
            except Exception as e:
                msg = str(e)
                status = getattr(e, "status_code", None)
                low = msg.lower()
                if (
                    status == 429
                    or "429" in msg
                    or "rate" in low
                    or "quota" in low
                    or "limit" in low
                ):
                    # Rate limited: cool this key down briefly
                    self.rate_limited_until[key] = time.time() + 60
                    errors.append(f"{model}: rate limited")
                elif (
                    status in (401, 403)
                    or "401" in msg
                    or "403" in msg
                    or "invalid api key" in low
                    or "forbidden" in low
                ):
                    # Bad/revoked key: cool down long so we stop wasting calls
                    self.rate_limited_until[key] = time.time() + 3600
                    errors.append(f"{model}: auth error")
                else:
                    errors.append(f"{model}: {msg[:200]}")
                continue

        raise Exception(
            f"All {self._name} attempts failed: "
            f"{'; '.join(errors) or 'no keys configured'}"
        )


class LLMApiProvider(LLMProvider):
    """LLMApi.ai provider (backup)."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model_name = model

    @property
    def name(self) -> str:
        return "llmapi"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str) -> LLMResponse:
        import urllib.request
        import urllib.error
        import json

        url = "https://api.llmapi.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}]
        }

        req = urllib.request.Request(
            url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP Error: {e.code} {e.reason} - {e.read().decode('utf-8')}")
        except Exception as e:
            raise Exception(str(e))

        text = res_json["choices"][0]["message"]["content"]
        if not text or not text.strip():
            raise Exception("Empty response from LLMApi")

        return LLMResponse(
            text=text,
            provider="llmapi",
            model=self.model_name
        )


class APIFreeProvider(LLMProvider):
    """APIFreeLLM provider (backup)."""

    def __init__(self, api_key: str, model: str = "apifreellm"):
        self.api_key = api_key
        self.model_name = model

    @property
    def name(self) -> str:
        return "apifreellm"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str) -> LLMResponse:
        import urllib.request
        import urllib.error
        import json

        url = "https://apifreellm.com/api/v1/chat"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "message": prompt,
            "model": self.model_name
        }

        req = urllib.request.Request(
            url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
        except urllib.error.HTTPError as e:
            raise Exception(f"HTTP Error: {e.code} {e.reason} - {e.read().decode('utf-8')}")
        except Exception as e:
            raise Exception(str(e))

        text = res_json.get("response", "")
        if not text or not text.strip():
            raise Exception("Empty response from APIFreeLLM")

        return LLMResponse(
            text=text,
            provider="apifreellm",
            model=res_json.get("model", self.model_name)
        )


class MultiProviderLLM:
    """
    Multi-provider LLM client with automatic fallback.

    Tries providers in order (Gemini -> Groq -> Cerebras -> OpenRouter ->
    SwiftRouter -> LLMApi -> APIFree). If a provider fails, raises, times out,
    or is rate limited, the next available provider is used instead.
    """

    def __init__(self):
        self.providers: List[LLMProvider] = []
        self._load_providers()

    def _load_providers(self):
        """Load providers from environment variables (in fallback order)."""

        # 1. Gemini (multi-key, multi-model)
        gemini_keys = []
        multi_keys = os.environ.get("GEMINI_API_KEYS", "").strip()
        if multi_keys:
            gemini_keys.extend([k.strip() for k in multi_keys.split(",") if k.strip()])
        single_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if single_key and single_key not in gemini_keys:
            gemini_keys.append(single_key)

        if gemini_keys:
            self.providers.append(GeminiProvider(gemini_keys))

        # 2. Groq (OpenAI-compatible)
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if groq_key:
            self.providers.append(OpenAICompatProvider(
                name="groq",
                api_keys=[groq_key],
                base_url="https://api.groq.com/openai/v1",
                models=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"],
                timeout=45,
            ))

        # 3. Cerebras (OpenAI-compatible)
        cerebras_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
        if cerebras_key:
            self.providers.append(OpenAICompatProvider(
                name="cerebras",
                api_keys=[cerebras_key],
                base_url="https://api.cerebras.ai/v1",
                models=["gpt-oss-120b", "zai-glm-4.7"],
                timeout=60,
            ))

        # 4. OpenRouter (two keys, OpenAI-compatible)
        openrouter_keys = [
            os.environ.get("OPENROUTER_API_KEY_1", "").strip(),
            os.environ.get("OPENROUTER_API_KEY_2", "").strip(),
        ]
        openrouter_keys = [k for k in openrouter_keys if k]
        if openrouter_keys:
            self.providers.append(OpenAICompatProvider(
                name="openrouter",
                api_keys=openrouter_keys,
                base_url="https://openrouter.ai/api/v1",
                models=[
                    "meta-llama/llama-3.3-70b-instruct:free",
                    "openai/gpt-oss-120b:free",
                ],
                timeout=60,
                extra_headers={
                    "HTTP-Referer": "https://github.com",
                    "X-Title": "PRPilot",
                },
            ))

        # 5. SwiftRouter (OpenAI-compatible)
        swiftrouter_key = os.environ.get("SWIFTROUTER_API_KEY", "").strip()
        if swiftrouter_key:
            self.providers.append(OpenAICompatProvider(
                name="swiftrouter",
                api_keys=[swiftrouter_key],
                base_url="https://api.swiftrouter.com/v1",
                models=["glm-4.7", "command-r-08-2024"],
                timeout=90,
            ))

        # 6. xAI / Grok (OpenAI-compatible)
        xai_key = os.environ.get("XAI_API_KEY", "").strip()
        if xai_key:
            self.providers.append(OpenAICompatProvider(
                name="xai",
                api_keys=[xai_key],
                base_url="https://api.x.ai/v1",
                models=["grok-4", "grok-3"],
                timeout=90,
            ))

        # 7. LLMApi Backup
        llmapi_key = os.environ.get("LLMAPI_API_KEY", "").strip()
        if llmapi_key:
            self.providers.append(LLMApiProvider(llmapi_key))

        # 8. APIFree Backup
        apifree_key = os.environ.get("APIFREE_API_KEY", "").strip()
        if apifree_key:
            self.providers.append(APIFreeProvider(apifree_key))

    def generate(self, prompt: str) -> LLMResponse:
        """
        Generate content using available providers.
        Falls back to the next provider on failure.
        """
        errors = []

        for provider in self.providers:
            if not provider.is_available():
                continue

            try:
                response = provider.generate(prompt)
                return response
            except Exception as e:
                errors.append(f"{provider.name}: {str(e)[:300]}")
                continue

        # All providers failed
        raise Exception(f"All LLM providers failed: {' | '.join(errors)}")

    def get_status(self) -> dict:
        """Get status of all providers."""
        return {
            "providers": [
                {
                    "name": p.name,
                    "available": p.is_available(),
                    "models": getattr(p, "models", [getattr(p, "model_name", "")]),
                }
                for p in self.providers
            ]
        }


# Global instance
_llm_client: Optional[MultiProviderLLM] = None


def get_llm_client() -> MultiProviderLLM:
    """Get or create the global LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = MultiProviderLLM()
    return _llm_client


def reset_llm_client():
    """Reset the global LLM client."""
    global _llm_client
    _llm_client = None
