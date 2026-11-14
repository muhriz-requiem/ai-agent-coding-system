---
name: night-shift
description: Run and supervise orchestrator builds in the background with bounded token cost. Use when the operator wants long builds to run while away, when resuming after an overnight run, or whenever a blocking orchestrator process must not hold the turn.
---

Overnight/long-run pattern for orchestrator work in D:\workspace. The goal:
progress keeps happening while the session stays responsive, and every
check-in costs hundreds of tokens, not thousands.

## Launch (never a foreground blocker)

1. Housekeeping first: kill leftover `python` from prior sessions
   (`Get-Process -Name python | Select Id,StartTime,CPU`), confirm no
   orchestrator holds the workspace (`main.py` enforces an OS lock; a second
   start exits 2; the lock file `.system/orchestrator.lock` is OS-owned, so
   a stale file does not block — only delete it after confirming the holder
   is dead).
2. If the board is large, raise `ONCE_BUDGET_S` in `.env` first (edit tool,
   never `Set-Content` with an array; verify with
   `python -c "import config; print(config.ONCE_BUDGET_S)"`).
3. Launch in the background: `python main.py --once` with
   `background: true`. Report immediately that it is running — never wait
   synchronously, never end a turn holding a foreground blocker
   (AGENTS.md auto-backgrounding policy).

## Check-in cadence (bounded reads only)

- `workspace` MCP `log_tail` (default 40 lines, clipped) — one call, few
  hundred tokens.
- `.system/manifest.json` for per-project `status`/`loop_state`/`board`
  counts; `.system/steering_state.json` for doom-loop counters.
- Escalate to the operator only on: `steering_doom_loop` lines (the loop
  has *stopped* retrying and escalated), breaker trips, crash-restart
  streaks (5), or `LLMUnavailableError` deferrals.
- An escalated task's `last_feedback` opens with a `DIAGNOSIS:` line —
  read that line first; the bucket matters more than the stack trace.
- A frozen log tail is not proof of a stall: count events over the window
  instead.

## Morning summary

When the run drains (`--once` self-terminates when the board drains):
report board counts (done/failed/pending/blocked), every escalation's
DIAGNOSIS bucket, token/cache stats from the manifest, and append any
durable lesson to `memory/instincts.md` (via the harness-memory skill).
Verify no process is left running before ending.

## Hard rules

- One orchestrator per workspace, ever. Two loops race the boards and
  snapshots; the losing rollback resurrects the winner's files.
- Never stream full logs into context — the feed TUI
  (`python main.py --feed`) exists for humans; agents read tails.
- Data caches and `.env` are operator territory: edit `.env` only with the
  edit tool and re-verify imports after.
