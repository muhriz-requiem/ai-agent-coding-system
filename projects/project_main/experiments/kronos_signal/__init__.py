"""Kronos foundation-model signal experiment (research-only).

Question: does a zero-shot Kronos (K-line foundation model, MIT license)
forecast beat the repository's barriers — the 16 bps round-trip cost
model and the random-baseline contract — on the same 2y/28-name
overnight replay the README documents as the primary edge candidate?

Pipeline:
    ``generate_forecasts.py``  fetches OHLCV (project ``fetch_ohlcv``),
    runs Kronos at strictly non-lookahead origins, and caches predicted
    next-bar open/close per (ticker, origin) into ``data/kronos/``.

    ``evaluate_forecasts.py``  replays thresholded signals from the
    cached forecasts under the SAME contract as ``backtest --mode
    overnight`` (entry close[t], exit open[t+1], ExecutionCosts,
    summarize_trades) — expensive GPU work happens exactly once.
"""
