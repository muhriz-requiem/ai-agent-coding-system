# Kronos signal experiment — provenance & prior-art record

Per workspace rules (AGENTS.md): prior-art sweep before building, borrowed
ideas recorded with license, vendor-copying flagged.  Nothing here is a
clone of another repo's full codebase; only the model implementation is
vendored, with the upstream header intact.
## Upstream model (vendored code)

- **Repo:** github.com/shiyu-coder/Kronos — Kronos: A Foundation Model for
  the Language of Financial Markets (AAAI 2026; arXiv:2508.02739).
- **License:** MIT (vendored copy at `kronos_model/LICENSE`; upstream
  master is the source of truth).
- **Files vendored:** `model/kronos.py` (30133 B), `model/module.py`
  (23426 B), `model/__init__.py` (412 B).  Single modification: upstream's
  ``sys.path.append("../")`` + ``from model.module import *`` replaced by a
  package-relative import (vendoring detail, no behavior change).
- **Weights:** Hugging Face `NeoQuasar/Kronos-small` (24.7M) by default;
  `NeoQuasar/Kronos-base` (102.3M) selectable via `--model`.
- **Upstream context note:** the authors state their finetune pipeline "is
  a demonstration ... not a production-ready quantitative trading system"
  and require cost/slippage modeling for honest backtests — our contract
  encodes exactly that.

## Prior-art sweep (README/pinned files only; nothing cloned)

1. **sumit-ai-ml/kronos-market-eval** (MIT) — walk-forward eval vs a
   random-walk baseline; "on this data, Kronos does not beat 'the price
   stays where it is'".  Borrowed: non-overlapping origins where the model
   sees only bars *strictly before* the forecast window; multi-path
   sampling (we use the built-in `sample_count` averaging instead of N
   separate predictor calls).
2. **nidheesh-kadem/kronos-trader** (US equities, Alpaca paper) — honest
   framing ("a money printer it is not"); borrowed the shape of wrapping
   Kronos over yfinance daily bars with a realistic US cost model.
3. **ktecho/llm_predict_markets** (Apache-2.0) — vendored-Kronos pattern
   with a backtest (MAE/RMSE/directional-accuracy) before any trading use;
   borrowed: judge forecast quality separately from edge measurement.
4. **konaaravind4/kronos-reproduction** — paper reproduction + simulator
   (context only; no code borrowed).
5. **Independent post-release evidence (negative):** jiripik validation
   writeup (2026-08-31) — zero-shot TSFMs produce negative out-of-sample
   R² on US equity returns; repo issues report AAPL daily directional
   accuracy 48.5–54.3% vs persistence; DEV community test (2026-11-03,
   500 US stocks x 53 weekly dates, strictly post-release) found no edge.

## Expectation before the run

Zero-shot Kronos likely shows no after-cost edge on US daily bars given
the above; the experiment's job is to *measure* it under this repo's
honest contract (ExecutionCosts + summarize_trades + baselines), not to
manufacture one.  A no-edge result is a finding, not a failure.

## Identity of this experiment

- Output: `data/kronos/forecasts_*.json` (generated predictions + observed
  bars) and `data/kronos/kronos_backtest_*.json` (scored trades).
- Determinism: one `torch.manual_seed` per run; sampling (multinomial) is
  stochastic by design — treat re-runs as new samples, not exact copies.
- Promotion gate: an edge only matters if, after 16 bps round-trip costs,
  `summarize_trades` shows `usable=True` with positive Kelly on n >= 30 —
  the same bar the quant overnight replay failed in 2026-09-14.  Only an
  explicit operator decision may then wire anything into sizing.

## 2026-11-08 outcome — thread closed (operator: "do whatever, only
implement if beneficial")

Hardware: local GTX 1650 Ti, chunked `predict_batch` (8 windows x
sample_count 2), 400-bar lookback, theta ladder on the predicted
next-open gap.

1. **Kronos-small, latest ~101 bars (2y), theta=0..400:** neutral
   directional skill 0.539 (n=1128); kelly `None` after 16 bps at every
   threshold; zero-cost kelly peaked at 0.126 (theta=200).
2. **Kronos-base, 6 disjoint ~100-bar windows over 5y** (A latest),
   pre-registered replication target = theta=200 BUY:

   | window | n | mean (bps) | win | with-costs kelly |
   |---|---|---|---|---|
   | A | 88 | +1.6 | 0.466 | 0.090  |
   | B | 90 | −23.5 | 0.433 | None |
   | C | 33 | +7.3 | 0.515 | 0.105 |
   | D | 91 | −39.8 | 0.473 | None |
   | E | 73 | −37.5 | 0.397 | None |
   | F | 44 | +36.7 | 0.614 | None |

   **Pooled: n=419, win 0.468, kelly `None`, Sharpe −0.93.**  Three
   windows positive, three negative; the two "survives costs" cells (A, C)
   were exactly the multiple-comparisons flukes the replication design
   was built to catch.

Conclusion: **no Kronos variant (small or base, zero-shot) passes the
promotion gate.**  Production sizing untouched — bit-identical to
pre-experiment.  Prior published replications (PROVENANCE prior-art
section) remain consistent with these numbers.
