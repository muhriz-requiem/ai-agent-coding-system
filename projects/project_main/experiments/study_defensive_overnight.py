"""Defensive-sleeve overnight study (research-only; informs the panic
exception decision — see experiments/kronos_signal/PROVENANCE.md pattern).

Questions, all under the SAME contract as `backtest --mode overnight`
(entry close[t], exit open[t+1], ExecutionCosts 10/3 bps vol-scaled):

  1. SIGNAL-CONDITIONED overnight trades for SH, PSQ, GLD, TLT over 5y
     (generate_signal per bar, exactly like the live overnight cycle),
     pooled, split by a panic proxy on the ENTRY date:
     VIX >= VIX_PANIC_LEVEL (25) AND VIX/VIX3M >= 1.0 (backwardation)
     -- the regime.py panic definition reconstructed from yfinance.
  2. SPY/QQQ overnight returns on panic vs non-panic days (always-in),
     i.e. does the long-side halo drift invert in stress?
  3. The full 51-name production universe, signal-conditioned overnight
     aggregate WITH costs (does the 2026-11-10 expansion change the
     aggregate edge?), scored with src.backtest.replay.replay_overnight.

NOTE (concerns.txt item 13 caveat): the fear/breadth regime gates are
fail-open in replays (historical snapshots not reconstructable) -- the
signal population here is slightly larger than live, as with every repo
replay.  Writes NOTHING to production stats files.
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\workspace\projects\project_main")

import src.config  # noqa: F401  (loads .env for gate thresholds)
from src.backtest.costs import ExecutionCosts
from src.backtest.replay import replay_overnight, summarize_trades
from src.data.market_data import fetch_ohlcv
from src.quant.signals import generate_signal

DEFENSIVE = ["SH", "PSQ", "GLD", "TLT"]
MARKET = ["SPY", "QQQ"]
UNIVERSE_51 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ",
    "AMD", "COST", "AVGO", "ADBE", "CRM", "NFLX", "JPM", "WMT", "XLK",
    "XLF", "XLV", "XLE", "XLY", "XLI", "XLP", "XLU", "XLB", "XLC", "XLRE",
    "BAC", "WFC", "GS", "V", "MA", "UNH", "JNJ", "LLY", "MRK", "ABBV",
    "KO", "PG", "HD", "MCD", "NKE", "XOM", "CVX", "CAT", "HON", "UPS",
    "DIS", "T", "VZ",
]
PERIOD_DEF = "5y"
PERIOD_UNI = "2y"
COSTS = ExecutionCosts(spread_bps=10.0, slippage_bps=3.0, scale_by_vol=True)
ZERO = ExecutionCosts(0.0, 0.0, False)
VIX_PANIC_LEVEL = float(__import__("os").environ.get("VIX_PANIC_LEVEL", "25"))
VIX_BACKWARDATION = float(__import__("os").environ.get("VIX_BACKWARDATION", "1.0"))


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    keep = {}
    for col in ("Open", "High", "Low", "Close", "Volume"):
        keep[col] = pd.to_numeric(frame[col], errors="coerce")
    out = pd.DataFrame(keep, index=frame.index)
    return out.replace([np.inf, -np.inf], np.nan).dropna()


def _vol20(closes: np.ndarray, t: int, window: int = 20) -> float:
    if t < window:
        return 0.0
    w = closes[t - window : t + 1]
    rets = w[1:] / w[:-1] - 1.0
    return float(np.std(rets)) if len(rets) >= 2 else 0.0


def signal_trades(frame: pd.DataFrame) -> list[dict]:
    """Overnight trades where generate_signal fires BUY (live contract)."""
    closes = frame["Close"].to_numpy()
    opens = frame["Open"].to_numpy()
    trades = []
    for t in range(24, len(closes) - 1):
        sig = generate_signal(frame.iloc[: t + 1])
        if str(sig.get("signal", "")).upper() != "BUY":
            continue
        entry = float(closes[t])
        exitp = float(opens[t + 1])
        if not math.isfinite(entry) or entry <= 0 or not math.isfinite(exitp) or exitp <= 0:
            continue
        vol = _vol20(closes, t)
        e_adj = COSTS.adjust_entry(entry, "BUY", vol)
        x_adj = COSTS.adjust_exit(exitp, "BUY", vol)
        trades.append({
            "date": str(frame.index[t])[:10],
            "return_gross": exitp / entry - 1.0,
            "return_net": x_adj / e_adj - 1.0,
            "daily_vol": vol,
        })
    return trades


def always_in_overnight(frame: pd.DataFrame) -> list[dict]:
    """Every overnight close->open observation (drift measurement)."""
    closes = frame["Close"].to_numpy()
    opens = frame["Open"].to_numpy()
    return [{
        "date": str(frame.index[t])[:10],
        "return_gross": float(opens[t + 1] / closes[t] - 1.0),
    } for t in range(len(closes) - 1)]


def main() -> int:
    print("fetching VIX / VIX3M for the panic proxy...")
    vix = _clean(fetch_ohlcv("^VIX", period=PERIOD_DEF))["Close"]
    vix3m = _clean(fetch_ohlcv("^VIX3M", period=PERIOD_DEF))["Close"]
    vv = pd.concat([vix.rename("vix"), vix3m.rename("vix3m")], axis=1).dropna()
    panic_dates = {
        str(d)[:10] for d, (v, r) in vv.iterrows()
        if v >= VIX_PANIC_LEVEL and (v / r) >= VIX_BACKWARDATION
    }
    print(f"panic proxy days (5y): {len(panic_dates)} "
          f"({len(panic_dates)/len(vv):.1%} of sessions)")

    out: dict = {
        "vix_panic_level": VIX_PANIC_LEVEL,
        "vix_backwardation": VIX_BACKWARDATION,
        "n_panic_days": len(panic_dates),
        "defensive": {},
        "market_panic": {},
        "universe51_aggregate": None,
    }

    # -- Part 1: signal-conditioned defensive sleeve -----------------------
    pooled: list[dict] = []
    for ticker in DEFENSIVE:
        frame = _clean(fetch_ohlcv(ticker, period=PERIOD_DEF))
        trades = signal_trades(frame)
        for tr in trades:
            tr["panic"] = tr["date"] in panic_dates
        pooled.extend(trades)
        by = {
            "all": [t["return_net"] for t in trades],
            "panic": [t["return_net"] for t in trades if t["panic"]],
            "non_panic": [t["return_net"] for t in trades if not t["panic"]],
        }
        stats = {k: summarize_trades([{"return": v} for v in vs], 30, 1)
                 for k, vs in by.items()}
        out["defensive"][ticker] = {
            "n": {k: len(v) for k, v in by.items()},
            "stats": stats,
        }
        line = " | ".join(
            f"{k}: n={len(by[k])} mean={np.mean(by[k])*1e4 if by[k] else 0:+.1f}bps"
            for k in ("all", "panic", "non_panic"))
        print(f"{ticker:>5} {line}")

    pooled_by = {
        "all": [t["return_net"] for t in pooled],
        "panic": [t["return_net"] for t in pooled if t["panic"]],
        "non_panic": [t["return_net"] for t in pooled if not t["panic"]],
    }
    out["defensive_pooled"] = {
        "n": {k: len(v) for k, v in pooled_by.items()},
        "stats": {k: summarize_trades([{"return": v} for v in vs], 30, 1)
                  for k, vs in pooled_by.items()},
    }
    line = " | ".join(
        f"{k}: n={len(pooled_by[k])} mean={np.mean(pooled_by[k])*1e4 if pooled_by[k] else 0:+.1f}bps "
        f"win={sum(1 for x in pooled_by[k] if x>0)/len(pooled_by[k]) if pooled_by[k] else 0:.3f}"
        for k in ("all", "panic", "non_panic"))
    print(f"POOL {line}")

    # -- Part 2: long-side drift on panic vs non-panic days ----------------
    for ticker in MARKET:
        frame = _clean(fetch_ohlcv(ticker, period=PERIOD_DEF))
        obs = always_in_overnight(frame)
        panic_rets = [o["return_gross"] for o in obs if o["date"] in panic_dates]
        norm_rets = [o["return_gross"] for o in obs if o["date"] not in panic_dates]
        out["market_panic"][ticker] = {
            "panic_n": len(panic_rets), "panic_mean_bps": float(np.mean(panic_rets)) * 1e4 if panic_rets else None,
            "panic_median_bps": float(np.median(panic_rets)) * 1e4 if panic_rets else None,
            "nonpanic_n": len(norm_rets), "nonpanic_mean_bps": float(np.mean(norm_rets)) * 1e4,
        }
        print(f"{ticker:>5} overnight drift | panic: n={len(panic_rets)} "
              f"mean={np.mean(panic_rets)*1e4:+.1f}bps median={np.median(panic_rets)*1e4:+.1f}bps"
              f" | non-panic mean={np.mean(norm_rets)*1e4:+.1f}bps")

    # -- Part 3: 51-name universe aggregate (signal-conditioned, costs) ----
    all_trades: list[dict] = []
    for ticker in UNIVERSE_51:
        try:
            frame = fetch_ohlcv(ticker, period=PERIOD_UNI)
        except Exception:
            continue
        all_trades.extend(replay_overnight(frame, costs=COSTS))
    out["universe51_aggregate"] = summarize_trades(all_trades, 30, 1)
    s = out["universe51_aggregate"]
    print(f"UNIVERSE-51 overnight aggregate (net): n={s['n_trades']} "
          f"win={s.get('win_rate')} kelly={s.get('kelly_fraction')} "
          f"sharpe={s.get('sharpe')}")

    with open(r"D:\workspace\projects\project_main\data\defensive_sleeve_study.json",
              "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("wrote data/defensive_sleeve_study.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
