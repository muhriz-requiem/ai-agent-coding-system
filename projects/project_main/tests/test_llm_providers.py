"""Provider-agnostic LLM env plumbing (2026-11-08 OpenCode Go retarget).

Ensures ``LLMClient`` resolves credentials/endpoint from the environment
with the documented precedence, keeps the historic OpenRouter variables
working, and honors explicit constructor arguments over everything.
No network access: only the lazy ``openai.AsyncOpenAI`` construction is
inspected.
"""

from openai import AsyncOpenAI

from src.agents.llm import LLMClient


def test_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    client = LLMClient(api_key="arg-key", base_url="https://arg.example/v1",
                       model="arg-model")
    assert client.api_key == "arg-key"
    assert client.base_url == "https://arg.example/v1"
    assert client.model == "arg-model"


def test_llm_env_vars_win_over_openrouter(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "go-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://opencode.ai/inference/go/openai/v1")
    monkeypatch.setenv("LLM_MODEL", "glm-5.3-flash")
    client = LLMClient()
    assert client.api_key == "go-key"
    assert client.base_url == "https://opencode.ai/inference/go/openai/v1"
    assert client.model == "glm-5.3-flash"


def test_openrouter_fallback_kept_when_llm_key_absent(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-key")
    client = LLMClient()
    assert client.api_key == "legacy-key"
    assert client.base_url is None  # default (OpenRouter) applied at request time
    assert client.model == LLMClient().model


def test_client_construction_uses_base_url(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://opencode.ai/inference/go/openai/v1")
    monkeypatch.setenv("LLM_API_KEY", "go-key")
    handle = LLMClient()._get_client()
    assert isinstance(handle, AsyncOpenAI)
    assert str(handle.base_url).rstrip("/") == "https://opencode.ai/inference/go/openai/v1"
    assert handle.api_key == "go-key"


def test_untouched_env_unchanged(monkeypatch):
    import pytest as _pytest

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = LLMClient()
    assert client.api_key is None
    assert client.base_url is None
    # No key anywhere -> the lazy client construction still refuses (the
    # same error the pre-2026-11-08 code produced); `_components` catches
    # it and degrades to client=None (per-analyst neutral placeholders).
    with _pytest.raises(Exception):
        client._get_client()
