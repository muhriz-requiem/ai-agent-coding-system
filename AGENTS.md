# AGENTS.md — how to operate this repo without leaving a session idle

## Never end a turn with a process still running

This is the single most important rule here, and it is about *my* behaviour
rather than the code.

`Start-Process -PassThru` returns in milliseconds. If a tool call launches work
and then the turn ends, the session looks hung to the operator and has to be
manually interrupted — even though nothing is actually stuck. A tool call that
*starts* work must never be the last thing that happens in a turn.

Concretely, in order of preference:

1. **Prefer a bounded foreground run.** This repo's orchestrator has a budget
   knob for exactly this. Run it synchronously and give the tool call a large
   `timeout` so it is *supposed* to take minutes:

   ```powershell
   python main.py --once          # self-terminates when the board drains
   ```

   Raise `ONCE_BUDGET_S` in `.env` for long builds. The operator sees a live
   spinner and streamed output, and gets a real completion signal.

2. **When work genuinely is unbounded, block in the same call.** Use the helper
   below rather than a bare `Start-Process`. It keeps the call alive, prints
   progress, and tells you plainly if its own cap expires with the child still
   running — so a process is never silently orphaned.

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
     "& 'literal:<path-to>\run-and-wait.ps1' -Name <label> -FilePath python `
        -ArgList @('main.py','--once') -WorkDir 'literal:<repo-root>' `
        -MaxMinutes 8 -PollSeconds 25"
   ```

   Note the `-Command` wrapper. Invoking the script with `-File` flattens array
   parameters, and `main.py,--once` is then passed as one filename.

3. **Cap each wait below the operator's patience** (~8 minutes) and immediately
   issue the next wait. Long silence reads as a hang even when it is not.

## Housekeeping that prevents confusing "stuck" with "idle"

- Only **one** orchestrator may hold a workspace (`main.py` enforces an
  OS-level lock; a second start exits 2). Before restarting a build, stop the
  previous process and delete `.system/orchestrator.lock` if it was left behind.
- The lock file being *present* is not the same as being *held* — it is
  OS-owned, so a stale file does not block a new start.
- Kill leftover `python` processes from previous sessions before starting a new
  build. Check with `Get-Process -Name python | Select Id,StartTime,CPU`.
- A frozen log tail does not mean a stalled build. Count events over the window
  instead: 600+ events with slowly climbing CPU means it is working, just not
  logging on the line you tailed.

## Verification commands

```powershell
python -m pytest tests -q                    # core suite
python -m ruff check --select E9,F *.py       # production lint
python main.py --preflight scan              # exit 1 = findings (expected here)
python -m pytest tests -q                    # run from projects/<name>/ for project tests
```

## Working on this system

- `python main.py --new-project NAME --goal "..." --author-plan` first, then
  read the plan before letting it build. Machine-authored specs are a first
  draft, not a contract you trust.
- An escalated task's `last_feedback` opens with a `DIAGNOSIS:` line. Read that
  first — the bucket matters more than the stack trace under it.
- A `steering_doom_loop` line means the loop has *stopped* retrying and
  escalated. It is an intervention, not just a warning.
