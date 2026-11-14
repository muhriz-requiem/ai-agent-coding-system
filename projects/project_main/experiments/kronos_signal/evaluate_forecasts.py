"""Score cached Kronos forecasts under the overnight-replay contract.

Offline phase of the Kronos signal experiment: loads
``data/kronos/forecasts_<model>_<period>.json`` (from
``generate_forecasts.py``) and replays thresholded signals exactly like
``src/backtest/replay.py::replay_overnight`` — entry at ``Close[t]``,
exit at ``Open[t+1]``, ``ExecutionCosts`` (spread + slippage,
vol-scaled), ``summarize_trades`` stats — so the numbers are directly
comparable with the README's quant overnight replay (2026-09-14).

No GPU, no network: every outcome price comes from the observed bars the
generator cached alongside the forecasts.

Outputs ``data/kronos/kronos_backtest_<model>_<period>.json`` and a
printed summary table.

Usage::

    python -m experiments.kronos_signal.evaluate_forecasts
    python -m experiments.kronos_signal.evaluate_forecasts \
        --forecasts data/kronos/forecasts_smoke.json --costs-bps 0
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.costs import ExecutionCosts
from src.backtest.replay import summarize_trades

DEFAULT_THRESHOLDS_BPS = [0, 25, 50, 100, 200, 400]


def _vol20(closes: np.ndarray, t: int, window: int = 20) -> float:
    """Std of the last ``window`` close-to-close daily returns ending at t."""
    if t < window:
        return 0.0
    w = closes[t - window : t + 1]
    rets = w[1:] / w[:-1] - 1.0
    if len(rets) < 2:
        return 0.0
    return float(np.std(rets))


def load_payload(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def evaluate(payload: dict, thresholds_bps: list[float], costs: ExecutionCosts,
             zero_cost: ExecutionCosts) -> dict:
    bars: dict = payload["bars"]
    forecasts = payload["forecasts"]

    # Index bars by (ticker -> numpy arrays) once.
    frames: dict[str, pd.DataFrame] = {}
    for ticker, payload_bars in bars.items():
        stored = {k: list(v) for k, v in payload_bars.items()}
        # Reuse the market_data cache recipe: payload keyed "open"/"close"
        # with dates as ISO strings.
        records = {k: list(v) for k, v in stored.items()}
        dates = records["dates"]
        frame = pd.DataFrame({
            "Open": records["open"], "High": records["high"],
            "Low": records["low"], "Close": records["close"],
            "Volume": records["volume"],
        }, index=pd.to_datetime(pd.Series(dates)))
        frames[ticker] = frame

    trades = []  # one row per (threshold, cost_model, side, forecast)
    for entry in forecasts:
        ticker = entry["ticker"]
        frame = frames.get(ticker)
        if frame is None:
            continue
        t = int(entry["origin_idx"])
        closes = frame["Close"].to_numpy()
        opens = frame["Open"].to_numpy()
        if t < 0 or t >= len(closes) - 1:
            continue
        entry_px = float(closes[t])
        exit_px = float(opens[t + 1])
        if not math.isfinite(entry_px) or entry_px <= 0:
            continue
        if not math.isfinite(exit_px) or exit_px <= 0:
            continue
        vol = _vol20(closes, t)

        gap_pred = entry["pred_open"] / entry_px - 1.0
        # Direction: BUY when Kronos predicts a higher next open; SELL when
        # it predicts a lower one (short leg reported for completeness, as
        # in replay.run_backtest's per_side breakdown).
        for theta_bps in thresholds_bps:
            theta = theta_bps / 1e4
            if gap_pred > theta:
                side = "BUY"
            elif gap_pred < -theta:
                side = "SELL"
            else:
                continue
            for tag, cost_model in (("with_costs", costs), ("zero_cost", zero_cost)):
                if tag == "with_costs" and cost_model is None:
                    continue
                e = cost_model.adjust_entry(entry_px, side, vol)
                x = cost_model.adjust_exit(exit_px, side, vol)
                fwd = x / e - 1.0
                outcome = fwd if side == "BUY" else -fwd
                trades.append({
                    "threshold_bps": theta_bps,
                    "cost_model": tag,
                    "side": side,
                    "ticker": ticker,
                    "origin_date": entry["origin_date"],
                    "return": outcome,
                    # observation block (diagnostics, not part of the edge)
                    "realized_gap": exit_px / entry_px - 1.0,
                    "gap_pred": gap_pred,
                    "daily_vol": vol,
                })

    # Aggregate
    report: dict = {"thresholds": {}}
    all_df = pd.DataFrame(trades)
    for theta_bps in thresholds_bps:
        block = {}
        for tag in ("with_costs", "zero_cost"):
            for side in ("BUY", "SELL", "ALL"):
                sub = [
                    tr for tr in trades
                    if tr["threshold_bps"] == theta_bps
                    and tr["cost_model"] == tag
                    and (side == "ALL" or tr["side"] == side)
                ]
                block[f"{tag}_{side.lower()}"] = summarize_trades(
                    sub, min_trades=30, horizon=1)
        # Persistence / accuracy diagnostics on the BUY population
        buys = [tr for tr in trades
                if tr["threshold_bps"] == theta_bps and tr["side"] == "BUY"]
        if buys:
            hits = sum(
                1 for tr in buys
                if (tr["gap_pred"] > 0) == (tr["realized_gap"] > 0)
            )
            block["directional_accuracy"] = hits / len(buys)
        report["thresholds"][str(theta_bps)] = block

    # Baselines: always-in overnight gross (the "price stays where it is"
    # persistence family from the prior-art sweep) and the directionless
    # random-baseline contract.
    report["baseline"] = {
        "always_in_gross_mean_gap": (
            float(np.mean(all_df["realized_gap"])) if len(all_df) else None),
        "always_in_gross_median_gap": (
            float(np.median(all_df["realized_gap"])) if len(all_df) else None),
        "n_observations": int(len(all_df)),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Kronos forecasts")
    parser.add_argument("--forecasts", default="data/kronos/forecasts_small_2y.json")
    parser.add_argument("--thresholds-bps", default="")
    parser.add_argument("--spread-bps", type=float, default=10.0)
    parser.add_argument("--slippage-bps", type=float, default=3.0)
    parser.add_argument("--cost-scale-by-vol", type=int, default=1)
    parser.add_argument("--no-costs", action="store_true",
                        help="report zero-cost blocks only")
    parser.add_argument("--min-trades", type=int, default=30,
                        help="documented gate (used by recording notes only)")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    thresholds = (
        [float(x) for x in args.thresholds_bps.split(",") if x.strip()]
        if args.thresholds_bps else list(DEFAULT_THRESHOLDS_BPS)
    )
    costs = None
    if not args.no_costs:
        costs = ExecutionCosts(
            spread_bps=max(0.0, args.spread_bps),
            slippage_bps=max(0.0, args.slippage_bps),
            scale_by_vol=bool(args.cost_scale_by_vol),
        )
    zero = ExecutionCosts(spread_bps=0.0, slippage_bps=0.0, scale_by_vol=False)

    payload = load_payload(args.forecasts)
    report = evaluate(payload, thresholds, costs, zero)

    meta = dict(payload.get("meta", {}))
    meta.update({
        "costs": (None if costs is None else {
            "spread_bps": args.spread_bps, "slippage_bps": args.slippage_bps,
            "scale_by_vol": bool(args.cost_scale_by_vol)}),
        "thresholds_bps": thresholds,
        "evaluated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })
    payload_out = {"meta": meta, "report": report}

    stem = Path(args.forecasts).stem.replace("forecasts", "kronos_backtest")
    out = args.out or f"data/kronos/{stem}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload_out, indent=1), encoding="utf-8")
    print(f"wrote {out}")

    # Console summary
    print(f"\n=== Kronos signal vs the {meta.get('hf_model', '?')} overnight contract ===")
    print(f"observations: {report['baseline'].get('n_observations')}  "
          f"always-in gross mean gap: "
          f"{(report['baseline'].get('always_in_gross_mean_gap') or 0):+.5f}")
    print(f"{'theta':>8} {'side':>5} | {'n':>6} {'win':>6} {'kelly':>7} "
          f"{'sharpe':>7} | {'n0':>6} {'win0':>6} {'kelly0':>7} {'sharpe0':>7}"
          "   [0 = zero cost]")
    for theta in thresholds:
        block = report["thresholds"].get(str(theta), {})
        for side in ("BUY", "SELL", "ALL"):
            wc = block.get(f"with_costs_{side.lower()}", {})
            zc = block.get(f"zero_cost_{side.lower()}", {})

            def fmt(d):
                if not isinstance(d, dict):
                    return " " * 30
                k = d.get("kelly_fraction")
                s = d.get("sharpe")
                return (f"{d.get('n_trades', 0):>6} {d.get('win_rate', 0):>6.3f} "
                        f"{'None' if k is None else f'{k:7.4f}'} "
                        f"{'None' if s is None else f'{s:7.3f}'}")
            print(f"{theta:>8} {side:>5} | {fmt(wc)} | {fmt(zc)}")

    bias = report["thresholds"].get(str(thresholds[0]), {})
    da = bias.get("directional_accuracy")
    if da is not None:
        print(f"\ndirectional accuracy of pred_open-gap sign (theta=0 BUYs): {da:.3f}")
    print("\npromotion gate: usable=True with positive kelly AFTER costs "
          "(n>=30) -- same bar the quant overnight replay failed 2026-09-14.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
