"""
P0.5 — Model Adapter
=====================
A single interface over LLM providers so that the rest of MA-SET never
imports a provider SDK directly.  Supports three modes:

  stub     — returns canned responses; no network; safe for CI and rate-limit
             constrained environments (default when no key is set)
  gemini   — uses google-generativeai (free Flash tier)
  groq     — uses groq SDK (free tier)

Response caching
----------------
All real provider calls are cached on disk (via diskcache).  A cache key is
sha256(provider + model + prompt).  On a cache hit the adapter emits a
LLM_CACHE_HIT event instead of LLM_REQUEST + LLM_RESPONSE.

Usage
-----
    from ma_set.model.adapter import ModelAdapter, ModelConfig

    adapter = ModelAdapter(ModelConfig())          # auto-detects stub mode
    response = adapter.complete("Say hello", node="A1", agent="planner", run_id=run_id)
"""

from __future__ import annotations

import hashlib
import json
import os
import textwrap
import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Lazy imports for optional providers
# ---------------------------------------------------------------------------

def _import_gemini():
    try:
        import google.generativeai as genai  # type: ignore
        return genai
    except ImportError:
        raise ImportError(
            "google-generativeai is not installed.  "
            "Run: pip install google-generativeai"
        )


def _import_groq():
    try:
        from groq import Groq  # type: ignore
        return Groq
    except ImportError:
        raise ImportError(
            "groq is not installed.  Run: pip install groq"
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class Provider(str, Enum):
    STUB      = "stub"
    GEMINI    = "gemini"
    GROQ      = "groq"
    ANTHROPIC = "anthropic"
    OPENAI    = "openai"


class ModelConfig(BaseModel):
    """Runtime configuration for the model adapter."""

    provider: Provider = Field(
        default=Provider.STUB,
        description="LLM provider to use"
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model name"
    )
    groq_model: str = Field(
        default="llama3-8b-8192",
        description="Groq model name"
    )
    anthropic_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="Anthropic model name"
    )
    openai_model: str = Field(
        default="gpt-4o-2024-08-06",
        description="OpenAI model name"
    )
    temperature: float = Field(default=0.2)
    max_tokens: int = Field(default=2048)
    cache_dir: Path = Field(
        default=Path(".ma_set_cache"),
        description="Disk cache directory for LLM responses"
    )
    cache_enabled: bool = Field(default=True)
    stub_delay_s: float = Field(
        default=0.1,
        description="Simulated latency for stub responses (seconds)"
    )

    @classmethod
    def from_env(cls) -> "ModelConfig":
        """
        Auto-detect provider from environment variables.
        Falls back to stub if no API key is found.
        """
        if os.getenv("GEMINI_API_KEY"):
            return cls(provider=Provider.GEMINI)
        if os.getenv("ANTHROPIC_API_KEY"):
            return cls(provider=Provider.ANTHROPIC)
        if os.getenv("OPENAI_API_KEY"):
            return cls(provider=Provider.OPENAI)
        if os.getenv("GROQ_API_KEY"):
            return cls(provider=Provider.GROQ)
        return cls(provider=Provider.STUB)


# ---------------------------------------------------------------------------
# Stub responses
# ---------------------------------------------------------------------------

_STUB_RESPONSES: Dict[str, str] = {
    "default": (
        "[STUB] This is a canned response from the MA-SET stub adapter. "
        "Set GEMINI_API_KEY or GROQ_API_KEY to use a real provider."
    ),
    "plan": textwrap.dedent("""\
        [STUB PLAN]
        Task breakdown:
        1. Add input validation to the signup endpoint
        2. Return a 400 error for missing fields
        3. Write unit tests for the validation logic
        Acceptance criteria:
        - Missing email returns 400 with {"error": "email required"}
        - Missing password returns 400 with {"error": "password required"}
        - Valid payload returns 201
    """),
    "design": textwrap.dedent("""\
        [STUB DESIGN SPEC]
        Files to modify:
          - demo_target/app.py  (allowed)
        Files NOT to modify:
          - demo_target/legacy_billing.py  (PROTECTED)
        Proposed change:
          Add validate_signup() helper in app.py that raises ValueError on
          missing fields; call it in the /signup route.
    """),
    "diff": textwrap.dedent("""\
        [STUB DIFF]
        --- a/demo_target/app.py
        +++ b/demo_target/app.py
        @@ -12,6 +12,12 @@
        +def validate_signup(data):
        +    for field in ("email", "password"):
        +        if not data.get(field):
        +            raise ValueError(f"{field} required")
        +
         @app.route("/signup", methods=["POST"])
         def signup():
        -    user = User(request.json)
        +    try:
        +        validate_signup(request.json or {})
        +    except ValueError as exc:
        +        return jsonify({"error": str(exc)}), 400
        +    user = User(request.json)
    """),
    "review": "[STUB REVIEW] Approved. Diff matches design spec. All tests passing.",
    "release_notes": "[STUB RELEASE NOTES] v0.1.1 — Added signup validation (DEMO-001).",
}


def _pick_stub_response(prompt: str) -> str:
    """Choose a canned stub response based on keywords in the prompt."""
    pl = prompt.lower()
    if any(k in pl for k in ("plan", "ticket", "breakdown", "story")):
        return _STUB_RESPONSES["plan"]
    if any(k in pl for k in ("design", "spec", "architect", "impact")):
        return _STUB_RESPONSES["design"]
    if any(k in pl for k in ("implement", "diff", "code", "develop")):
        return _STUB_RESPONSES["diff"]
    if any(k in pl for k in ("review", "verify", "verdict")):
        return _STUB_RESPONSES["review"]
    if any(k in pl for k in ("release", "notes", "changelog")):
        return _STUB_RESPONSES["release_notes"]
    return _STUB_RESPONSES["default"]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(provider: str, model: str, prompt: str) -> str:
    h = hashlib.sha256(f"{provider}|{model}|{prompt}".encode()).hexdigest()
    return h


class _DiskCache:
    """Thin wrapper around diskcache (or a plain JSON file if diskcache absent)."""

    def __init__(self, cache_dir: Path):
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            import diskcache  # type: ignore
            self._cache = diskcache.Cache(str(cache_dir))
            self._backend = "diskcache"
        except ImportError:
            self._cache = None  # type: ignore
            self._backend = "json"

    def get(self, key: str) -> Optional[str]:
        if self._backend == "diskcache":
            return self._cache.get(key)  # type: ignore
        path = self._dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())["response"]
        return None

    def set(self, key: str, value: str) -> None:
        if self._backend == "diskcache":
            self._cache.set(key, value)  # type: ignore
            return
        path = self._dir / f"{key}.json"
        path.write_text(json.dumps({"response": value}))


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

class ModelAdapter:
    """
    Unified LLM interface for MA-SET.

    Parameters
    ----------
    config : ModelConfig
        Runtime configuration (provider, model names, cache settings).
    event_callback : callable, optional
        Called with an Event dict after each LLM interaction.
        Signature: callback(event_dict: dict) -> None
    """

    def __init__(
        self,
        config: Optional[ModelConfig] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = config or ModelConfig.from_env()
        self._event_callback = event_callback
        self._cache = _DiskCache(self.config.cache_dir) if self.config.cache_enabled else None
        self._call_count = 0
        self._token_count = 0

        # Initialise real providers lazily
        self._gemini_model = None
        self._groq_client = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_stub(self) -> bool:
        """Return True if adapter is configured in stub mode."""
        return self.config.provider == Provider.STUB

    @property
    def call_count(self) -> int:
        """Number of LLM calls made by this adapter."""
        return self._call_count

    @property
    def token_count(self) -> int:
        """Estimated number of tokens consumed."""
        return self._token_count

    def complete(
        self,
        prompt: str,
        *,
        node: str = "system",
        agent: str = "unknown",
        run_id: str = "no-run",
        system_prompt: Optional[str] = None,
        system: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Send a prompt to the configured provider and return the response text.

        All parameters except *prompt* are used for event emission only.
        """
        effective_sys = system_prompt or system or kwargs.get("system_prompt")

        if self.config.provider == Provider.STUB:
            return self._stub_complete(prompt, node=node, agent=agent, run_id=run_id)

        cache_key = _cache_key(self.config.provider, self._active_model(), prompt)
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._emit({
                    "run_id": run_id, "node": node, "agent": agent,
                    "event_type": "llm_cache_hit",
                    "payload": {"model": self._active_model(), "key": cache_key[:8] + "..."},
                })
                return cached

        self._emit({
            "run_id": run_id, "node": node, "agent": agent,
            "event_type": "llm_request",
            "payload": {"provider": self.config.provider, "model": self._active_model(),
                        "prompt_chars": len(prompt)},
        })

        try:
            if self.config.provider == Provider.GEMINI:
                response = self._gemini_complete(prompt, system_prompt=effective_sys)
            elif self.config.provider == Provider.ANTHROPIC:
                response = self._anthropic_complete(prompt, system_prompt=effective_sys)
            elif self.config.provider == Provider.OPENAI:
                response = self._openai_complete(prompt, system_prompt=effective_sys)
            else:
                response = self._groq_complete(prompt, system_prompt=effective_sys)

            self._call_count += 1
            if self._cache and cache_key:
                self._cache.set(cache_key, response)

            self._emit({
                "run_id": run_id, "node": node, "agent": agent,
                "event_type": "llm_response",
                "payload": {"chars": len(response), "call_count": self._call_count},
            })
            return response

        except Exception as exc:
            self._emit({
                "run_id": run_id, "node": node, "agent": agent,
                "event_type": "llm_error",
                "payload": {"error": str(exc)},
            })
            raise

    @property
    def stats(self) -> Dict[str, int]:
        return {"call_count": self._call_count, "token_count": self._token_count}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stub_complete(self, prompt: str, *, node: str, agent: str, run_id: str) -> str:
        time.sleep(self.config.stub_delay_s)
        response = _pick_stub_response(prompt)
        self._call_count += 1
        self._emit({
            "run_id": run_id, "node": node, "agent": agent,
            "event_type": "llm_stub_response",
            "payload": {"prompt_chars": len(prompt), "response_chars": len(response)},
        })
        return response

    def _active_model(self) -> str:
        if self.config.provider == Provider.GEMINI:
            return self.config.gemini_model
        if self.config.provider == Provider.ANTHROPIC:
            return self.config.anthropic_model
        if self.config.provider == Provider.OPENAI:
            return self.config.openai_model
        if self.config.provider == Provider.GROQ:
            return self.config.groq_model
        return "stub"

    def _gemini_complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        genai = _import_gemini()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)
        candidate_models = [self.config.gemini_model, "gemini-flash-latest", "gemini-2.5-flash", "gemini-1.5-flash"]
        last_exc = None
        for model_name in candidate_models:
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_prompt or "You are a helpful software engineering AI.",
                )
                result = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=self.config.temperature,
                        max_output_tokens=self.config.max_tokens,
                    ),
                )
                return result.text
            except Exception as e:
                last_exc = e
                continue
        raise last_exc or RuntimeError("All Gemini candidate models failed")

    def _anthropic_complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set")
        import urllib.request
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        body: Dict[str, Any] = {
            "model": self.config.anthropic_model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "".join(b.get("text", "") for b in data.get("content", []))

    def _openai_complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY not set")
        import urllib.request
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self.config.openai_model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _groq_complete(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        Groq = _import_groq()
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not set")
        if self._groq_client is None:
            self._groq_client = Groq(api_key=api_key)
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        chat = self._groq_client.chat.completions.create(
            model=self.config.groq_model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return chat.choices[0].message.content

    def _emit(self, event_dict: Dict[str, Any]) -> None:
        """Fire event to the callback if one is registered."""
        if self._event_callback:
            try:
                self._event_callback(event_dict)
            except Exception:
                pass  # Never let telemetry crash the agent


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = ModelConfig(provider=Provider.STUB)
    events_seen: List[Dict] = []

    adapter = ModelAdapter(cfg, event_callback=events_seen.append)

    print("=== Stub mode test ===")
    for prompt in ["Plan the ticket", "Design the solution", "Implement the change", "Review the diff"]:
        resp = adapter.complete(prompt, node="A1", agent="planner", run_id="test-run")
        print(f"\n[prompt] {prompt!r}\n[response] {resp[:120]}...")

    print(f"\nStats: {adapter.stats}")
    print(f"Events emitted: {len(events_seen)}")
    for e in events_seen:
        print(f"  {e['event_type']}")
