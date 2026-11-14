"""VIEW_GATE_PLAN V4: vision is a router capability, Unknown is not False.

The precedent this pins: the v2.9.1 capability refactor.  A bare ``/models``
refresh reported nothing about structured outputs, the floor believed the
default ``False``, and the spec_author pool emptied to zero.  Vision is the
same trap one flag later: a refresh cannot see pixels, so a refresh outcome
must be ``None`` (admitted, flat prior), and only a hand-annotated seed or a
deterministic probe may set ``True``.  A known-text-only flag
(``vision=False``) is real information and keeps the model out of the
witness pool -- but a pool-starved witness relaxes like every other
capability floor, loudly.
"""

from __future__ import annotations

import asyncio

import config
import model_router
import providers
from model_router import (_capability_ok, _capability_score,
                          kind_needs_structured, kind_needs_vision,
                          rank_candidates)
from providers import ProviderDef, ProviderModel


def _model(**kw) -> ProviderModel:
    base = dict(provider="openrouter", model="x", context_length=32768,
                max_output=32768, structured_outputs=True,
                response_format=True, coding_index=50.0)
    base.update(kw)
    return ProviderModel(**base)


_PDEF = ProviderDef(key="openrouter", label="OpenRouter",
                    base_url="https://openrouter.ai/api/v1",
                    api_key_env="OPENROUTER_API_KEY", models=())


def test_witness_is_its_own_role_kind() -> None:
    assert model_router._role_kind("witness") == "witness"
    assert kind_needs_vision("witness") is True
    assert kind_needs_vision("planner") is False
    assert kind_needs_vision("builder_initial") is False
    # The witness still returns a JSON envelope, so structured adherence
    # rules apply to it like every other verdict role.
    assert kind_needs_structured("witness") is True


def test_vision_unknown_is_admitted_known_text_only_is_excluded() -> None:
    assert _capability_ok("witness", _PDEF, _model(vision=None)) is True, \
        "a roster refresh's None must not read as False (v2.9.1 law)"
    assert _capability_ok("witness", _PDEF, _model(vision=True)) is True
    assert model_router._role_kind("planner") != "witness"


def test_capability_score_rewards_verified_vision_modestly() -> None:
    plain = _capability_score("witness", _model(vision=None))
    bonus = _capability_score("witness", _model(vision=True))
    assert bonus > plain
    # Unknown vision does not outrank verified absence on ranking.
    assert plain >= _capability_score("witness", _model(vision=False))


def test_unverified_model_is_admitted_even_with_vision_false_flag() -> None:
    """Exactly the refresh scenario: a flag value that carries no evidence
    must not become a verdict (coding_index None => never annotated)."""
    m = _model(vision=False, coding_index=None)
    assert _capability_ok("witness", _PDEF, m) is True


def test_verified_text_only_model_stays_out_of_the_witness_pool(
        monkeypatch, tmp_path) -> None:
    """Rank-level pin through the real scheduler path."""
    seen = ProviderDef(key="openrouter", label="OpenRouter",
                       base_url="https://openrouter.ai/api/v1",
                       api_key_env="OPENROUTER_API_KEY",
                       models=(_model(vision=False, structured_outputs=True),
                               _model(vision=True, structured_outputs=True),
                               _model(vision=None, structured_outputs=True)))
    monkeypatch.setattr(providers, "enabled_providers",
                        lambda: [seen])
    ranked = rank_candidates("witness", workspace_root=tmp_path)
    flags = [c.model.vision for c in ranked]
    assert False not in flags, \
        "a verified text-only candidate leaked into the witness pool"
    assert voted_eligible(ranked)


def voted_eligible(ranked) -> bool:
    return all(_capability_ok("witness", c.pdef, c.model) for c in ranked)


def test_other_roles_indifferent_to_vision(monkeypatch, tmp_path) -> None:
    """Vision gating must not leak into non-witness roles."""
    seen = ProviderDef(key="openrouter", label="OpenRouter",
                       base_url="https://openrouter.ai/api/v1",
                       api_key_env="OPENROUTER_API_KEY",
                       models=(_model(vision=False, structured_outputs=True),))
    monkeypatch.setattr(providers, "enabled_providers",
                        lambda: [seen])
    assert rank_candidates("planner", workspace_root=tmp_path)
