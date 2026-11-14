"""Generate Kronos forecasts over project OHLCV history (research-only).

GPU phase of the Kronos signal experiment: expensive work happens exactly
once, predictions are cached to ``data/kronos/forecasts_<model>_<period>.json``
and scored offline by ``evaluate_forecasts.py`` under the standard
``backtest --mode overnight`` contract.

Non-lookahead contract (borrowed from sumit-ai-ml/kronos-market-eval,
MIT): at each origin bar ``t`` the model sees ONLY bars ``<= t`` —
window truncated to the last ``--lookback`` rows — and forecasts bar
``t+1`` of the same ticker (``y_timestamp`` = the ticker's actual next
trading date).  Every entry pair is non-overlapping overnight exposure:
enter at close[t], exit at open[t+1].

Usage::

    python -m experiments.kronos_signal.generate_forecasts          # full run
    python -m experiments.kronos_signal.generate_forecasts \
        --tickers AAPL,MSFT --origins-cap 30                       # smoke
    python -m experiments.kronos_signal.generate_forecasts --model base

Run with ``python -m`` from the project root (package-relative imports).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import time

import numpy as np
import pandas as pd

from src.data.market_data import fetch_ohlcv

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "SPY", "QQQ",
    "AMD", "COST", "AVGO", "ADBE", "CRM", "NFLX", "JPM", "WMT", "XLK",
    "XLF", "XLV", "XLE", "XLY", "XLI", "XLP", "XLU", "XLB", "XLC", "XLRE",
]

_MODEL_NAMES = {
    "small": "NeoQuasar/Kronos-small",
    "base": "NeoQuasar/Kronos-base",
}
_TOKENIZER_NAMES = {
    "small": "NeoQuasar/Kronos-Tokenizer-base",
    "base": "NeoQuasar/Kronos-Tokenizer-base",
}


def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Numeric, NaN-free OHLCV frame with capital-column names."""
    keep = {}
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in frame.columns:
            raise ValueError(f"missing column {col!r}")
        keep[col] = pd.to_numeric(frame[col], errors="coerce")
    cleaned = pd.DataFrame(keep, index=frame.index)
    cleaned = cleaned.replace([np.inf, -np.inf], np.nan).dropna()
    cleaned = cleaned[(cleaned["Close"] > 0) & (cleaned["Open"] > 0)]
    return cleaned


def _bars_payload(frame: pd.DataFrame) -> dict:
    dates = []
    for value in frame.index:
        dates.append(value.isoformat() if hasattr(value, "isoformat") else str(value))
    return {
        "dates": dates,
        "open": [float(v) for v in frame["Open"]],
        "high": [float(v) for v in frame["High"]],
        "low": [float(v) for v in frame["Low"]],
        "close": [float(v) for v in frame["Close"]],
        "volume": [float(v) for v in frame["Volume"]],
    }


def _as_timestamp_series(dates_json) -> pd.Series:
    return pd.Series(pd.to_datetime(list(dates_json)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Kronos forecast generation")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--period", default="2y")
    parser.add_argument("--lookback", type=int, default=400)
    parser.add_argument("--sample-count", type=int, default=2)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--model", default="small", choices=sorted(_MODEL_NAMES))
    parser.add_argument("--device", default="")  # empty = Kronos auto-detect
    parser.add_argument("--chunk", type=int, default=8,
                        help="windows per predict_batch call; effective "
                             "batch = chunk x sample_count (VRAM guard)")
    parser.add_argument("--origins-cap", type=int, default=0,
                        help="max forecasts per ticker (0 = all; smoke tests)")
    parser.add_argument("--origins-skip-newest", type=int, default=0,
                        help="drop the newest N eligible origins per ticker -- "
                             "replication windows disjoint from the latest run")
    parser.add_argument("--max-tickers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.max_tickers:
        tickers = tickers[: args.max_tickers]

    import torch

    # Reproducibility: one seed per run.  Sampling is multinomial by
    # design; a re-run is a new sample, not an exact copy (PROVENANCE.md).
    torch.manual_seed(args.seed)

    from experiments.kronos_signal.kronos_model.kronos import (
        Kronos,
        KronosPredictor,
        KronosTokenizer,
    )

    tokenizer = KronosTokenizer.from_pretrained(_TOKENIZER_NAMES[args.model])
    model = Kronos.from_pretrained(_MODEL_NAMES[args.model])
    kwargs = {"max_context": 512, "clip": 5}
    if args.device:
        kwargs["device"] = args.device
    predictor = KronosPredictor(model, tokenizer, **kwargs)

    print(f"model={args.model} lookback={args.lookback} "
          f"sample_count={args.sample_count} chunk={args.chunk} "
          f"device={predictor.device}", flush=True)

    job = {"meta": {}, "bars": {}, "forecasts": []}
    n_forecasts = 0
    t0 = time.monotonic()
    for ticker in tickers:
        try:
            frame = fetch_ohlcv(ticker, period=args.period)
        except Exception as exc:  # noqa: BLE001 - degrade per ticker
            print(f"{ticker}: fetch failed ({exc}); skipped", flush=True)
            continue
        try:
            frame = _clean_frame(frame)
        except ValueError as exc:
            print(f"{ticker}: {exc}; skipped", flush=True)
            continue
        job["bars"][ticker] = _bars_payload(frame)
        n_bars = len(frame)

        # Origins: every bar index t where the window [t-lookback+1, t] is
        # full and bar t+1 exists.  Outcome prices are strictly historical.
        lo = args.lookback - 1
        hi = n_bars - 2
        origins = list(range(lo, hi + 1))
        if args.origins_skip_newest:
            origins = origins[: len(origins) - args.origins_skip_newest]
        if args.origins_cap:
            origins = origins[-args.origins_cap:]
        if not origins:
            print(f"{ticker}: <{args.lookback + 2} bars; skipped", flush=True)
            continue

        done = 0
        t_ticker = time.monotonic()
        for start in range(0, len(origins), args.chunk):
            chunk_pairs = origins[start : start + args.chunk]
            windows = [frame.iloc[t - args.lookback + 1 : t + 1].rename(
                columns={"Open": "open", "High": "high", "Low": "low",
                         "Close": "close", "Volume": "volume"})
                for t in chunk_pairs]
            next_dates = [
                (frame.index[t + 1].isoformat()
                 if hasattr(frame.index[t + 1], "isoformat")
                 else str(frame.index[t + 1]))
                for t in chunk_pairs
            ]
            origin_dates = [
                (frame.index[t].isoformat()
                 if hasattr(frame.index[t], "isoformat")
                 else str(frame.index[t]))
                for t in chunk_pairs
            ]

            preds = predictor.predict_batch(
                df_list=windows,
                x_timestamp_list=[_as_timestamp_series(w.index) for w in windows],
                y_timestamp_list=[pd.Series(pd.to_datetime([d])) for d in next_dates],
                pred_len=1,
                T=args.temperature,
                top_p=args.top_p,
                sample_count=args.sample_count,
                verbose=False,
            )
            for t, origin_date, next_date, pred_df in zip(
                chunk_pairs, origin_dates, next_dates, preds
            ):
                job["forecasts"].append({
                    "ticker": ticker,
                    "origin_idx": int(t),
                    "origin_date": origin_date,
                    "origin_close": float(frame["Close"].iloc[t]),
                    "next_date": next_date,
                    "pred_open": float(pred_df["open"].iloc[0]),
                    "pred_high": float(pred_df["high"].iloc[0]),
                    "pred_low": float(pred_df["low"].iloc[0]),
                    "pred_close": float(pred_df["close"].iloc[0]),
                })
                n_forecasts += 1
            done += len(chunk_pairs)
        rate = done / max(1e-9, time.monotonic() - t_ticker)
        print(f"{ticker}: {done} origins @{rate:.1f}/s", flush=True)

    elapsed = time.monotonic() - t0
    job["meta"] = {
        "model": args.model,
        "hf_model": _MODEL_NAMES[args.model],
        "period": args.period,
        "lookback": args.lookback,
        "pred_len": 1,
        "sample_count": args.sample_count,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "seed": args.seed,
        "device": str(predictor.device),
        "tickers": tickers,
        "bars_tickers": sorted(job["bars"]),
        "n_forecasts": n_forecasts,
        "elapsed_seconds": round(elapsed, 1),
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }

    out = args.out or f"data/kronos/forecasts_{args.model}_{args.period}.json"
    out_path = __import__("pathlib").Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(job, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out_path} ({n_forecasts} forecasts in {elapsed:.0f}s, "
          f"{n_forecasts / elapsed:.1f}/s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
