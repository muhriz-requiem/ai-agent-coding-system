# Multi-Agent Coding System — v3, the research lane

Continuation of [ai-agent-coding-system](https://github.com/muhriz-requiem/ai-agent-coding-system), which is frozen as published. That tree is the record of a failure: three test projects run under a multi-agent orchestrator, **138 review records, 25 escalations, 13 approvals — all three passed their test suites, none of them worked.** Green tests over dead code, a spec-derived test deleted in the same operation that made it fail, and three modules defining three incompatible `JournalEntry` classes.

This repo is what I built because of that record. Same architecture family — 3-tier orchestrator, tests-first boards, free-provider routing, the redaction/egress layer — plus the four things the diagnosis said were missing:

1. **Evidence before design.** Planner and Builder prompts can now carry a bordered evidence block instead of a guessing mandate (`research.py`): local reverse-engineering evidence via REA, prior-art digests from GitHub with license capture. Both are config-gated, default OFF; with gates off the prompts are byte-identical to v2.9.
2. **A contract of record the Builder cannot touch.** Authored tests are written to disk *before* their tasks exist, frozen by `test_integrity.py`, and the spec critic resolves each task's authored test path explicitly — so the v1 failure class (a spec-derived test deleted when the suite was split, nothing replacing it) is now structurally unreachable rather than merely discouraged.
3. **Escalations arrive as a cause and a remedy**, not a stack trace — plus deterministic steering that measures burn (it flagged a task at 2,746s against an 1,800s threshold) and a terminal `gave_up` state instead of infinite retries.
4. **Nothing leaves the workspace without a manifest** (`export_gate.py`): fail-closed staging, fresh pytest re-measure at scan time, checksum verification. The gate refuses to promote anything to the v1 repository — it is on the built-in, config-immutable blacklist.

> ## Why this repository is published
>
> Same policy as v1: the evidence is committed, including the unflattering parts. Every phase of the v3 branch has a ledger entry — the two full escalation cycles it took to learn that content-mode builders are blind, the 1.1k-line log flood from a level-triggered warning, eight independent candidates blocked by the *same* pin before anyone audited the spec pair itself. Where a human had to do the work, the ledger says so.

## What did not survive v1, and what changed here

| v1 finding | v3 change |
| --- | --- |
| The spec-derived test that asserted the package re-exports its API was deleted when the suite was split; nothing replaced it; the remaining tests imported submodules directly, so nothing tested the package contract | `TaskSpec.authored_test_path` rides the board end-to-end and `spec_critic.py` resolves a task's test path of record; `test_integrity.py` freezes the entire pre-existing test tree (new tests must be *new files*), so the Builder can rewrite neither its grader nor its silence |
| Tests written against a spec's signatures passed whether or not the code behind them was correct | The spec surface moved from prose to pinned evidence: a case study is reverse-engineered first, its SPEC pins each requirement (R1–R6) to an Evidence ID, and the payoff build is graded against those pins |
| 0 escalations on the *most* incomplete project — silence was never suspicious | Deterministic steering (`steering.py`): doom loops, stalls, dependency deadlock, repeated failure shapes, resource burn — no LLM, counters and edge-triggered signals; an escalation now opens with `DIAGNOSIS: <bucket> <confidence>` |
| Two of six tasks were hand-completed, recorded in source docstrings only | The ledger is committed evidence; every handover to a human names what was done and why (same policy, more instrumentation: `steering_burn_rate` quantified the two blind cycles) |
| Nothing published its own output safely from the machine | `export_gate.py` — stage/approve/verify, fail-closed on every leg: fresh pytest re-measure at scan (unparseable or timeout = red), blacklist outranks allowlist, *empty* allowlist approves nothing, verify recomputes checksums, injection scan is deterministic and data-only |
| "A scoring function was mine, and it was not good enough" | The reviewer, not the gate, is the judge: `real_gate_passed` is an "applied and ran" log line, not a green verdict — named as a footgun in the ledger so nobody reads it as success |

## The proofs, and their costs

Three payoff builds ran on this branch (all machine-built via boards, graded by authored tests; numbers from their closeout records):

| Build | Result | The cost, stated |
| --- | --- | --- |
| `modinstall` | 6/6 chains done. Spec required sources: static RE of the installed CurseForge desktop app (13.4 MB asar; the `install` seed matched exactly one IPC channel node — the app is statically unpairable by design), SPEC R1–R6 each pinned to an Evidence ID | T-004 escalated `spec_wrong` at 0.98 (network-bound happy path), then failed 3+3 attempts before the real defect surfaced: content-mode builders receive neither test bodies nor current file contents on attempt 1 — only TASK_JSON. Two full escalation cycles (2,746s against a 1,800s threshold) bought that lesson. T-004's resolver and T-006's orchestrator were hand-written against re-pinned offline contracts at the human handover, and the ledger says so |
| `boardscan` | 3/3 chains done; board drained in 81.8s and `--once` self-terminated (no budget exhaustion) | Five `--once` runs, each unblocking the next layer. Two core fixes fell out of it — the authored test path carried end-to-end, and objective-named symbols in scope. After that, **eight independent candidates failed the *same single pin*** — the objective's literal rule ("replace \n and \r with spaces") yields two spaces on `"Line1\r\nLine2"` while the pin demanded one; the diagnosis layer called `spec_ambiguous → narrow_objective` at 1.0 confidence and was right. The models were never the problem; the objective-vs-pin pair was |
| `qreturns` | Returns-metrics milestone (03f6866): scaffold → machine plan → `--once` slices → diagnostician `fix_env` → gatekeeper contract hardening → 7 passed → portfolio 5/5 drained → export staged, awaiting operator approval | The smallest of the three — its value is that the *whole pipeline* (board, gate, registry, export staging) had become routine enough for a two-task build to traverse all of it |

Baseline at branch start: **pytest 566 passed** in 43.7s. At the notes-lane gate: **663 passed**, ruff clean. At this snapshot (2026-11-14): **730 core tests passing** plus the **678-test project suite**, ruff clean across the full `src/` tree. Each new module (research lane, export gate, portfolio registry, workspace MCP, notes lane, sight lane) carries its own pinned test file, and no existing test was edited — the frozen-tree rule applied to the core suite too.

## What I did vs. what the agents did

Same division as v1, stated the same way:

- **The developer wrote the system** — the research seams, the export gate, the portfolio registry, the read-only MCP server, the steering/diagnosis/notes layers, and every fix to the orchestrator's meta-problems (`once_boot_timeout` made edge-triggered after a 1.1k-line flood; the spec critic's plan-notes loop so blocking findings reach the author as repair context).
- **The agents built the payoff projects** under those gates — plans authored in ~13s, `--once` slices, escalations handled by the diagnosis layer where they could be.
- **The developer did the contract surgery** when a contract itself was wrong (resolver re-pins, boardscan objective v2→v4). That is the same act as v1's two hand-completed tasks — the difference is that now the burn is measured, the handover names its reasons, and the lesson is encoded back into the system (a machine task's contract must ride TASK_JSON; tests gate results but cannot steer attempt 1).

## The company lane

After the research lane proved itself, the roadmap turned to organizing multiple builds: **organization by annotation, not reproduction** — one orchestrator, sequential boards, divisions as domain prompt profiles, and a **portfolio registry** (`--portfolio`) that classifies every folder by what it *is* (subsidiary = board + goal both present; board without goal = other, with the fix stated; boardless = research). This directly killed a drift class: research-only directories made every orchestrator cycle emit recurring `task_board_unreadable` errors — now they are named children with a stated reason instead.

A **read-only workspace MCP server** (`workspace_mcp.py`, JSON-RPC 2.0 stdio, config-gated, default OFF) gives the operator's coding agent structured reads — company roster, project boards, steering state, export staging — without giving it a second write path: every mutation still has to pass the orchestrator lock and the export gate.

Design corroboration, cited where it was load-bearing: MAST (arXiv 2503.13657) puts spec + coordination at ≈74% of multi-agent failures, which is why single-board debugging stayed first-class; the manifest gate follows SLSA/in-toto practice rather than inventing one; the injection scan adapts OpenHands' deterministic no-LLM analyzer pattern.

## Since the October snapshot

Four lanes landed after the October curation, each with its own pinned tests:

1. **The sight lane — observing the artifact.** Every gate until now verified *the code's claims* (tests pass, suite grew); nothing ever looked at a rendered page — the v1 failure class, one plane up. The sight lane adds a third verification plane: view contracts (`expected_views/`) frozen like tests before a Builder exists, a DOM capture tier (stdlib, zero deps), an optional browser tier (Playwright/Chromium: a11y snapshot, screenshot, console errors — a blank screenshot refuses itself), and a bounded `WITNESS` model pass whose findings can veto an approval but never clear a mechanical one. Two-source rule enforced mechanically: a vision-derived claim stays `asserted` unless a non-vision source corroborates it on the same page. Feature-gated default OFF; when off, prompts are byte-identical.
2. **Trigger reliability.** A week of "no orders" turned out to be pure trigger lateness: GitHub Actions `schedule` events degraded platform-wide (delivered 2.5–7.5 h late since 2026-08-26), so every trade window was missed while the code was fine — the scheduled runs dying as `cancelled` were the designed timeout-kill, not a failure. The on-time trigger is now an external dispatcher (`workflow_dispatch`), with the late-schedule fallback made cheap: no-op runs exit in ~3 minutes behind a visible guard line. Same-run instant-exit and post-close resting-exit bugs were fixed and pinned by tests. (The setup runbooks are deliberately not part of this publication — operational detail.)
3. **Workspace MCP grew a gated write tier.** The read-only server (roster, boards, steering, export staging, cache stats) gained operator-grade steering tools — `pause`/`resume`/`note`/`retry_task`/`skip_task`, mirroring the dashboard's file control plane exactly — behind a second config gate, default OFF: the tools are absent from the tool catalog while off (least-privilege visibility), and writes touch only the file control plane a human already steers by hand. Enabling is an explicit `.env` choice, never a prompt-time one.
4. **A harness MCP policy.** After a researched survey, only two servers earned places in the operator's coding harness — a driver-enforced read-only SQLite server over the decision store and a remote docs-lookup server — with everything overlapping existing tools (GitHub CLI, yfinance, shell) explicitly skipped, versions pinned against rug-pulls, and the untrusted-data law extended to all MCP tool output (tool errors can arrive as normal payloads, not exceptions).

## Still true, and still not solved

Carried from v1's limitations, because they remain true:

1. **A new test's assertions are not checked for meaningfulness** — the tests-first gate proves the suite grew and nothing pre-existing was removed; it cannot tell a substantive test from `assert True`. That needs mutation testing, which this system does not have.
2. **Auditing independence is best-effort.** `REVIEWER_MODEL_EXCLUSION` keeps auditing roles off the Builder's model family when the free roster allows; an audit is still an LLM judging an LLM, and the deterministic Spec Critic tier — not a model — carries the load (corroboration for preferring a deterministic tier).
3. **The system writes the contract its own Builder is graded against**, and the Critic between author and frozen test is one model pass. A confident wrong Critic is possible; only `high` severity blocks, and the deterministic tier cannot be talked out of its findings.
4. **Escalation diagnosis is not independent evidence** — the diagnosing model usually participated in the work that failed.
5. **Board surgery is still manual when a contract is wrong** — and it has its own footguns, documented the hard way: operator surgery must rotate the `error_signature` token or the doom-loop threshold trips instantly, and "KEEPING the existing X unchanged" is unexecutable prose for a blind builder that emits complete files. The objective must embed the exact current source.

What changed on the human side: eight candidates failing the same pin now ends in an audit of the objective-vs-pin pair *before* anyone blames the models. That habit is the single largest improvement over v1, and it is a habit, not a module.

## Architecture

```
main.py                 Entry point and CLI (--once, --new-project, --preflight, --portfolio, --mcp-serve, --export)
super_orchestrator.py   Scheduling, steering, budget control
project_orchestrator.py Per-project loop: plan → build → review → gate → escalate
spec_author.py          Goal paragraph → tests-first task chains (authored tests frozen on disk)
spec_critic.py          Deterministic tier (ast-based) + one model pass; plan-notes become the author's repair context
agent_roles.py          Role definitions and prompt assembly (<<<TOOLS>>>, <<<PATTERNS>>>, <<<RESEARCH>>>)
model_router.py         Free-provider routing; RPM learned from each provider's own 429s
quota_governor.py       Quota caps and provider health
research.py             Evidence injection (REA, filtered) + prior-art digest (GitHub, license-aware) — gates default OFF
steering.py             Deterministic progress telemetry; edge-triggered signals
diagnosis.py            Escalated task → DIAGNOSIS bucket + remedy, not a stack trace
divergence.py           N-candidate generation with a merge gate
validation.py           Board-write allowlist — an escalated task cannot rewrite its own grading
executors.py            Deterministic tool execution; egress gate seam
patcher.py              Diff application with path denial (.env, keys) and scope guard
test_integrity.py       Frozen test tree; new tests are new files
redaction.py            Secret values blanked at every sink; pattern detection gates egress
export_gate.py          Manifest promotion: stage (fail-closed scan) → approve → verify
portfolio_registry.py   One read-side view over projects/: admission as a classification outcome
workspace_mcp.py        Read-only JSON-RPC server (roster, boards, steering, export staging, cache stats) + gated operator write tier
sight.py                Capture tier of the view gate: DOM/browser render of the artifact, self-checking, fail-closed
projects/
  curseforge-install-study/   Static RE case study: research/FINDINGS.md + SPEC.md (evidence-pinned R1–R6)
  modinstall/                 Payoff build 1: transactional mod installer (6/6)
  boardscan/                  Payoff build 2: task-boards CLI (3/3)
  qreturns/                   Payoff build 3: returns-metrics library (2/2)
  logtriage/ ledgerline/ slatepress/   The v1-era subjects, kept
  project_main/               The live paper-trading pipeline (also published as llm-equities-paper-trading; its on-time trigger and overnight-loop hardening are part of this branch's work)
  project_alpha/ project_beta/         Harness bootstrap fixtures, not projects
```

## Run it

```
pip install -r requirements.txt
cp .env.example .env          # DEMO_MODE auto-enables with no API key
python main.py --once         # bounded foreground pass; self-terminates when the board drains
python -m pytest tests -q     # core suite -- 730 passing on this snapshot
```

`AGENTS.md` carries the operating rules (and the story of the one PowerShell `Set-Content` accident that corrupted this workspace's `.env` — recovery took four attempts; the lessons about `.env` key-diffing survive in that file on purpose).

## The ledger

Every phase of this branch (opencode 2.0 harness upgrade, REA registration, harness capability mining, the research lane, the case study, three payoff builds, the company lane, the notes lane, the sight lane, the trigger-reliability lane) is documented with its costs. This repository is a curated snapshot: the day-to-day development history lives in the private workspace, and what's committed here is the system, the phase record, and the run evidence under `projects/*/.agent/` that the findings rest on.

For the record: this branch's `providers.VERSION` still reads **2.9.1** — the constant was never bumped during the overhaul, and the real version history is the development ledger, not the constant. The version-single-source test pins exactly the "constant appears in the README" property that once caught versions drifting apart as independent prose.

Also committed as evidence, per the same policy as v1: every project's `.agent/` run state — task boards (including the board-surgery backups), reviewer verdicts in `review_history.log`, rejected divergence candidates, cycle summaries. The boards are read by the core suite itself (`test_lines_partition`, `test_spec_critic` assert properties against the real completed builds rather than fixtures written to pass), so the evidence doubles as the regression data. (As of this snapshot, some October-era candidate artifacts were pruned from the live workspace; the run evidence follows the live tree's truth.)

`memory/instincts.md` is the harness's append-only session memory — distilled, dated lessons with their sources, read at the start of each session. It is excluded from this publication (it can carry machine-specific findings), but the format is part of the design: when a session ends, what it learned becomes the next session's first input.

## Secrets

Same discipline as v1: `.env` is gitignored and was never committed; `redaction.py` blanks live credential values at every sink (the JSONL log, prompts, caches, shared memory) and `scan_secrets` gates egress; `python main.py --preflight scan --committed` was re-run clean on this tree at the 2026-11-14 refresh (847 tracked files, zero credential-shaped content). Findings report only a `sha256(value)[:8]` hint, never the value. Every finding on this tree is a credential-*shaped* test fixture, named in `.secret-scan-allow` — the scan exists to catch the day one of them isn't.

## Licence

MIT.

