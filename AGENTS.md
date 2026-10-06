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

## Never rewrite a file with `Set-Content` and an array

PowerShell's `Set-Content -Value <string[]> -NoNewline` writes the array joined
by the **empty string**. Every newline is lost, so a 290-line file becomes one
line, and because dotenv treats everything after the first `#` as a comment the
file then sets **no variables at all**.

This happened to `.env` in this repo, which is gitignored — so git could not
restore it. Recovery took four attempts because the lost newlines destroyed real
information: a comment word fused onto a key (`# CRITICAL` + `LOG_LEVEL=INFO`
became `CRITICALLOG_LEVEL`) is not recoverable structurally, and a lookbehind
rejects valid matches when a comment ends in a letter. What worked was treating
`.env.example`'s key list as authoritative and matching known keys as **suffixes**
of the tokens in the mangled text.

Two near-misses the recovery caught, both of which would have been worse than
the corruption:

* `MODEL_OVERRIDES` was un-commented. It routes every builder role at
  `qwen/qwen3.8-27b:free` — the model that answers *"This model is unavailable
  for free"*. Every build would have failed at its first call.
* `SECRET_SCRUB_TARGETS` was being harvested as a live secret value, because its
  name matches `SECRET*`. Its value is a **path list**, and the same string is
  documented in `.env.example`, so `--preflight scan --committed` reported a
  leak in a tracked file. Redaction would also have blanked the list of files
  the operator is supposed to scrub.

**Rules that follow:**

* To edit a multi-line file, use the `edit` tool. Not `Set-Content`.
* If a rewrite is unavoidable, pipe (`Get-Content f | % {...} | Set-Content f`),
  which writes one line per item. Never `-Value $array -NoNewline`.
* After touching `.env`, verify: key count, every credential present and
  non-empty, `python -c "import config; print(config.X)"` for the settings you
  changed, and `python main.py --models verify` for a live call.
* Diff the key *set* before and after. Value comparison is not enough.

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
