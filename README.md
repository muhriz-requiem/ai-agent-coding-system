# Enterprise Multi-Agent Coding System

A 3-tier hierarchical multi-agent coding orchestrator (Python 3.10+, Pydantic v2)
targeting the OpenRouter API. Runs end-to-end offline in DEMO_MODE. Includes a Kaggle
domain pack, a secrets-and-egress layer, and a circuit breaker.

> ## Why this repository is published
>
> I built this system to test whether a team of LLM agents could write working software.
> **They could not — and the interesting part is why, in a way I did not expect going in.**
>
> Across three test projects the agents produced **138 review records, 25 escalations,
> and only 13 approvals**. The projects that scored 100% green on `pytest` were, in
> places, non-functional. See "The finding" below for the specific failures.
>
> This is a record of that failure, with the raw evidence committed.

---

## The finding: a green test suite is not a working program

The system was run on three projects. **All three passed their tests. None of them
worked.**

| Project | Tests | Escalations | What was actually broken |
|---|---|---|---|
| `slatepress` | 21/21 pass | 0 | The spec required a package `__init__.py` re-exporting `blocks()` (headings, fenced code, lists) among others. **It was never written** — and the spec-derived test that asserted it was deleted when the suite was split. `markdown.py` ships with only `inline_markup`. The task board has no task for it. |
| `ledgerline` | 26/26 pass | 13 | Three modules define **three mutually incompatible `JournalEntry` classes**. `trial_balance.py` reads attributes the real objects don't have. `reports.py` reads an attribute nothing sets, so it returns all zeros. |
| `logtriage` | 105/105 pass | 12 | Two tasks were **hand-completed by me**, not the Builder. The reasoning is in the source docstrings. |

`slatepress` is the sharpest case, and the fix that was applied makes it worse, not
better. Its original spec-derived test — 8 assertions that the package re-exports its
public API, including `blocks` — **could never have passed**, because the `__init__.py`
was never written. When the suite was reorganised into per-module tests, that file was
deleted. Nothing replaced it. The remaining five test files import submodules directly
(`from src.slatepress.frontmatter import ...`), so they never touch the package
contract. Green suite, missing requirement, and the test that would have caught it
deleted in the same operation.

The failure mode is consistent: **the agents satisfy the API surface without satisfying
the behaviour.** Tests written against a spec's signatures pass whether or not the code
behind them is correct.

This is not hypothetical for me. It is the same class of error as an AI generating a
plausible-but-wrong proof of a famous open problem: a scoring function reports success,
and a reader who trusts the score is wrong. The difference is that here the scoring
function was *mine*, and it was not good enough.

The raw evidence — every reviewer verdict, every escalation, every rejected candidate —
is in `projects/*/.agent/review_history.log` and is committed to this repository.

---

## Architecture

```
Spec Author ──▶ task board ──▶ Builder ──▶ Reviewer ──▶ gate ──▶ done / escalate
      │              │             │           │          │
  goal.txt      .agent/       applies     verdicts   pytest +
                                     diffs              objective
                                                         │
                            Spec Critic ──▶ validates the spec BEFORE building
```

**Key modules:**

| Module | Role |
|---|---|
| `main.py` | Entry point and CLI (`--once`, `--new-project`, `--preflight`) |
| `super_orchestrator.py` / `project_orchestrator.py` | Scheduling, steering, budget control |
| `spec_author.py` / `spec_critic.py` | The system writes its own tests-first spec; the critic rejects specs with unresolvable imports |
| `agent_roles.py` | Role definitions; `AUDITING_ROLES` decides which models review Builder output |
| `model_router.py` / `quota_governor.py` | Free-provider routing with learned RPM limits and quota caps |
| `redaction.py` | Blanks live credential values at every sink; blocks untrusted output from naming its own write targets |
| `validation.py` | Board-write allowlist — an escalated task cannot rewrite its own grading |
| `diagnosis.py` / `divergence.py` | Classifies escalations; optional N-candidate generation with a merge gate |
| `logtriage` (project) | The system building a diagnostic tool that reads **its own event log** |

---

## What I did vs. what the agents did

This system was built with AI coding agents, deliberately.

- **The developer wrote the system** — the orchestrator, the spec critic, the circuit
  breaker, the redaction layer, the routing and quota logic.
- **The agents wrote the three test projects** under its supervision. That was the point
  of building it.
- **The developer read every escalation and wrote the post-mortems.** Where the agents
  failed in an interesting way, the analysis is in the project's own source docstrings —
  see `projects/logtriage/src/triage/failures.py`, which explains in the first person why
  a reviewer flip-flopped on an ambiguous contract and how I resolved it.

The three projects exist as **test subjects for this orchestrator**, not as portfolio
pieces. `slatepress` and `ledgerline` were thin one-paragraph specs; `logtriage` had an
87-line architecture document. The thin specs produced the most incomplete output.

---

## Test projects

| Project | Spec | Tasks | Result |
|---|---|---|---|
| `ledgerline` | 1-line `goal.txt` | 7 | 26 tests pass; 13 escalations, ~60 of 69 review records on a single task |
| `slatepress` | 1-line `goal.txt` | 5 (one missing) | 21 tests pass; **0 escalations** — and the most incomplete output |
| `logtriage` | 87-line `context.md` | 6 | 105 tests pass; 12 escalations; 2 tasks hand-completed |
| `project_main` | Full reference implementation | 20 | 666 tests pass — published separately as `llm-equities-paper-trading` |
| `project_alpha` / `project_beta` | none | — | Harness bootstrap fixtures written by `config.py`. Not projects. |

---

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env          # runs in DEMO_MODE with no API key
python main.py --once         # bounded foreground run
python -m pytest tests -q     # core suite
```

See `AGENTS.md` for operating notes — including two hard-won lessons about PowerShell
and `.env` files that cost real recovery time.

## Configuration

`.env.example` is heavily commented and documents every subsystem. Notable defaults:
`DEMO_MODE` auto-enables with no API key; `FREE_MODEL_ROUTING` uses free providers;
`REVIEWER_MODEL_EXCLUSION` keeps reviewers off the Builder's model family (a reviewer
sharing the Builder's weights is an echo, not a check).

## Secrets

`.env` is gitignored and was never committed. `redaction.py` blanks live credential
values at every sink, and `--preflight scan --committed` checks for leaks before a push.
`.secret-scan-allow` lists the only files permitted to contain credential-*shaped*
strings — all test fixtures.

## Licence

MIT.
