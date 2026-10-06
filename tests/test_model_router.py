"""Model router: capability filters, health ranking, cooldown exclusion."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import config
import model_router
from quota_governor import get_governor


def _enable(clean_env, *keys: str):
    clean_env.setenv("FREE_MODEL_ROUTING", "true")
    for key in keys:
        clean_env.setenv(f"{key.upper()}_API_KEY", "test-key")
        if key == "cloudflare":
            clean_env.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    return clean_env


def test_json_roles_require_structured_output(clean_env, tmp_path):
    _enable(clean_env, "groq")
    # Every groq seed supports response_format -> json candidates exist.
    ranked = model_router.rank_candidates("planner", workspace_root=tmp_path)
    assert ranked
    assert {c.pdef.key for c in ranked} == {"groq"}
    assert all(c.model.response_format or c.model.structured_outputs
               for c in ranked)


def test_longform_excludes_low_tpm_provider(clean_env, tmp_path):
    _enable(clean_env, "groq", "gemini")
    ranked = model_router.rank_candidates("builder", workspace_root=tmp_path)
    assert ranked
    keys = {c.pdef.key for c in ranked}
    # Groq's 8k TPM disqualifies it for long builder generations.
    assert "groq" not in keys
    assert "gemini" in keys


def test_disabled_free_routing_returns_empty(clean_env, tmp_path, monkeypatch):
    _enable(clean_env, "groq")
    monkeypatch.setattr(config, "FREE_MODEL_ROUTING", False)
    assert model_router.rank_candidates("planner",
                                        workspace_root=tmp_path) == []


def test_cooldown_excludes_provider(clean_env, tmp_path):
    _enable(clean_env, "groq")
    governor = get_governor(tmp_path)
    governor.set_cooldown("groq", 120, reason="test")
    assert model_router.rank_candidates("planner",
                                        workspace_root=tmp_path) == []


def test_health_degrades_ranking(clean_env, tmp_path):
    """A model that mostly works loses rank but stays in rotation.

    The ratio is chosen so the outcome lands between "untried" (health 0.60)
    and the quarantine line (success <= 0.10): degraded enough to lose first
    place, not so degraded that it is thrown out of the pool.
    """
    _enable(clean_env, "groq")
    before = model_router.rank_candidates("planner", workspace_root=tmp_path)
    top = before[0]
    for _ in range(10):
        model_router.record_call(top.pdef.key, top.model.model, "planner",
                                 "ok", workspace_root=tmp_path)
    for _ in range(10):
        model_router.record_call(top.pdef.key, top.model.model, "planner",
                                 "error", workspace_root=tmp_path)
    after = model_router.rank_candidates("planner", workspace_root=tmp_path)
    assert after
    failed_score = next(c.score for c in after
                        if c.model.model == top.model.model)
    assert failed_score < top.score
    assert not model_router.is_quarantined(top.pdef.key, top.model.model,
                                           workspace_root=tmp_path)
    assert after[0].model.model != top.model.model


def test_never_responded_model_leaves_rotation(clean_env, tmp_path):
    """0 successes is a fact at a low sample size, not a noisy rate (v2.9.1).

    The 20-call quarantine bar exists because a *rate* over few observations is
    noise.  "Has never once answered" is not a rate estimate, so it acts at
    ``QUARANTINE_MIN_CALLS_ZERO_OK``.  This matters operationally: two nvidia
    models each held an authoring attempt for the full 360 s call budget on
    repeat, because a timeout counts as a transient failure and 2 < 20.
    """
    _enable(clean_env, "groq")
    before = model_router.rank_candidates("planner", workspace_root=tmp_path)
    top = before[0]
    for _ in range(model_router.QUARANTINE_MIN_CALLS_ZERO_OK):
        model_router.record_call(top.pdef.key, top.model.model, "planner",
                                 "timeout", workspace_root=tmp_path)
    assert model_router.is_quarantined(top.pdef.key, top.model.model,
                                       workspace_root=tmp_path)
    after = model_router.rank_candidates("planner", workspace_root=tmp_path)
    assert all(c.model.model != top.model.model for c in after)


def test_latency_score_is_not_a_reward_for_silence(clean_env, tmp_path):
    """An unmeasured latency must be neutral, never perfect (v2.9.1).

    ``latency_ewma`` starts at 0.0 and is only written when a call returns, so
    the old ``latency <= 0`` clause scored a model that had never responded as
    the fastest in the pool -- on 15% of its health.
    """
    never_answered = {"calls": 3, "ok": 0, "latency_ewma": 0.0}
    assert model_router._latency_score(never_answered) < 0.5
    fast = {"calls": 3, "ok": 3, "latency_ewma": 4.0}
    assert model_router._latency_score(fast) == 1.0
    untried = {"calls": 0, "ok": 0, "latency_ewma": 0.0}
    assert model_router._latency_score(untried) == 0.5


def test_record_outcome_and_parse(clean_env, tmp_path):
    usage = {"provider": "groq", "model": "openai/gpt-oss-120b",
             "role": "planner"}
    model_router.record_parse(False, usage, workspace_root=tmp_path)
    model_router.record_outcome(usage, True, workspace_root=tmp_path)
    health = model_router._load_json(
        model_router._health_path(tmp_path), {})
    entry = health["entries"]["groq|openai/gpt-oss-120b|planner"]
    assert entry["parse_fail"] == 1
    assert entry["outcomes_ok"] == 1


def test_next_reset_iso_is_future(tmp_path, clean_env):
    _enable(clean_env, "groq")
    reset = model_router.next_reset_iso(workspace_root=tmp_path)
    assert datetime.fromisoformat(reset) > datetime.now(timezone.utc)


def test_catalog_conversion_filters_nonzero_pricing():
    entries = [
        {"id": "free/model:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 100000, "supported_parameters": ["structured_outputs"],
         "top_provider": {"max_completion_tokens": 32000},
         "architecture": {"output_modalities": ["text"]}},
        {"id": "paid/model", "pricing": {"prompt": "0.1", "completion": "0.2"},
         "context_length": 100000,
         "architecture": {"output_modalities": ["text"]}},
        {"id": "audio/model:free", "pricing": {"prompt": "0", "completion": "0"},
         "context_length": 100000,
         "architecture": {"output_modalities": ["audio"]}},
        {"id": "openrouter/free", "pricing": {"prompt": "0", "completion": "0"}},
    ]
    models = model_router._openrouter_models_from_catalog(entries)
    assert [m.model for m in models] == ["free/model:free"]


def test_verify_providers_reports_ok_and_errors(clean_env, tmp_path):
    _enable(clean_env, "groq")

    class _FakeLLM:
        async def raw_complete(self, provider, model, system, user):
            if provider == "groq":
                return "OK"
            raise RuntimeError("boom")

    results = asyncio.run(
        model_router.verify_providers(_FakeLLM(), tmp_path))
    assert len(results) == 1
    assert results[0]["provider"] == "groq" and results[0]["ok"]
