"""Research-only experiment packages.

Nothing in ``experiments/`` feeds the production pipeline: no sizer, no
gate, no backtest tool reads from here.  Promotion to production (e.g.
a new Kelly stats source) requires an explicit review of the experiment's
JSON results, the way the README/concerns records every prior sizing
input.
"""
