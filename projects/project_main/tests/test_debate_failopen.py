"""Fail-open debate isolation (2026-11-08 cloud finding).

One debate-stage LLM error used to abort the whole batch
(``asyncio.gather`` without isolation and an unguarded ``run_debate``);
the cloud test run showed all 28 tickers die on a single
``LLMError: unbalanced JSON object``.  Pinned contracts:

1. a debate component raising degrades THAT ticker to the neutral
   ``NO-DATA`` sentinel: pipeline completes, ``winner == 'undecided'``,
   citations non-empty (citations gate keeps passing), other tickers
   unaffected;
2. a cheap cycle whose precomputed debate is absent/None degrades to the
   same sentinel instead of crashing ``evaluate_risk``.
"""

import asyncio

import pandas as pd

from src.pipeline.graph import run_pipeline
from src.agents.models import (AnalystReport, DebateRecord, RiskDecision)


def _report(ticker: str) -> AnalystReport:
    return AnalystReport.model_validate({
        "agent": "fundamental", "ticker": ticker, "stance": "neutral",
        "confidence": 0.5, "thesis": "flat",
        "citations": ["NO-DATA: debate unavailable this run"]})


def _risk(ticker: str, veto_reasons=None) -> RiskDecision:
    return RiskDecision.model_validate({
        "ticker": ticker, "approved": not veto_reasons,
        "veto_reasons": veto_reasons or []})


def _components(tickers, debate_fn):
    """Pipeline component dict mirroring test_pipeline's offline shape."""

    calls = []

    def fetch_ohlcv(ticker, period="6mo"):
        return pd.Series([100.0, 101.0, 99.0] * 10)

    def fetch_fundamentals(ticker):
        return {"gross_margin": 0.4}

    def fetch_news(ticker):
        return [{"title": "headline", "publisher": "p", "url": "u"}]

    def generate_signal(prices, regime=None):
        calls.append("quant")
        return {"signal": "HOLD", "confidence": 0.5, "z_score": 0.1,
                "momentum": 0.0, "reference_price": 100.0}

    def run_analysts(ticker, inputs, client=None):
        calls.append(f"analysts:{ticker}")
        return {"fundamental": _report(ticker)}

    def evaluate_risk(ticker, reports, debate, quant, account,
                      proposed_position_pct=None, flow_data=None):
        calls.append(f"risk:{ticker}")
        reasons = []
        # the real citations gate: a sentinel debate must NOT trip it
        for report in reports.values():
            if not report.citations:
                reasons.append(f"missing citations: {report.agent}")
        if not debate.citations:
            reasons.append("missing citations: debate")
        return _risk(ticker, reasons)

    def build_order_plan(decisions, signals, account, day_trade_dates,
                         **kwargs):
        return []

    def broker_submit(orders):
        return []

    components = {
        "account": {"equity": 100000.0, "max_position_pct": 0.10},
        "day_trade_dates": [],
        "tickers": list(tickers),
        "fetch_ohlcv": fetch_ohlcv,
        "fetch_fundamentals": fetch_fundamentals,
        "fetch_news": fetch_news,
        "regime_snapshot": None,
        "submit": broker_submit,
        "broker_submit": broker_submit,
        "generate_signal": generate_signal,
        "run_analysts": run_analysts,
        "run_debate": debate_fn,
        "evaluate_risk": evaluate_risk,
        "build_order_plan": build_order_plan,
        "client": None,
    }
    return components, calls


def _decision_map(result):
    return {d["ticker"]: d for d in result}


def test_debate_failure_degrades_that_ticker_only():
    def failing_debate(ticker, reports, client=None):
        raise RuntimeError("LLM transport exploded")

    components, calls = _components(
        ["AA", "BB"], failing_debate)
    result = asyncio.run(run_pipeline(["AA", "BB"], components))
    decisions = _decision_map(result)

    # both tickers produce decisions; every debate is the neutral sentinel
    assert set(decisions) == {"AA", "BB"}
    for decision in decisions.values():
        debate = decision["debate"]
        assert debate.winner == "undecided"
        assert all(
            "NO-DATA: debate unavailable" in c for c in debate.citations)
        # the citations gate did not trip on the sentinel
        veto = decision["veto"]
        assert veto["approved"] if isinstance(veto, dict) else veto.approved
        reasons = veto["veto_reasons"] if isinstance(veto, dict) else veto.veto_reasons
        assert reasons == []
    # the analyst/risk stages still ran for every ticker
    assert calls.count("risk:AA") == 1 and calls.count("risk:BB") == 1


def test_cheap_cycle_absent_debate_degrades_to_sentinel():
    def good_debate(ticker, reports, client=None):
        return DebateRecord.model_validate({
            "ticker": ticker, "bull_points": [], "bear_points": [],
            "winner": "bull", "citations": ["gross_margin=0.4"]})

    components, calls = _components(["AA"], good_debate)
    # Cheap cycle: analysts/debate must not run; a precomputed entry whose
    # debate key is missing entirely (older session stores / a restart)
    # must not crash evaluate_risk's attribute access.
    components["precomputed"] = {
        "AA": {"reports": {"fundamental": _report("AA")}}, }
    result = asyncio.run(run_pipeline(["AA"], components))
    decision = {d["ticker"]: d for d in result}["AA"]
    assert decision["debate"].winner == "undecided"
    assert decision["debate"].citations
    veto = decision["veto"]
    assert veto["approved"] if isinstance(veto, dict) else veto.approved
    # cheap cycle: no analyst/debate call for the ticker
    assert "analysts:AA" not in calls
    assert "risk:AA" in calls


def test_neutral_sentinel_shape_contract():
    from src.pipeline.graph import _neutral_debate
    sentinel = _neutral_debate("AA")
    assert sentinel.winner == "undecided"
    assert sentinel.citations and all(sentinel.citations)
    assert sentinel.bull_points and sentinel.bear_points
