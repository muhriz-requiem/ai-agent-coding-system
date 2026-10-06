# Enterprise Multi-Agent Coding System v2.9.1

A 3-tier hierarchical multi-agent coding orchestrator (Python 3.10+, Pydantic v2)
targeting the **OpenRouter API** (with an optional **OpenCode CLI** adapter).
Runs **end-to-end offline** in DEMO_MODE: all LLM calls are stubbed behind one
integration seam with clearly marked TODOs for the real calls.

v2.7 added a **secrets-and-egress layer** (`redaction.py`): live credential
values are blanked at every sink, credential-shaped content is blocked from
leaving the machine, and untrusted model output can no longer name its own
write targets. See "Secrets and egress" below.

**v2.8 closes the holes that layer left.** The system could verify its own
output but nothing stopped the Builder from editing the tests that graded it,
a transient board read could erase the entire backlog, and the "learning"
subsystem did not learn. Three new pieces:

- **`test_integrity.py`** — the pre-existing test tree is a frozen baseline.
  A diff may not modify or delete a test, `conftest.py` or pytest config
  (`allow_test_edits` opts out per task); new test files stay writable, so
  tests-first is intact.
- **`steering.py`** — deterministic progress telemetry: doom loops, stalls,
  dependency deadlock, repeated failure shapes, resource burn. No LLM.
- ~~`council.py`~~ — deleted in v2.9; its one useful reflex survives as the
  deterministic circuit breaker (`SuperOrchestrator._check_breaker`), which
  pauses a project that spent quota without completing anything. Counters, no
  inference. Its board-write whitelist is kept, in
  `validation.BOARD_WRITE_ALLOWLIST`, because escalation diagnosis now needs the
  same boundary.

**v2.9 — the system authors its own specification.** The reference build put
**all 12 task escalations at the human handover boundary and none at an
engineering defect**. So the writing moved before the gates:

- **`spec_critic.py`** — verifies an objective against the tests that will grade
  it *before* any Builder attempt. A free deterministic tier (`ast`-based, no
  model call) plus one model pass with the full spec and full test source.
- **`spec_author.py`** — `--new-project NAME --goal "..."` turns one paragraph
  into tests-first task chains. Authored tests are written to disk *before* the
  tasks exist, so `TestIntegrityGuard` freezes them and the Builder is refused
  any edit to the contract it is graded against.
- **`diagnosis.py`** — an escalated task now arrives as a cause and a remedy
  rather than a stack trace, with the reason string fed to the steering
  clusterer so repeated failures surface as one systemic block.
- **`lines.py`** — the board is graph-coloured into conflict-free lines.
  Deterministic, free, validated before publication.
- Model routing now **measures instead of trusting typed-in numbers**: capability
  weighted below observed success, probes ordered least-observed-first (13
  previously unreachable models), live `/models` discovery for five providers,
  and each provider's RPM **learned from its own 429s**.

Three pre-existing defects were found and fixed on the way: the core suite could
not run as a whole (`conftest` name collision), `logtriage` silently verified
nothing when pytest ran from the wrong directory, and the Builder's conversation
leaked across task boundaries. Details and measurements below.

Plus: the Reviewer is routed off the Builder's model, LLM calls have a hard
wall-clock ceiling, real token usage is recorded, and the tests-first gate
compares test node IDs instead of a single integer.

**v2.8.1 — dogfooding.** The harness was then pointed at a real project
(`projects/logtriage`: a log-analysis library it built to diagnose itself,
6 tasks, 105 tests). That found six more defects, five of them in code this
release had just added. See "Dogfooding findings" below.

## Dogfooding findings (v2.8.1, extended in v2.9)

Running the system on real work was far more productive than reading it. Each
item below was found by the run, not by inspection.

### In the harness

| Defect | Symptom observed | Fix |
|---|---|---|
| **"Hard" call ceiling was not hard** | The first implementation used `wait_for(asyncio.shield(req))`. `wait_for` awaits cancellation of what it is handed, and a shield future does not complete until the inner task does — so a provider that ignored cancellation hung forever. The regression test never returned and had to be killed at 600 s. | Use `asyncio.wait({req}, timeout=...)`, which returns when the timer fires, then cancel and **abandon** |
| **A finished project was reported as stalled** | Three boards at 100% done emitted `steering_stall` at 50–58 cycles, three projects, several times a second — the same log-spam class v2.8 had just fixed for the pause poll, reintroduced by the module written to replace it | `idle_cycles` now means "work was available but nothing moved"; a board with nothing actionable resets it |
| **Signals were level-triggered** | 16 identical `steering_doom_loop` rows for one stuck task; later **199** `steering_structural_block` rows | Every signal is edge-triggered: first sighting reports, repeats require the evidence to grow by `REPEAT_STEP`, and progress re-arms |
| **A success cleared the counter but not its report stamp** | A *fresh* loop after progress was silently suppressed | Counters and stamps are cleared together |
| **The Reviewer judged test failures from 400 characters** | It argued with the Builder across four escalated attempts about code it could not see, flip-flopped between opposite instructions, and cited `test_skipped_signature` — a test that does not exist. The harness collected the failing node IDs and never forwarded them | Reviewer now receives the failing test IDs, the skip count, missing modules, and a 2000-char tail |
| **Raw provider account IDs still reached the log** | `logtriage` reported 48 `user_*` and 11 `org_*` identifiers sitting raw in `logs/agent_log.jsonl` inside provider exception bodies. The scan rules existed but only ran at egress gates | Identifiers are now the one deliberate exception to exact-value-only sink redaction — they carry no diagnostic value, and every *other* credential shape is still exact-value-only so a Reviewer can still read credential-handling code |
| **The Planner had no retry** | One malformed reply produced a **zero-step plan** and the build proceeded with no planning at all | One re-ask with format pressure, mirroring the Reviewer |

### In my own work — the more useful half

Six of the escalations were **my** fault, not the system's. Every one was a
task objective that contradicted the test file I had written:

- `outliers()` specified as `dict[str, float]`, tested as a list of records
- `success_rate` specified as `calls/(calls+errors+timeouts)`, tested as `1.0`
  for one success plus one timeout
- `generic_signature` returning a token from one shape, tested against two
- a test helper defined as `_analyse_file_text` and called as
  `analyse_file_text` in eight places — a `NameError` in every test in the file
- `"well-formed empty value"` without saying which type, so `outliers: {}` and
  `cooldowns: {}` where lists were required
- a `_MIXED` fixture whose shapes contradicted the `generic_signature` contract

**The Reviewer caught every one of them, correctly, and escalated rather than
rubber-stamping.** That is the loop working. The lesson is uncomfortable and
specific: in a tests-first system the *tests* are the contract, and an operator
who writes an objective that disagrees with them has authored the ambiguity the
Builder then burns quota on. I proved the suite was satisfiable by writing a
reference implementation first — after which every remaining failure was
genuinely the Builder's.

## Using with an AI agent (OpenCode) — the intended workflow

The human does **not** hand-write task boards or test files. The intended
operating model puts a coding agent (OpenCode, Claude Code, Cursor, or a
plain chat model) in the driver's seat:

1. **Human:** describes what to build (a rough document is fine), approves
   model routing and cost, provides API keys.
2. **Coding agent:** reads **[`PROJECT_ONBOARDING.md`](PROJECT_ONBOARDING.md)**
   and performs every mechanical step — scaffolds the project, decomposes the
   spec into single-file tasks, writes the test files first (tests-first
   gate), configures dependencies and routing, validates the board, then
   starts and monitors `python main.py`.
3. **This system:** builds each task — plan → code → real tests → review —
   autonomously, with rollback and escalation handled internally.

`projects/project_main/` is a complete worked example produced this way.

---

## Architecture

```
                     +---------------------------+
                     |     SuperOrchestrator     |   tier 1
                     |  (supervision + manifest) |
                     +------------+--------------+
             spawns / restarts / pauses |
        +------------------------------+--------------------------------+
        |                              |                                |
+---------------+             +---------------+                (optional)
| ProjectOrch.  |             | ProjectOrch.  |          +------------------+
| project_alpha |             | project_beta  |          | IntegrationAgent |
+-------+-------+             +-------+-------+          |  (async queue)   |
        |  Planner -> Builder -> Reviewer (max 3 cycles) |          +--------+---------+
        +------------------------------+---------------------------------+
                                |                     notifications
                     +----------v-----------+
                     |   SharedWorkspace    |  patterns / anti-patterns /
                     |      Engine          |  draft logs / cache headers
                     +----------------------+
                                |
                     +----------v-----------+
                     |       LLMClient      |  <-- THE single LLM seam
                     +----------------------+
```

* **Tier 1 — SuperOrchestrator** (`super_orchestrator.py`): discovers
  `projects/`, spawns one `ProjectOrchestrator` asyncio task per project,
  supervises them (restart after 5 s backoff), writes `.system/manifest.json`
  with high-level statuses. It never loads code or runs tests.
* **Tier 2 — ProjectOrchestrator** (`project_orchestrator.py`): one per
  project; task-board scheduling (dependencies, priority high > medium > low),
  the Builder–Reviewer loop (max **3** attempts), cycle summaries, pattern
  promotion, integration notifications.
* **Tier 3 — Agents** (`agent_roles.py`): `PlannerAgent`, `BuilderAgent`,
  `ReviewerAgent`, plus the optional `IntegrationAgent`.
* **IPC:** structured JSON only, Pydantic-validated at every handoff
  (`validation.py`, `validate_or_error`). On validation failure the next
  stage receives a concise error such as
  `{"error": "Missing field: target_files"}` — never a raw traceback.

## Codebase map

| Module | Responsibility |
|---|---|
| `main.py` | CLI entry: single-instance lock, mode dispatch (`--once`, `--feed`, `--cmd`, `--dashboard`, `--preflight`, default loop) |
| `config.py` | Single source of truth for model routing / escalation / fallback, feature toggles, idempotent workspace bootstrap + seed boards |
| `validation.py` | Pydantic v2 models for every inter-stage message + `validate_or_error`, the one gateway all IPC passes through |
| `super_orchestrator.py` | Tier 1: project discovery, one supervised asyncio task per project (5 s crash backoff), manifest writer, IntegrationAgent host |
| `project_orchestrator.py` | Tier 2: board scheduling (atomic board writes), the Builder–Reviewer loop, real-execution gate (`_apply_and_test`), escalation + pattern decay |
| `agent_roles.py` | `LLMClient` (the single LLM seam), the four agent roles, and the response-coercion layer that normalizes real-model output before validation |
| `patcher.py` | Tolerant diff parsing, path safety (`resolve_target` + `path_is_denied`), hunk ambiguity guard, atomic writes, byte-exact snapshots and rollback |
| `executors.py` | Real pytest runner (fail-closed on every anomaly) + advisory `ruff` + the fail-closed Kaggle submission secret gate |
| `tool_registry.py` | JSON-schema tool catalog; resolves the minimal per-role tool set injected into prompts |
| `providers.py` | v2.6 multi-provider free-inference registry (OpenRouter, Groq, Gemini, Cloudflare, Z.ai, NVIDIA, Cohere; Mistral/Alibaba/Cerebras/local are opt-in only) |
| `model_router.py` | v2.6 free-model catalog + health registry + role-capability ranking + canary probes ("automatically choose reliable free models") |
| `quota_governor.py` | v2.6 per-provider RPM/TPM/RPD/TPD/monthly buckets, reserve, cooldowns, reset-aware deferral |
| `llm_cache.py` | v2.6 exact-match response cache (dedupes byte-identical LLM calls) |
| `divergence.py` | v2.6 divergent/convergent engine: strategy pools, plan lenses, blind-payload scoring, winner selection |
| `domain_registry.py` | v2.6 pack registry + the two generic hooks (task proposals at starvation, post-completion reaction) |
| `domains/kaggle_pack.py` | v2.6 Kaggle vertical: scaffold, campaign director, CV-gated submission; v2.7 validates the LLM-authored `target_files` / `run_command` |
| `redaction.py` | v2.7 secret layer: `redact_known_secrets` (exact-value, sink-side), `scan_secrets` (pattern detection, egress-side), `scrub_secrets` + the `--preflight` remediation. v2.8 also owns `write_json_atomic`, the single write discipline for polled state |
| `test_integrity.py` | **v2.8** frozen baseline of the grading apparatus: a pre-existing test, `conftest.py` or pytest config may not be rewritten unless `allow_test_edits` |
| `steering.py` | **v2.8** deterministic progress telemetry — doom loops, stalls, dependency deadlock, repeated failure shapes, burn rate. No LLM. Replaces pattern memory |
| `spec_critic.py` | **v2.9** objective-vs-tests consistency: a free deterministic tier (`ast`-based) plus merge rules for one model pass. A model can *add* findings, never clear a mechanical one |
| `spec_author.py` | **v2.9** goal → tests-first task chains. The authored tests are written *before* the tasks are baselined, and that ordering is what freezes them against Builder edits |
| `diagnosis.py` | **v2.9** escalation diagnosis: closed cause/remedy vocabularies, three gates before any board write, cause fed to the steering clusterer |
| `lines.py` | **v2.9** graph colouring of a board into conflict-free lines (shared files + intra-line ordering), with an independent validator |
| `shared_workspace_engine.py` | Anti-pattern **audit** store (append, dedup/merge). v2.8 retired pattern promotion/decay and the read-side TTL delete; the prompt-cache header helpers were removed as verified no-ops |
| `logger.py` | Thread-safe JSONL event log; never raises; optional console echo; redacts the message *and* every payload |
| `dashboard.py` | Watch-only feed + command console over the file-based control plane (no IPC) |
| `projects/logtriage/` | v2.8.1 dogfood project: 6 tasks, 105 tests, all agent-built (one operator-written). Reads this harness's own event log — the acceptance criterion is that its report's `events.total` matches the real line count |

## Run instructions

```bash
pip install -r requirements.txt   # includes pytest (real gate) + rich (dashboard)
copy .env.example .env        # (Linux/macOS: cp .env.example .env)
python main.py --preflight paths      # which env vars count as live secrets
python main.py --preflight scan       # walk the tree; exit 1 on findings
python main.py --preflight scrub      # dry run: what a remediation would change
python main.py --new-project my_app   # scaffold a new project
# have your coding agent fill the board -- see PROJECT_ONBOARDING.md
python main.py --dashboard    # orchestrator + two windows: live feed + command console
python main.py                # headless orchestration loop (Ctrl+C to stop)
python main.py --once         # single pass, then exit (testing/CI)
python main.py --models status             # free-provider rankings + quota
python main.py --models refresh            # refresh the free-model catalog
python main.py --models verify             # one live call per provider (key/endpoint check)
python main.py --new-kaggle my_comp --competition titanic --metric accuracy
```

`.env` holds live provider keys and per-project `.env` files hold brokerage
credentials. **`.gitignore` excludes them** — run
`python main.py --preflight scan` before your first commit, and never paste a
real key into `.env.example`. See "Secrets and egress" below.

### Real execution mode (`REAL_EXECUTION=true`, default in live mode)

In live mode the Builder's diff is **actually applied** to the project tree
and the Reviewer gate runs **real pytest** against the patched files:

```
parse -> scope guard -> snapshot -> apply -> real pytest -> Reviewer (real counts)
     -> APPROVED:      keep files, complete task
     -> CHANGES_REQUESTED: rollback to snapshot, retry (max 3)
     -> apply failure:  structured patch errors fed back as review feedback
```

Safety rails: only project-relative paths are writable (no `..`, absolute
paths, `.agent/`, `.git`, ...), credential-bearing names are not writable at
all (`.env*`, `*.pem|key|p12|pfx|jks|kdbx`, `id_rsa*`, `kaggle.json`,
`.netrc/.npmrc/.pypirc` — `patcher.path_is_denied`), writes are atomic, and
every attempt is rolled back byte-exact on failure/escalation -- a broken tree
is never left behind. `ruff` (optional) contributes advisory lint context to
the Reviewer. In DEMO_MODE nothing touches disk and tests stay simulated.

Three additional hardening rules learned in production use:

1. **Scope guard** -- a diff may only touch the task's declared
   `target_files`; anything else is rejected (prevents an overreaching diff
   from corrupting already-approved modules). The check runs **twice**: once
   on the paths parsed out of the diff, *before* `apply_diff` touches disk,
   and again on what actually landed (v2.7 -- the pre-apply pass means an
   out-of-scope file never exists on disk, not even briefly; the post-apply
   pass stays authoritative).
   Package-marker `__init__.py` files are exempt only as declared targets,
   siblings of targets, or package ancestors of targets
   (`patcher.scaffolding_allowed`).
2. **Collection-error resilience** -- the test runner passes
   `--continue-on-collection-errors` and folds collection errors into the
   failure count: one broken module fails only itself instead of aborting
   the whole suite.
 3. **Tests-first gate** (`requires_new_tests: true` on a task) -- the
    orchestrator records the pre-task passed-count baseline and requires the
    final run to EXCEED it: a green suite in which the task's own tests never
    ran (e.g. the module was never created) counts as CHANGES_REQUESTED.
    This pairs with the tests-first workflow: write the test files up front,
    have each test file self-skip until its implementation module exists
    (`pytest.skip(..., allow_module_level=True)` guarded by
    `importlib.util.find_spec`), and let the Builder implement exactly the
    declared file. See `projects/project_main/tests/conftest.py` for the
    pattern.

**Content-mode building** (`CONTENT_MODE=true`, default): for tests-first
tasks the Builder emits complete file contents in fenced blocks
(```python path=src/... ```) instead of unified diffs. Blocks are
syntax-checked, coverage-checked, scanned for module-level `sys.exit` /
`raise SystemExit` (a recurring model failure that silently kills pytest),
get misplaced `from __future__` imports auto-repaired by the patcher, and
are then applied through the same snapshot/scope/rollback rails.
Multi-file tasks generate one focused request per file (`CONTENT_PER_FILE`,
default on). This is what makes cheap builder models viable; attempts 1-2
use the affordable model and attempt 3 auto-escalates to the
`builder_escalate` role (default `anthropic/claude-sonnet-5`).

**Live dashboard** (`python main.py --dashboard`) — two **separate windows**
(the old single-TUI fought itself for the terminal; separation removed all
rendering conflicts):

* **Event feed window** — watch-only: per-project panels (status, current
  task, done/failed/pending) plus a live event stream including
  `llm_exchange` entries (model, duration, prompt/response heads — the
  models' visible "thought process").
* **Command console** — a dedicated REPL where every typed line is fully
  visible: `pause`, `resume`, `status`, `skip <task_id>`, `retry <task_id>`,
  `note <project> <text>`, `ask <question>` (answered live by the
  `super_orchestrator` model role with workspace context), `exit`.

Commands operate on the same file-based control plane the orchestrator
polls (`pause.flag`, task boards), so they take effect on the next loop
tick; closing either window never stops the build.

No API key configured ⇒ `DEMO_MODE=auto` ⇒ deterministic canned responses ⇒
fully offline. Demo tasks (`TASK-1001`, `TASK-2001`) are planned → built →
reviewed → approved on the first attempt, a pattern is promoted
(`P-0001`), the IntegrationAgent is notified, and the cross-project check
against `project_beta` (imports of `shared_util`) runs with simulated tests.

### Watching a run (how to use)

The console echoes one compact colored line per event by default:

```
[01:52:10 INFO] task_started :: project=project_alpha task_id=TASK-1001
[01:52:10 INFO] plan_created :: task_id=TASK-1001 steps=5
[01:52:11 INFO] reviewer_verdict :: task_id=TASK-1001 verdict=APPROVED
```

More ways to observe / control a run:

```powershell
# full structured event stream (second terminal)
Get-Content logs\agent_log.jsonl -Wait -Tail 20

# high-level statuses (running / idle / paused / crashed, restarts, current task)
Get-Content .system\manifest.json

# last completed cycle per project
Get-Content projects\project_alpha\.agent\cycle_summary.json

# pause everything (all project loops idle; remove the file to resume)
New-Item pause.flag          # in the workspace root
Remove-Item pause.flag
```

Stop the system with `Ctrl+C`. Default model slugs were refreshed against the
live OpenRouter catalog (Aug 2026) — override any role with `MODEL_OVERRIDES`.

## Plugging in real OpenRouter calls

The **only** integration seam is `LLMClient.complete()` in
`agent_roles.py` (search for `TODO: real OpenRouter call`). The live branch
already contains the client construction:

```python
from openai import AsyncOpenAI
client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1",
                     api_key=config.OPENROUTER_API_KEY)
resp = await client.chat.completions.create(
    model=payload["model"], messages=payload["messages"],
    extra_headers={"HTTP-Referer": "https://localhost",
                   "X-Title": "EnterpriseMultiAgentCodingSystem"})
```

Set `OPENROUTER_API_KEY` (or `DEMO_MODE=false`) to switch from stubbed to
live calls. Live calls run with an explicit `timeout=300` (s) and
`max_retries=1` on the OpenAI client — without it a hung connection stalls a
task for up to 30 minutes (SDK default: 600 s × 3 internal retries) before
the fallback chain even starts. Model routing / escalation / fallback policy
lives exclusively in
`config.py` (`MODEL_ROUTING`, `MODEL_FALLBACKS`, `select_model`,
`resolve_role`): builder attempt 1 → `builder_initial`, retries →
`builder_patch`; reviewer → `reviewer_bugfix` for bugfix tasks else
`reviewer_feature`; all roles fall back in the order of `MODEL_FALLBACKS`.

**Optional OpenCode CLI adapter:** to route a role through a local OpenCode
CLI instead of OpenRouter, wrap the subprocess call inside
`LLMClient._demo_response`/`_invoke` with the same signature:

```python
# e.g. in LLMClient.complete, add a branch before the OpenRouter call:
#   proc = await asyncio.create_subprocess_exec(
#       "opencode", "run", "--prompt", user, ...,
#       stdout=asyncio.subprocess.PIPE)
#   return (await proc.stdout.read()).decode()
```

All agents keep using `LLMClient`, so the adapter stays behind the same seam.

## Token-saving strategies

1. **Provider-specific prompt caching** — `SharedWorkspaceEngine.apply_cache_headers`
   annotates only *static* prompt parts (system prompt, global rules, pattern
   excerpts): Anthropic → `cache_control: {"type": "ephemeral"}` on the system
   block; Google → `x-goog-cache-control` marker; OpenAI → implicit (no-op).
   Additive only, controlled by `CACHE_ENABLED`.
2. **Dynamic tool injection** — `tool_registry.resolve_required_tools()` gives
   each role the *minimal* JSON-schema tool set (Builder: fs+lint; Reviewer:
   test+search; Planner: search). Orchestrators inject only that set.
3. **Compact retry payloads** — retries 2–3 send only `task_id`,
   `current_diff`, `last_feedback`, `max_retries_left` and the original plan;
   never the full message history.
4. **Top-3 pattern excerpts** — pattern/anti-pattern queries return at most 3
   matches (confidence > 0, best first).
6. **State-machine context** — agents keep a minimal conversation state; the
   Builder's conversation is reset before attempt 3 and restarted from the
   compact state (spec + latest feedback + plan + patterns).
7. **Compact cycle summaries** — `cycle_summary.json` holds only
   `task_id, attempts, verdict, model_used, duration_s` (+ escalation info).

## Quality-first strategies

* **Mandatory Planner** — every task is planned before any build attempt.
* **Cheap-first model escalation** — attempt 1 on `builder_initial`
  (affordable codegen), attempt 2 on `builder_patch` (cheap patches from
  compact feedback), attempt 3 auto-escalates to `builder_escalate`
  (premium model). Premium spend fires only when cheap attempts actually
  failed twice.
* **Builder self-check** — simulated lint/type checks run on the Builder's
  own output; findings trigger one auto-fix + re-check before returning
  (`self_check_passed` is surfaced to the orchestrator).
* **Bugfix verdict rules** — APPROVED only when all simulated tests pass AND
  (feature OR diff includes a regression test AND root cause identified).
  A failing simulated test can *never* be approved.
* **Reviewer calibration + auto-approve** — the calibrated Reviewer must
  default to APPROVED when real tests pass and acceptance criteria look
  met; and when its output is unparseable after one retry while the
  deterministic gates are fully green (real tests passed, new-tests
  baseline exceeded), the build is **auto-approved** — the gates are
  authoritative, an absent review never vetoes verified work.
* **Anti-pattern reuse** — **retired in v2.8.** This used to claim anti-patterns
  were "injected into every attempt"; the code injected them only on the final
  attempt, only into the Builder, and the text was ~1.3 KB of raw provider
  error prose with no task-relevant signal. Escalations are still recorded as
  an audit trail. (v2.9: the Council that read them is gone.)
* **Pattern promotion only on green tests** — **retired in v2.8.** Nothing read
  a promoted pattern back into a prompt, the decay path was unreachable (zero
  decrements in 36,646 log lines), and the 30-day TTL ran on *read*, so
  querying memory deleted records. Superseded by `steering.py`, which measures
  progress from counters instead of replaying old notes.

## IntegrationAgent

Enable/disable with `ENABLE_INTEGRATION_AGENT` (default `true`). Flow:

1. Each ProjectOrchestrator notifies `IntegrationAgent.queue` after a
   completed task (`source_project, task_id, files_changed, status`).
2. **Conflict heuristic:** other projects' `src/` files are scanned for
   imports of the touched module basenames (e.g. `shared_util`). Only names
   that correspond to a module that actually exists in the source project's
   `src/` count — the raw `modules_touched` list contains every imported
   symbol (`__future__`, `annotations`, typing names, …), which otherwise
   matches every project and burns a pointless LLM call per task completion.
   The LLM is invoked **only** when a conflict is suspected.
3. On suspected conflict → the dependent project's tests run. In live mode
   this is REAL pytest against the dependent project (fail-closed: an
   unavailable, timed-out or red suite counts as a conflict), executed off
   the event loop; DEMO_MODE keeps it simulated.
   On failure → a patch task (with `error_signature`) is inserted into the
   originating project's task board and the project is notified; if that
   fails → escalation to the SuperOrchestrator via a structured
   `IntegrationReport` (persisted in `.system/integration_reports.json`).

**Demo cross-project scenario:** `project_alpha` exports
`src/shared_util.py`; `project_beta` imports it (`src/consumer.py`). When
alpha completes a task touching `shared_util`, the heuristic flags beta, the
conflict-analysis LLM call fires, and beta's tests are simulated (pass → no
patch task needed).

## Pause flag and self-healing

* `pause.flag` (workspace root): while present, the SuperOrchestrator pauses
  spawning **and** every ProjectOrchestrator loop idles; remove the file and
  everything resumes. State transitions are logged and mirrored in
  `.system/manifest.json` (`"paused": true`).
* **Single-instance lock:** `main.py` takes an OS-level
  `.system/orchestrator.lock` for every orchestrator-bearing mode (default,
  `--once`, `--dashboard`); a second start refuses with exit code 2. This
  prevents two suites from racing the boards, snapshots and manifest —
  a race whose signature is double `task_escalated` events, manifest write
  errors, and rollbacks that resurrect each other's files. The watch-only
  `--feed` / `--cmd` windows are exempt and may run alongside any suite.
* **Manifest write resilience:** the manifest writer uses a unique temp file
  per write and retries transient `OSError` (reader locks) with backoff
  before logging `manifest_write_failed`.
* **Self-healing:** a crashed ProjectOrchestrator task is logged with
  traceback and restarted after a **5 s backoff**; consecutive restarts are
  tracked (a tight restart loop escalates to CRITICAL and stops restarting
  that project).

## v2.5.4 hardening

Applied from the code audit that produced the original Known-limitations
list. Each fix is behavior-preserving on green paths and stricter on
failure paths; verified by a 41-check harness (anchor policy, scaffolding
rules, apply semantics, merge math, atomic writes, live/demo branches,
builder tool-hallucination defenses).

1. **Anti-pattern memory dedup + merge-on-save** (`shared_workspace_engine.py`)
   — same-signature escalations now increment an `occurrences` counter and
   refresh the newest description / strongest severity instead of appending
   duplicates; every save merges historical duplicates (lowest id kept,
   occurrences summed, volume preserved). New ids derive from
   `max(existing) + 1`, never list length.
2. **Atomic task-board writes** (`project_orchestrator.py`) — `_save_board`
   now uses tmp-file + `replace`, matching the dashboard's write
   discipline (pollers never see a torn read). *v2.8 closes the other half:
   the IntegrationAgent's board write was **not** atomic and was the source of
   torn reads, and a failed read used to be written back as an empty board.*
3. **Real dependent-project tests in live mode** (`agent_roles.py`) — the
   IntegrationAgent runs real fail-closed pytest (via `asyncio.to_thread`,
   off the event loop) against suspected dependents; simulation remains
   DEMO_MODE-only.
4. **Scope guard `__init__.py` tightening** (`patcher.scaffolding_allowed`,
   enforced in the orchestrator scope guard and the Builder content
   checks) — package markers are exempt only as declared targets, siblings
   of targets, or package ancestors of targets.
6. **Hunk ambiguity guard** (`patcher.py`) — a multi-line hunk context
   matching at several positions (none at the declared offset) fails the
   hunk with a structured `ambiguous context` reason instead of silently
   editing the nearest occurrence; single-line contexts keep
   nearest-match behavior within the search radius.
7. **New-file hunks replace existing files** (`patcher.py`) — a
   content-mode regeneration over a file that already exists now replaces
   it wholesale instead of prepending the new content to the old.
8. **Configurable `--once` budget** — `ONCE_BUDGET_S` (default 600 s) with
   an explicit `once_budget_exhausted` warning when pending tasks remain.
9. **Builder anti-tool-hallucination hardening** (`agent_roles.py`) —
   content-mode prompts now state the listed tools are advisory-only (run
   by the harness *after* the response) and the `Available tools:` JSON
   appendix is no longer sent to the Builder — that appendix was the
   inducement behind models burning all attempts "calling" `fs.read_file`
   on a three-attempt escalation (TASK-7010B). Bare `<tool>` markup is now
   stripped alongside `<tool_call>`, and a lone path-less fenced block is
   accepted as a single-target file's content (the leniency per-file mode
   already had). Diff-mode behavior is unchanged.
10. **LLM call resilience** (`agent_roles.py`, `config.py`) — an *empty*
   completion is treated as a provider failure and walks the fallback
   chain instead of feeding an unusable response into the agents; every
   candidate call is additionally bounded by a wall-clock budget
   (`LLM_CALL_TIMEOUT_S`, default 360 s) because the SDK's per-read
   timeout never fires on a slow-drip response (observed: a 926 s empty
   reply).

## v2.5.5 — failure recovery + observability

The previous behavior on escalation was *fail fast and starve*: a `failed`
task stayed failed forever and every dependent sat `pending`-but-ineligible,
so the loop went quiet and looked dead. Two changes fix that without
abandoning the fail-fast philosophy:

1. **Bounded auto-requeue** (`project_orchestrator.py`, `config.py`) —
   when a project loop has *no eligible work*, a `failed` task is requeued
   to `pending` after `FAILED_RETRY_COOLDOWN_S` (default 600 s) — at most
   `FAILED_AUTO_REQUEUES` (default 1) times per task, tracked in the task's
   `auto_requeues` field; `0` disables the feature. Guarantees: it only
   ever fires at starvation time (never preempts healthy work); dependents
   of a failed task are still never auto-run; a manual `retry`
   (dashboard/operator) grants a fresh budget by clearing
   `auto_requeues`/`failed_at`. Escalation still records the anti-pattern
   and remains the signal to re-read the spec — the auto-requeue is a
   second chance, not a substitute for diagnosis.
2. **Starvation observability** — every project's manifest entry gains a
   `board` block (`done`, `failed`, `pending`, `blocked`, `failed_ids`),
   computed by `compute_board_stats` with the same dependency-eligibility
   rule the scheduler uses; the idle transition logs
   `project_idle_blocked`, and the dashboard feed gains a `blocked`
   column. An idle system now explains itself.

## v2.5.6 — failure evidence + environment self-healing

First two steps of the autonomy roadmap (the operator tasks this system
kept needing, moved into the machine):

1. **Structured failure evidence** (`executors.py`) — every real pytest run
   now returns machine-readable `missing_modules` (parsed
   `ModuleNotFoundError: ...` lines; the runner switched to `--tb=line` so
   collection-error reasons survive) and `failing_tests` (FAILED/ERROR
   ids, capped). The tests-first gate's feedback and `new_tests_gate_blocked`
   logs carry both, so retries target the actual broken tests and imports.
2. **Environment self-healing** (`executors.py`, `project_orchestrator.py`)
   — when the gate fails on missing imports, the orchestrator runs
   `pip install -r projects/<p>/requirements.txt` **once per task**
   (`asyncio.to_thread`, `PIP_TIMEOUT_S` budget) and re-runs the gate with
   the files still applied. Requirements-only policy: the project's own
   file is the single source of truth for what may be installed — pip
   resolves its listed packages *and* their missing transitive deps (the
   click-under-typer failure class). Knob: `ENV_AUTOHEAL_ENABLED` (default
   true); events `env_autoheal_started/completed/failed`; still-missing
   modules fail closed with a precise message.
3. **Reviewer calibration backstop** (`agent_roles.py`) — reviewer tools
   are advisory-only (no `Available tools:` JSON appendix; the same
   anti-hallucination treatment as the builder, after a reviewer was
   observed emitting fabricated search results instead of a verdict), and
   gate authority is extended: an *evidence-free* rejection of a fully
   green build (failed == 0, new-tests baseline exceeded, zero findings)
   is an absent review and auto-approves (`reviewer_auto_approve_no_findings`).
   Genuine findings always stand; failing tests can still never approve.

## v2.6 — free multi-provider capacity, objective gate, divergence, domain packs

The core is still a general autonomous coding company; the v2.6 work makes
it run on **free models by automatic reliability selection**, adds a
**generic objective gate** (experiments/benchmarks, not just pytest), a
**divergent/convergent candidate engine**, and moves Kaggle to an optional
**domain pack**.

1. **Free multi-provider routing** (`providers.py`, `model_router.py`,
   `quota_governor.py`, `llm_cache.py`) — every credentialed free provider
   (OpenRouter, Groq, Gemini, Cloudflare, Z.ai, NVIDIA, Cohere; Mistral,
   Alibaba, Cerebras and local servers are opt-in only) becomes an
   OpenAI-compatible candidate.
   Candidates are filtered by role capability (JSON roles need
   `structured_outputs`/`response_format`; long-form roles need output
   headroom and TPM — Groq's 8k TPM excludes it from builder runs), then
   ranked by benchmark prior + observed health (EWMA of call success,
   parse adherence, gate outcomes, latency) + quota headroom. Canary
   probes (`--models probe`) cold-start the health registry; real runs
   keep learning. Exact-match caching dedupes byte-identical calls.
2. **Quota governor** — per-provider rolling/persistent buckets (RPM/TPM/
   RPD/TPD/monthly), a reserve held for probes/retries, per-role daily
   caps, 429 cooldowns honoring `Retry-After`, and a live OpenRouter
   `GET /api/v1/key` reading. When capacity is exhausted the call raises
   `LLMUnavailableError` and the task is **deferred to the earliest
   provider reset** (`defer_until`) — never escalated, never paid unless
   `FREE_MODELS_ALLOW_PAID_FALLBACK=true`. `FREE_MODEL_ROUTING=false`
   restores the legacy static routing byte-for-byte.
3. **Generic objective gate** (`executors.run_objective`) — a task with a
   `metric` spec and `run_command` runs a real experiment/benchmark and
   gates on its `reports/metrics.json` instead of pytest pass-count
   growth: fail-closed on timeout (Windows tree-kill), non-zero exit,
   unreadable JSON, missing required fields, `split_hash` mismatch, target
   misses and min-improvement misses. Reviewer auto-approve and pattern
   promotion treat a green objective gate exactly like green tests.
4. **Divergence/convergence** (`divergence.py`) — opt-in per task
   (`divergent: true`, `n_candidates`) or per project
   (`.agent/divergence.json`), plus plan-level lenses
   (`PLAN_DIVERGENCE`). Each strategy brief drives one Builder pass; every
   candidate is gated on a clean tree (snapshot restored after scoring),
scored gate-first, and the winner is re-applied for the normal review
path. The blind judge is consulted only for near-ties
(`DIVERGENCE_TIE_EPSILON`) and can never beat a gate-failing candidate.
An optional LLM merger (`DIVERGENCE_MERGE_ENABLED`) combines the
gate-passing near-tie candidates into one implementation that must
re-pass the gate and meet/beat the winner's score. Candidates are
archived under `.agent/candidates/<task>/`.
6. **Domain packs** (`domain_registry.py`) — packs plug into two generic
   hooks: task proposals when the board starves and a post-completion
   reaction. `domains/kaggle_pack.py` is the first: `--new-kaggle`
   scaffolds a campaign (data/src/experiments/reports/submissions, context
   with the split-hash contract, starter hypotheses), queued hypotheses
   become `experiment` tasks when `CAMPAIGN_AUTO_GENERATE=true`, and a
   format-validated `submissions/submission.csv` is submitted only on CV
   improvement, under a daily cap, and only when `KAGGLE_AUTO_SUBMIT=true`
   (`kaggle competitions submit --wait`, ref + score recorded for
   CV-vs-LB drift). An LLM campaign director (`CAMPAIGN_DIRECTOR_ENABLED`)
   generates new experiment hypotheses from the campaign state after every
   result, making the competition loop fully autonomous. The core stays
   domain-agnostic.
7. **Observability** — `python main.py --models status` prints provider
   credentials, quota headroom, reset times, top ranked builders, cache
   stats; `--campaign-status PROJECT` prints the Kaggle campaign ledger;
   new events include `candidate_scored`, `divergence_winner_selected`,
   `objective_gate_passed/blocked`, `task_deferred_llm_unavailable`,
   `domain_tasks_proposed`, `kaggle_submission_*`.

## v2.7 — secrets and egress

v2.6 put ten third-party providers, a `shell=True` objective gate and a
competition upload in the credential path. The gates were fail-closed but
nothing *redacted* or *scanned*: a credential that reached a log call site, a
prompt, or a submission file stayed there. This pass adds that missing layer.
It is deliberately two primitives, not one — see "Secrets and egress" above
for the boundary map.

**Why two primitives.** A single pattern-based scrubber would have been both
useless and harmful. Blanking anything key-shaped inside a prompt blinds the
Reviewer on exactly the credential-handling code it exists to check — and
`projects/project_main` is a broker integration whose entire job is handling
`ALPACA_SECRET_KEY`. So:

* `redact_known_secrets` replaces only the **literal values this process
  already holds**. Zero false positives by construction. Applied
  unconditionally everywhere.
* `scan_secrets` only **detects**. It gates egress, where a false positive
  costs one withheld submission and a false negative publishes a live key.
* `scrub_secrets` (the applying variant) exists only for one-shot
  remediation of files that already hold leaked values.

1. **Sink redaction** — `logger._safe_data` (all ~90 `log_event` sites),
   the `llm_exchange` heads, `LLMClient.complete` (the single outbound
   choke point), `SharedWorkspaceEngine._write_json`, `llm_cache.put`,
   `divergence.store_candidate`, and the Kaggle audit `detail`. Discovery
   reads `os.environ` **and** every `.env`, collecting values from *all*
   sources rather than first-wins-per-name — otherwise a placeholder in one
   source shadows the live value in another.
2. **Egress gates** — `executors.run_kaggle_submit` refuses fail-closed at
   the last point before `subprocess.run`, scanning both the submission file
   and the `-m` message (which also travels off-box); the Kaggle pack logs the
   cause at the point of decision. Subprocesses still inherit the full
   environment, so the LLM-authored `run_command` is constrained to a plain
   `python`/`py` invocation: `env > reports/metrics.json` exits 0, leaves a
   parseable `reports/metrics.json`, **passes the objective gate**, and would
   then upload every credential to the competition. Refused commands are
   stored as `null` and fail closed with `task declares no run_command`.
3. **Write-path hardening** — `patcher.path_is_denied` refuses `.env*`,
   `*.pem|key|p12|pfx|jks|kdbx`, `id_rsa*`, `kaggle.json`, `.netrc/.npmrc/
   .pypirc` and credential-named files. The credential-name heuristic applies
   only to non-source extensions, so `secrets_manager.py` stays writable while
   `prod-secret.yaml` does not. The scope guard now also runs **before**
   `apply_diff`, so an out-of-scope file is never on disk even briefly.
4. **Untrusted model output** — a campaign hypothesis's `target_files` (which
   the scope guard treats as the allow-list) is filtered through
   `resolve_target`; every system prompt gains an untrusted-data clause; and
   `<<<SECTION>>>` delimiters inside untrusted text are neutralized so
   competition data cannot impersonate harness framing.
6. **`--preflight`** — `scan` (walk the tree, exit 1 on findings; run before
   every commit), `paths` (which variables count, names only), `scrub`
   (**dry run by default**, `--apply` to write with a timestamped `.bak-`
   backup first). Findings carry a `sha256(value)[:8]` hint — repeated hits on
   one secret correlate without any of it being readable.
7. **`.gitignore`** — absent until now, with 13 live keys on disk. Excludes
   `.env`, `projects/*/data/raw/`, `submissions/`, private-key material and
   the machine-local state directories, while keeping `.env.example` tracked.

New events: `kaggle_submission_blocked_secrets`, `secrets_scrub_completed`,
`campaign_target_file_rejected`, `campaign_run_command_rejected`.

## v2.9 — the system authors its own specification

v2.8 hardened the gates. v2.9 moves the work *before* them, because the
logtriage build measured exactly where the effort was going: **all 12 task
escalations sat at the human handover boundary, and none was an engineering
defect.** Six were contradictions between an objective and a test file that were
each individually reasonable. The Reviewer found them — after up to three
Builder attempts and a rejection each. That is a system paying maximum price to
discover something readable for free.

### Three defects found and fixed before any of this worked

Recording these because they are the kind that produce *plausible wrong output*
rather than an error, and all three were found by running the new code against
the real workspace rather than against fixtures:

1. **The core suite could not run as a whole.** `tests/test_secret_sinks.py` did
   `from conftest import _TEST_LOG_DIR`, and two directories ship a module named
   `conftest` — so the import bound to `projects/project_main/tests/conftest.py`
   and collection failed. Replaced with a fixture, which resolves through
   pytest's registry rather than `sys.modules` and cannot collide. `pytest.ini`
   now scopes the bare root run to `tests/`, which also fixes a basename
   collision between the two `test_providers.py` files.
2. **`logtriage` verified nothing when run from the wrong directory.** It has no
   root `conftest.py`, so `import src.triage.reader` depended on the CWD landing
   on `sys.path`. From anywhere else, every module skipped and the suite
   reported `6 skipped` with exit code 0 — indistinguishable from healthy. All
   105 tests pass from any directory now, and the Spec Author emits a conftest
   for every project it scaffolds.
3. **The Builder's conversation leaked across tasks.** `reset()` fired only at
   `attempt == MAX_ATTEMPTS`, so `_history` was never cleared at a task
   boundary: task 2's first attempt opened with task 1's objective, diff *and*
   reviewer feedback still in the conversation, while being asked to write a
   different file. Fixed, and asserted at the source level so the loop structure
   itself is pinned.

### 1. Spec Critic — verification moved left (`spec_critic.py`)

Two tiers, split by whether the question has an exact answer.

**Deterministic, free, instant** — runs in the synchronous scheduler where there
is no LLM to call with: a test importing a name the module does not define (the
`ImportError`-at-collection class, invisible to a name-based scan because the
name *is* bound); a declared `-> dict` return indexed as `[0]` in the test (the
runtime `TypeError` class, where both sides spell everything correctly); a task
promising tests it cannot resolve; a protected pre-existing file in
`target_files`.

**One model call per task**, with the *full* objective and the *full* test
source — better posed than the Reviewer, which gets a diff and 2000 characters
of pytest output. Severity `high` holds the task; lower severities annotate the
objective and the build proceeds.

The model can only *add* findings. It cannot clear a mechanical one, because a
model that says "actually this is fine" must not be able to un-flag a test
importing a name nothing defines.

**Tuning this against reality was the whole job.** The first version blocked
**24 of the 28** already-completed tasks — it would have refused almost the
entire backlog, and a check like that gets switched off and then protects
nothing. Each false block was a specific overreach: names bound inside a function
reported as undefined (Python resolves those against the enclosing scope);
not-yet-created tests-first test files treated as protected files; and
"presupposes this symbol exists" widened from a specific cue to every symbol in
the document. Now **0 of 28**, and
`test_critic_is_silent_on_every_completed_task_in_the_workspace` asserts it
against the real boards so it cannot regress.

### 2. Spec Author — the system writes the contract (`spec_author.py`)

```
python main.py --new-project NAME --goal "one paragraph"
python main.py --new-project NAME --goal "..." --author-plan   # read it first
```

The author proposes chains of tasks, each with its objective and **its own
test**. Ordering is what makes this safe:

1. author the plan;
2. **write the tests to disk, before the tasks exist**;
3. run the Critic over each task;
4. only then append the survivors to the board.

Step 2 is the mechanism. `TestIntegrityGuard` snapshots protected files when a
task *starts*, so a test that already exists at that moment is frozen — verified
by probe: the Builder's rewrite is refused, the node-ID gate still fires, and
the suite goes green. The system writes the contract **and is forbidden from
quietly editing it**.

Tasks are emitted as independent *chains* rather than a flat list, because chain
shape is what makes the line partition free (below). Written tests are never
placed in `target_files`; nothing is overwritten, and a refusal marks the task
rather than silently scheduling work whose test does not exist.

### 3. Escalation diagnosis (`diagnosis.py`)

Escalation used to be terminal. The task arrived at a human as a stack trace, and
auto-requeue handed the identical objective back to the Builder — observed
repeating seven times. The reason is structural: the escalator recorded *that* a
task failed and nothing about *why*, so the retry had no new information.

One call per escalation, on data already recorded, producing a cause from a
closed vocabulary and a remedy. Three gates before anything touches the board:
the remedy must be one of two reversible ones, it must be on
`BOARD_WRITE_ALLOWLIST`, and confidence must clear `DIAGNOSIS_MIN_CONFIDENCE` —
the diagnosing model also participated in the work that failed, so its opinion is
not independent evidence. The `cause` string feeds the steering clusterer, so
three `spec_ambiguous` escalations surface as one systemic block instead of
three silent failures.

### 4. Model intelligence — stop trusting typed-in numbers (`model_router.py`)

Three ways the harness was confidently wrong, all from the reference build:

- **Capability outweighed measurement.** The blend weighted a hand-typed
  `coding_index` at 0.35 against measured success at 0.30. `qwen3.8-27b` scored
  0.857 on a `60.0` typed in months earlier while measuring **0.67 across 202
  calls with 66 hard errors**. Weights are now 0.20 / 0.50, and each candidate
  carries `evidence: measured | sparse | asserted`.
- **Probing could only confirm its own priors.** `probe_models` took its targets
  from `rank_candidates`, so an unannotated model (flat 0.5) ranked below the
  cutoff, was never called, kept `calls == 0`, held its 0.60 neutral prior, and
  kept ranking below the cutoff. **13 of 17 unannotated seeds were locked out of
  evidence permanently.** Probe order is now least-observed-first.
- **Live discovery was declared and never wired.** `supports_models_endpoint` was
  set for OpenRouter and read by nothing; `MODEL_PROBE_ENABLED` was defined and
  read by nothing. Groq, Gemini, NVIDIA, z.ai and Mistral are now refreshed from
  their own `/models`, with a roster diff logged as `model_catalog_changed` —
  which is how NVIDIA's retired gpt-oss-120b/llama-3.3 line would have been
  *detected* rather than discovered by a failing task and fixed by hand.

### 5. Learned rate limits (`quota_governor.py`)

217 genuine `http_429`s in one build, 281 of 325 cooldowns from groq alone.
Backoff was never the problem — it escalated correctly, 30s → 60s → 120s. The
**limit** was: `GROQ_RPM=30` is simply wrong, so the governor kept sending
requests at a rate the provider refuses. The effective limit is now learned from
the provider's own refusals, floored, and recovered only after a sustained clean
run — and persisted outside the daily ledger reset, which would otherwise forget
it every midnight.

### 6. Unbroken lines (`lines.py`, `LINE_COUNT`)

Line assignment is **graph colouring, not a model decision**. Two tasks may share
a line unless they share a `target_files` entry; a dependency constrains
*ordering*, not placement, because the scheduler's dependency gate already
handles waiting. Deterministic, free, and validated before publication — a
partition that cannot be proven safe is not published.

Measured on the real boards: `logtriage` (6 tasks, 6 files, 0 shared) splits
into 2–3 balanced lines with nothing serialised; `project_main` (20 tasks, **3
shared files**) holds exactly those three pairs together and splits the rest.

Two bugs here produced plausible wrong output and are pinned by tests: unioning
on *dependencies* collapsed the fully-parallel `logtriage` board to one line at
every line count, and ordering components independently left `TASK-7011` ahead of
its own dependency `TASK-7010B`.

**`LINE_COUNT` defaults to 1** — exactly the pre-v2.9 behaviour. RPM is the
binding constraint on this account, so raise it only after the learned limits
have settled. The partition is published in the manifest at any setting, so the
opportunity is visible before it is taken.

## v2.9.1 - the specification pipeline, made to actually work

v2.9 added three pre-Builder surfaces and then dogfooded them. Running them
against a real goal -- a double-entry bookkeeping library, seven tasks authored
from a one-paragraph brief -- showed that most of the machinery was present and
four load-bearing connections were missing. Every item below was found by
running the system, not by reading it.

### The author and the critic were sending the wrong system prompt

`BaseAgent._complete` derived the system prompt from
`self.role.split("_")[0]`. For `spec_author` and `spec_critic` that yields
`spec`, which is not a key in `_SYSTEM_STATIC`, so the lookup fell through to
the **Planner's** prompt -- which asks for
`{"task_id", "steps", "data_structures", "edge_cases"}`.

So the author was instructed to produce a *planner* envelope, and the answer
that kept coming back -- `{"task_id": "task-001", "steps": [...]}`, followed by
`authored zero tasks` -- was the model correctly obeying the prompt it had
actually been given. The entire authored-schema prompt, worked example
included, was dead code. `_complete` now takes an explicit `system=`, both
agents pass their own, and `test_injection_defense.py` asserts generically that
no agent can silently fall through to the Planner's contract again.

### The router ranked a model that returned nothing highest

Two independent faults, both about evidence the system had and did not use.

* **A withdrawn model stays first.** Health is recorded per
  `(provider, model, role)` and needs 20 aggregated calls before quarantine, so
  `openrouter|qwen/qwen3.8-27b:free` -- 23 planner calls, 16 successes -- ranked
  **first** for four roles and then answered every live call with
  `404 This model is unavailable`. Its two failures had just landed in the
  `spec_author` slice, where a 2-call sample cannot move a 20-call threshold.
  Absence is now its own fast, expiring signal
  (`model_router.mark_model_unavailable`, `MODEL_UNAVAILABLE_COOLDOWN_S`)
  applied to every role at once, deliberately kept out of the quality registry
  and re-admittable by `--models probe`.
* **Silence scored as speed.** `latency_ewma` starts at `0.0` and is only
  written when a call *returns*, and the health blend contained
  `1.0 if latency <= 20.0 or latency <= 0`. A model that had never once
  responded therefore scored a perfect 1.0 on 15% of its health -- the router
  was rewarding non-answers as fast. Unmeasured latency is now neutral (0.5),
  never-answered is the floor (0.1), and "0 successes in N attempts" quarantines
  at `QUARANTINE_MIN_CALLS_ZERO_OK` (5) instead of 20, because never having
  responded is a fact rather than a rate.

### The output budget for authoring was checked against the wrong thing

`spec_author` matched no role prefix, so it fell through to the `json` kind,
whose only length gate is `MODEL_MIN_MAX_OUTPUT` (4096). That admitted a model
with `max_output=8192` as the top author candidate -- a budget that cannot hold
three small test files, let alone eight. Roles that emit **whole files** inside a
structured envelope are now a distinct kind (`file_bearing`) with their own
floor (`MODEL_FILE_BEARING_MIN_MAX_OUTPUT`, 32768).

Authoring is also **two stages** now: stage 1 asks only for the breakdown
(ids, chains, exact API specs, dependencies) as a small JSON object, and stage 2
makes one focused call per task for its test file. Asking one call for a
multi-task breakdown *with every test inline* is the same structural mistake
content-mode removed for Builders, and it failed the same way -- a list of
English sentences, `{"tasks": [{}]}`, test bodies with the function names
stripped (`def:`). Splitting it also makes each test independently cached,
retryable and droppable, so one bad test no longer costs the whole plan.

### `--once` did not run the pass it advertised

`_run_once` answered "is there work left?" by grepping the boards for
`status == "pending"`. A goal-only project's board is *empty* until the Spec
Author writes one, and that is indistinguishable from a finished one -- so the
documented `--new-project NAME --goal ...` then `--once` returned in 3.5 s
having authored nothing, and could return before any project loop had made a
single scheduling decision.

Each loop now reports `loop_state` and `work_available` when it decides, and the
pass waits for those reports (`ONCE_BOOT_S` bounds the wait so a wedged loop
cannot hold it open). The same number also shows up in the manifest, which
distinguishes "finished" from "has not been given a turn".

### Feedback that described the wrong problem

Three fixes, all measured on the build that provoked them, and together they
turned a task with nine wasted Builder attempts into one that passed first try.

* **The gate could not tell "no module" from "no name".** Only
  `ModuleNotFoundError` was extracted, so `ImportError: cannot import name
  'EntryType' from 'src.ledger.journal'` -- a module that is present and does
  not define what the Builder invented -- arrived as a bare "tests did not run",
  and the remediation said "implement the target module", which the Builder had
  already done. `missing_names` is now extracted and gets its own remediation.
* **A wrong import path got a generic example, not an answer.** The Builder was
  told `from src.journal import X` was wrong and replied
  `from src.ledger.journal.entry import X` -- right package, invented submodule.
  `spec_critic.nearest_project_module` now names the file that *does* exist.
* **A detected doom loop changed nothing.** `steering` reported 16 doom-loop
  signals and 29 gate blocks with **zero** interventions: the loop kept planning,
  kept building, kept producing the identical diff, and handed the task back.
  A doom loop is now a stop signal -- the attempt loop halts and escalates with
  the diagnosis. Attribution needed care: the shape that actually fires carries
  `task_id=None` (it is one project-level row per recurring *token*), so a naive
  task-id filter discarded it. It is matched against the task's own
  `error_signature`, and an unattributable loop logs `doom_loop_unattributed`.

### Diagnostics that could not reach a conclusion

Every escalation came back `confidence 0.0` with no evidence, so no remedy was
ever auto-applied and every one logged as inconclusive. Three causes:

* the prompt never stated the response shape, so `confidence` and `evidence`
  were simply absent and `coerce` defaulted them to 0.0 and `[]`;
* the evidence block contained no **test source**, so "the Builder is wrong" and
  "the contract is impossible" were indistinguishable -- the two need opposite
  remedies, and picking wrong is what produces seven identical retries;
* `Diagnosis.feedback()` existed and was never called, so the conclusion died in
  the log. `last_feedback` now opens with `DIAGNOSIS: ...`, and a zero-confidence
  diagnosis says *no conclusion* rather than printing a cause word with nothing
  behind it.

With those in place the same unsatisfiable task was diagnosed `spec_wrong` with
a proposed objective instead of `env_broken` at confidence 0.0.

### Rules that were only suggestions

Three rules lived in the documentation and were enforced nowhere. They are now
deterministic Spec Critic findings, all `medium` so they report without blocking
a board that demonstrably worked (`projects/project_main`, 20 tasks):

| finding | catches |
|---|---|
| `multi_file_task` | more than one implementation module per task -- the leading cause of escalation. Exempt for `allow_test_edits` bootstrap tasks, which is exactly one. |
| `duplicate_target_file` | two tasks claiming one file: the second silently overwrites the first under `LINE_COUNT=1`, and they race under a real partition. The reference board contains two such pairs. |
| `cross_task_dependency_missing` | a test importing a module another task creates, with no dependency edge -- so both are eligible at once and the gate reports a confusing `passed == baseline`. |
| `unresolved_project_import` | an import into the project's own namespace that resolves to nothing. Distinguishes a *wrong path* (`src.journal` for `src/ledger/journal.py`) from a missing dependency, which is what an environment self-heal handles. Exempts guarded imports and the task's own not-yet-written module. |

`multi_file_task` was found by reading a real `--author-plan` output the way an
operator does: a seven-task plan in which one task declared `trial_balance.py`
*and* `reports.py` under a single test file.

### Smaller corrections

* `project_idle_blocked` fired on every completed project (`blocked=0
  failed_ids=[]`). It now only claims a block when something is blocked or
  escalated; otherwise it logs `project_idle` and says why.
* Authored tasks carry an `error_signature`, derived from the module under test
  when the model omits one. The escalation fallback `TASK:<id>` normalised down
  to the bare token `TASK`, so every escalated task looked like the same
  signature as every other -- and steering cannot attribute a loop to a task
  with no signature.
* Authored tasks get the **full** Critic (deterministic *and* the semantic tier),
  not the free tier only. The author is the weaker party, and the semantic tier
  is the only check that sees a test asserting `entry.account` when the
  objective declares `JournalEntry(date, memo, postings)`.
* `_objective_symbols_missing` matched a bare `exposes?`, so "the Ledger class
  **must expose** the methods" demanded that a symbol named `the` already exist.
  It now requires an existence-asserting cue ("already exposes"), plus a
  prose-word guard.
* `LLMClient.record_outcome` is used for authoring quality. Previously only the
  Builder had an outcome signal, so a model that answered every prompt with a
  list of English strings scored the same as one that writes correct tests.
* Rejected drafts name their own failure ("a str, not a task object: ...")
  instead of the generic "task #N was not a usable draft".

## v2.8 - the gates the Builder cannot edit

v2.7 made sure secrets did not leak. v2.8 makes sure the **verification cannot
be subverted**, and replaces the pretend-memory with real self-monitoring. It
was prompted by an audit of the reference run's own 36,646 log events.

### 1. Test integrity (`test_integrity.py`)

The system's one real strength is that verification is harness-owned: real
pytest, fail-closed parsing, byte-exact rollback. That guarantee had a single
large hole — nothing stopped a diff from rewriting the tests it was about to be
graded against, and because `target_files` is board-supplied *data*, a board
entry listing `tests/test_config.py` made exactly that legal. The reference
board did list it, and the log confirms both test files were written.

The policy is a **baseline freeze**, not a blanket ban:

| | |
|---|---|
| Protected | `tests/**`, `conftest.py` at any depth, `pytest.ini`, `pyproject.toml`, `tox.ini`, `setup.cfg` |
| Denied | a protected path that existed when the task started |
| Allowed | a **new** file under `tests/**` — tests-first is untouched |
| Opt-out | `TaskSpec.allow_test_edits` (default `false`) |

Enforced in `patcher.apply_diff`, because that is the single funnel every write
passes through — including the divergence winner re-apply, which snapshots the
touched paths but never ran the scope guard. Also pre-checked in the
orchestrator so the Builder gets an actionable rejection instead of a patch
failure, and filtered in the Kaggle pack and the IntegrationAgent so an
unwritable target never reaches a board. Refusals log
`test_integrity_violation`.

Covered attacks: weakening an assertion, deleting a test, a
`pytest_collection_modifyitems` hook that deselects the real tests, and
`addopts` smuggled through `pyproject.toml`.

### 2. Board durability

`_load_board` used to return `{"tasks": []}` on a read failure. Two callers
then wrote that placeholder back, so any transient error — a torn read from a
non-atomic writer, an AV/indexer file lock — silently **erased the whole
backlog**. The IntegrationAgent's board write was the non-atomic writer causing
those torn reads. Now: reads return `Optional` and retry, nothing persists a
board it failed to read, and every writer shares
`redaction.write_json_atomic`.

### 3. Steering telemetry replaces pattern memory (`steering.py`)

The old "learning" layer recorded which signatures had once been fixed and
injected a copy of `task.objective` into the Builder on attempt 3. It did not
learn: the injected text was already delivered in `<<<TASK_JSON>>>` on every
attempt; the confidence *decay* was unreachable (zero events in 36,646 log
lines) because `workspace_patterns_referenced` was empty everywhere; and the
30-day TTL was applied on **read**, so querying memory deleted records — 11 of
23 were already gone.

Replaced by counters, with no LLM anywhere:

| Signal | Fires when |
|---|---|
| `doom_loop` | N consecutive failures sharing a signature token, or the same diff emitted twice for one task |
| `stall` | cycles with no net board change |
| `structural_block` | the pending set is deadlocked, or ≥3 escalations share a *normalised* failure shape |
| `burn_rate` | per-task or per-project resource burn |

Clustering is by **normalised** signature (`ERR_SCHEMA_T-1_MAPPING` and
`T-2` collapse; `ERR_UNIQUE0_THING` and `ERR_UNIQUE1_THING` do not) — matching
on shared tokens produced both false positives and false negatives. State
persists to `.system/steering_state.json`, because the reference run launched
the orchestrator 86 times for 101 tasks.

### 4. ~~The Council~~ — deleted in v2.9

The Council read total context and decided what happened to the **process**. It
was the most expensive prompt in the system, and over a full six-module build it
produced 47 arbiter failures, 9 decisions held for a human, and **not one
intervention that actually repaired anything**.

The one thing it was genuinely good for was *stopping a doomed run*, and that
needs no model at all — so it survives as the **circuit breaker** in
`SuperOrchestrator._check_breaker`: a project that has completed zero tasks
while spending more than `BREAKER_TOKENS_PER_WINDOW` gets a `pause.flag` and a
`breaker_tripped` log row carrying the evidence. Counters, no inference.

The board-write whitelist the Council's actions were bound by is **kept**, in
`validation.BOARD_WRITE_ALLOWLIST`, because escalation diagnosis now applies two
of the same remedies from a model that also produced the failing task. Same
boundary, for the same reason: an automated remedy confined to named board keys
cannot rewrite a backlog.

### 5. Independence, bounds and observability

- **Auditing independence** — a role that judges Builder output is excluded from
  the Builder's model **and its model family**. In the reference run the Reviewer
  reviewed the Builder's work with the *same* free-tier model in 64 of 65 live
  calls, which made the review an echo; when no independent model is available
  the collapse is logged and recorded, never silent.

  v2.9 fixed three ways this rule was not doing what it claimed:

  1. **Membership was `role.startswith("reviewer")`.** v2.9 added `spec_critic`
     and `diagnosis`, both of which judge Builder output, and both were silently
     opted out. Membership is now the explicit `agent_roles.AUDITING_ROLES`.
     Enumerating has its own cost — `reviewer_experiment` had been covered
     implicitly and had to be named — so a test asserts every key
     `resolve_role("reviewer", …)` can return is in the set.
  2. **Exclusion was by exact id**, which a rename defeats: excluding
     `anthropic/claude-sonnet-5` still leaves `anthropic/claude-opus-4`. Family
     matching closes that, and `model_family()` handles the two cases a naive
     split gets wrong — `@cf/` is a routing prefix, and OpenRouter resells five
     vendors, so its family must come from the model id or the whole provider is
     excluded as one blob.
  3. **The role table contradicted itself.** `reviewer_bugfix` and `diagnosis`
     were both configured on the Builder's own model, so under
     `FREE_MODEL_ROUTING=false` both audits were echoes.

  Measured against the live roster: a Builder that used three families leaves
  **29 of 31** reviewer-capable models — real filtering, not starvation. A
  Builder on a free model filters 2–4. A Builder on a *premium* model filters
  **nothing**, because no anthropic model exists in the free roster; that is
  correct rather than broken, but it does mean the rule is inert until the
  Builder actually runs free, which is the default under `FREE_MODEL_ROUTING`.
- **Hard call ceiling** — `asyncio.wait_for` only *requests* cancellation and
  then waits for the SDK to unwind; 8 successful calls logged up to 1614 s
  against a 360 s budget. Since all agents share one event loop, an overrun
  stalled the whole orchestrator. Provider calls now run as their own task and
  are abandoned at the budget.
- **Real token accounting** — `llm_usage` records the SDK's own figures. The
  quota governor had been gating on a character-count estimate that ignored
  completions entirely.
- **Node-level tests-first gate** — `passed` before/after is one integer and
  cannot see a deleted test. The gate now diffs collected node IDs and rejects
  a suite that shrank or did not grow.
- **Log hygiene** — pause state transitions are logged instead of every 2 s
  poll (that one line was 31,468 rows, 86% of the log); `llm_cache_hit` moved
  above DEBUG so cache behaviour is measurable; the log `message` field is
  redacted like `data` already was.
- **Shell-free objective runs** — `run_objective` no longer passes a
  board-authored string to `shell=True`, and `env_autoheal` refuses editable /
  VCS / URL requirements.
- **`AGENTS_NO_DOTENV=1`** — set by the test suite so importing `config` never
  loads `.env`. Tests used to run with live provider keys in the environment,
  which is how a real key once reached a committed test file.

## Secrets and egress

The system reads credentials (`.env`, `projects/*/.env`), shells out with
them in the environment, and sends project source to third-party model
providers. `redaction.py` is the single module responsible for keeping
credentials out of all three.

Two primitives, deliberately separate:

* **`redact_known_secrets(text)`** replaces the **literal values of secrets this
  process holds** (env vars whose *name* contains `KEY`/`SECRET`/`TOKEN`/
  `PASSWORD`/`CREDENTIAL`, read from `os.environ` and the `.env` files). It
  cannot produce a false positive, so it is applied unconditionally at every
  sink: the JSONL log, `llm_exchange` heads, outbound prompts, pattern/anti-
  pattern memory, the LLM cache, divergence candidate archives and Kaggle
  submission payloads. The *identifier* survives — `os.getenv("ALPACA_API_KEY")`
  reviews normally, so the Reviewer is not blinded on credential-handling code.
* **`scan_secrets(text)`** only *detects* credential-shaped patterns
  (`sk-…`, `ghp_…`, `AKIA…`, `AIza…`, private-key blocks, JWTs, and provider
  **account** ids such as `user_…`). It never mutates text; it **gates egress**,
  where a false positive costs one withheld submission and a false negative
  publishes a live key.

Applied at:

| Boundary | Behavior |
|---|---|
| JSONL log | `logger._safe_data` redacts every payload (all ~90 call sites) |
| `llm_exchange` | prompt/response heads redacted before writing |
| Outbound prompts | `LLMClient.complete` — one choke point for every agent call |
| Shared memory | `SharedWorkspaceEngine._write_json` — where a leaked provider account id previously persisted and was replayed into every later prompt |
| LLM cache / divergence archive | responses and candidate diffs redacted on write |
| **Kaggle submit** | **hard fail-closed gate** in `executors.run_kaggle_submit`, before `subprocess.run` |
| Diff write path | `.env`, `*.pem`, `id_rsa`, `kaggle.json`, credential-named files are not writable (`patcher.path_is_denied`); the scope guard now refuses **before** `apply_diff` touches disk |

Operator commands:

```powershell
python main.py --preflight scan     # walk the tree; exit 1 on findings (run before every commit)
python main.py --preflight paths    # which variables count as live secrets (names only)
python main.py --preflight scrub    # dry run: what would be cleaned from shared memory
python main.py --preflight scrub --apply   # writes, with a timestamped .bak- backup first
```

Findings never contain the matched value — only a `sha256(value)[:8]` *hint*,
so repeated hits on one secret correlate without any of it being readable.

Two additional gates protect Kaggle specifically: an LLM-authored
`target_files` list is filtered through `patcher.resolve_target` (it decides
what the Builder may write, so it must not be able to name `.env`), and
`run_command` must be a plain `python`/`py` invocation with no chaining,
substitution or redirection — `env > reports/metrics.json` would otherwise
satisfy the objective gate and ship every credential to the competition.
Escape hatch: `KAGGLE_ALLOW_ARBITRARY_RUN_COMMAND=true`.

`.gitignore` excludes `.env`, `projects/*/data/raw/`, `submissions/` and
private-key material. Verify with `--preflight scan` before the first push.

## Known limitations

Current state after the v2.8 pass. Remaining trade-offs, all deliberate:

1. **The append-only log was not rewritten** — `--preflight scrub` cleaned
   `anti_patterns.json` (which was *re-injecting* a provider account id into
   every later prompt), but the 48 historical occurrences in
   `logs/agent_log.jsonl` and 8 in a project's `review_history.log` remain.
   Neither is a prompt source, so the risk is local-only; both are reachable
   by adding them to `SECRET_SCRUB_TARGETS`. **A leaked provider account id
   cannot be un-leaked** — it already reached third-party providers before
   this pass, so rotating that key is the only real remedy.
2. **A new test's *assertions* are not checked for meaningfulness** — the
   tests-first gate proves the suite grew and nothing pre-existing was
   removed, and `test_integrity` proves no existing test was rewritten. It
   cannot tell a substantive new test from `assert True`. That needs mutation
   testing, which the system does not have.
3. **Auditing independence is best-effort, and measurably so.**
   `REVIEWER_MODEL_EXCLUSION` keeps every role in `AUDITING_ROLES` off the
   Builder's exact ids and its family when the router offers an alternative.
   Under free-tier pressure only one family may be healthy, in which case the
   exclusion is given up and `reviewer_independence_unavailable` is logged, with
   `spec_critic_done.judgement_independent` recording whether that call actually
   ran degraded.

   Two limits worth stating plainly. First, an audit remains an LLM judging an
   LLM even when the exclusion holds — what v2.8 and v2.9 remove is the *silent*
   collapse, not the category. Second, the rule is inert when the Builder runs a
   premium model, because no model of that family sits in the free roster to be
   excluded; it only bites once the Builder is routed free, which is the default.

   The mitigating factor is that the Spec Critic's **deterministic tier is not a
   model** and cannot be collapsed at all — which is why it, and not the model
   pass, is what carries the load.
4. **The system now writes the contract its own Builder is graded against.**
   This is the honest new limit and it deserves stating plainly. The Spec Author
   produces the test; `TestIntegrityGuard` then freezes that test so the Builder
   cannot edit it; and the Spec Critic is the *only* independent check between
   the two. It is a check, not a guarantee — and it is a single model pass, so a
   confident and wrong Critic is possible. Mitigations: the deterministic tier
   needs no model and cannot be talked out of its findings, `high` severity only
   is blocking, and a human can always edit an authored test directly. What this
   buys is that the ambiguity which caused every escalation in the reference
   build is now *typed* by the system rather than by you.
5. **An authored test can be wrong, and the Builder cannot fix it.** This is the
   sharp edge of the previous item. `TestIntegrityGuard` freezes the authored
   test, which is exactly what stops the Builder from quietly rewriting its own
   grader — but it also means a *wrong* authored test is unfixable by the agent
   that has to satisfy it. The Critic is the only thing standing in the way, it
   is one model pass, and its deterministic tier covers the mechanical classes
   (unresolvable imports, declared-vs-used return types) rather than the
   semantic ones. The first run of this against a real goal is a dry run:
   `SPEC_AUTHOR_WRITE_TESTS=false` plus `--author-plan`.
6. **Escalation diagnosis is not independent evidence** — the diagnosing model
   usually also participated in the work that failed, and `AUDITING_ROLES`
   excludes the Builder's family rather than the Builder's *exact* model, so a
   shared vendor still counts as related but a shared lineage across vendors
   does not. `DIAGNOSIS_MIN_CONFIDENCE` and the two-remedy whitelist bound the
   damage and everything else is advice, but a wrong diagnosis at high confidence
   can still narrow an objective it should have left alone.
7. **Secret *values* are matched exactly** — a credential typed by hand into a
   file that differs from the configured value (typo, truncation, a different
   environment) is not redacted at sinks. It *is* caught by the egress gates,
   which run pattern detection too.
8. **`allow_test_edits` is trusted** — a task that sets it can rewrite its own
   grader. Only the bootstrap task that *creates* the harness should, and only
   one board entry currently does.
9. **Anti-pattern merge summarizes history** — per-occurrence records are
   folded into a single `occurrences` count with the newest description /
   strongest severity; verbatim per-escalation history lives in
   `review_history.log` instead.
10. **Dependent-project checks run the dependent's whole suite** — a
    pre-existing red suite in a dependent project is reported as a conflict
    (fail-closed) even when the changed modules are unrelated.
11. **Repetitive single-line hunk contexts anchor to the nearest
    occurrence** — unique multi-line contexts anchor exactly; the residual
    wrong-anchor risk on repetitive single-line context is bounded by the
    real-test gate + rollback.
12. **Lines are partitioned and published, not yet run concurrently.**
    `LINE_COUNT=1` is the default and the scheduler remains strictly sequential
    within a project; what v2.9 adds is that the conflict-free partition is
    computed, validated and shown in the manifest, so the opportunity is
    measured before anything is risked. Cross-*project* concurrency has always
    existed. Running two lines at once also needs per-line Builder instances —
    `BuilderAgent._history` is mutable, so the single instance cannot be shared.

## .env configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | *(empty)* | Empty ⇒ DEMO_MODE (offline) |
| `MODEL_OVERRIDES` | *(empty)* | JSON role→model overrides, e.g. `{"builder_initial": "deepseek/deepseek-chat-v3.1"}` — covers `builder_escalate` too |
| `ENABLE_INTEGRATION_AGENT` | `true` | Cross-project conflict agent |
| `CACHE_ENABLED` | `true` | Provider prompt caching annotations |
| `DEMO_MODE` | `auto` | `auto` = on when no API key; or `true`/`false` |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `CONSOLE_ECHO` | `true` | Compact colored event lines in the console (JSONL always written) |
| `REAL_EXECUTION` | `true` | Live mode: apply diffs + gate on real pytest (never in demo) |
| `CONTENT_MODE` | `true` | Tests-first tasks build from complete-file fences (not diffs) |
| `CONTENT_PER_FILE` | `true` | Multi-file tasks: one focused request per target file |
| `ONCE_BUDGET_S` | `600` | Budget (seconds) for the `--once` single-pass window; a warning logs if pending tasks remain |
| `LLM_CALL_TIMEOUT_S` | `360` | Wall-clock budget per LLM candidate call; empty replies walk the fallback chain |
| `FAILED_RETRY_COOLDOWN_S` | `600` | Cooldown before an escalated task is auto-requeued once |
| `FAILED_AUTO_REQUEUES` | `1` | Max auto-requeues per failed task (0 disables); operator `retry` resets the budget |
| `ENV_AUTOHEAL_ENABLED` | `true` | Auto-`pip install -r requirements.txt` on missing imports, once per task, then re-run the gate |
| `PIP_TIMEOUT_S` | `300` | Subprocess timeout for the self-heal pip install |
| `FREE_MODEL_ROUTING` | `true` | v2.6: route via the free multi-provider capacity layer; `false` = legacy static routing |
| `FREE_MODELS_ALLOW_PAID_FALLBACK` | `false` | Allow the paid static fallback when free capacity is exhausted |
| `LLM_CACHE_ENABLED` | `true` | Exact-match response cache (dedupes identical calls) |
| `OBJECTIVE_TIMEOUT_S` | `1800` | Objective-gate (experiment/benchmark) subprocess timeout |
| `DIVERGENCE_ENABLED` | `false` | Global divergence default (task/board opt-in wins) |
| `PLAN_DIVERGENCE` | `false` | Plan lenses merged deterministically before building |
| `KAGGLE_AUTO_SUBMIT` | `false` | CV-gated auto-submission (Kaggle-pack projects only) |
| `CAMPAIGN_AUTO_GENERATE` | `false` | Campaign director proposes queued experiments at starvation |
| `CAMPAIGN_DIRECTOR_ENABLED` | `false` | LLM campaign director generates new hypotheses from results |
| `REDACTION_ENABLED` | `true` | Blank live secret values at every sink (log, prompts, caches, memory) |
| `SECRET_SCAN_ENABLED` | `true` | Credential-pattern detection for egress gating (`--preflight`, Kaggle submit) |
| `SECRET_SCAN_MIN_LEN` | `8` | Minimum length for an env value to count as a redactable secret |
| `SECRET_SCRUB_TARGETS` | anti+pattern memory | JSON files `--preflight scrub` inspects |
| `KAGGLE_ALLOW_ARBITRARY_RUN_COMMAND` | `false` | Allow an arbitrary shell string as an experiment `run_command` |
| `BREAKER_ENABLED` | `true` | Circuit breaker: pause a project that spends quota with zero completions |
| `BREAKER_TOKENS_PER_WINDOW` | `250000` | Tokens a project may spend with 0 tasks done before the breaker pauses it (0 disables) |
| `SPEC_CRITIC_ENABLED` | `true` | Run the deterministic objective-vs-tests checks before scheduling a task (free) |
| `SPEC_CRITIC_LLM_ENABLED` | `true` | Also spend one model call per task on the Critic's own judgement pass |
| `SPEC_CRITIC_MAX_SOURCE_CHARS` | `24000` | Cap on test source sent to the Critic; generous on purpose |
| `SPEC_AUTHOR_ENABLED` | `true` | Let the system author a tests-first board from a project's `goal.txt` |
| `SPEC_AUTHOR_MAX_TASKS` | `8` | Cap on authored tasks per goal |
| `SPEC_AUTHOR_WRITE_TESTS` | `false`→`true` | Write authored tests to disk. Set false for a readable dry-run plan first |
| `DIAGNOSIS_ENABLED` | `true` | Diagnose escalated tasks (one model call each) |
| `DIAGNOSIS_MIN_CONFIDENCE` | `0.6` | Below this a remedy is recorded as advice, never applied |
| `LINE_CONTINUITY` | `true` | Carry a bounded summary of completed tasks into the next task's prompt |
| `LINE_NOTE_LIMIT` | `6` | How many finished tasks to keep in that summary |
| `LINE_COUNT` | `1` | Independent lines per project. 1 = pre-v2.9 sequential behaviour |
| `RPM_SELF_TUNING` | `true` | Learn each provider's real RPM from its 429s instead of trusting the constant |
| `RPM_RATCHET_DOWN` | `0.7` | Multiplier applied on each observed 429 |
| `RPM_LEARNED_FLOOR` | `4` | Never ratchet below this |
| `RPM_RECOVER_AFTER_CLEAN` | `40` | Consecutive clean calls before a learned limit recovers |
| `REVIEWER_MODEL_EXCLUSION` | `true` | Keep every role in `AUDITING_ROLES` off the Builder's model ids **and** its family. Collapses are logged, never silent |
| `AGENTS_NO_DOTENV` | unset | Set to `1` to import `config` **without** loading `.env` (the test suite does) |

## Structured logging

All events are appended as JSON lines to `logs/agent_log.jsonl`:

```json
{"ts": "2026-08-30T10:15:30.123Z", "level": "INFO", "message": "task_completed",
 "data": {"project": "project_alpha", "task_id": "TASK-1001", "attempts": 1}}
```

Significant events logged: task start/complete/fail/escalate, retry,
integration notify/suspected/tests, orchestrator spawn/restart/crash, pause,
pattern promotion/decay, LLM fallbacks, and **`llm_exchange`** — one entry
per model call with role, model, duration and bounded prompt/response heads
(this is what the dashboard's event feed renders as the agents' visible
"thought process"). The only other console output is the argparse CLI help
and the opt-out-able `CONSOLE_ECHO` lines from the logger.

**Every payload is redacted before it is written** (`logger._safe_data` →
`redaction.redact_obj`), so a credential that reaches a log call site — a
provider exception body, a pytest output tail, a model response head — is
blanked rather than persisted. Disable with `REDACTION_ENABLED=false` while
debugging a suspected false positive.

Security-relevant events added in v2.7: `kaggle_submission_blocked_secrets`,
`secrets_scrub_completed`, `campaign_target_file_rejected`,
`campaign_run_command_rejected`. None of them ever carries the offending
value — only rule names and `sha256` hints.

## Workspace layout

```
workspace/
├── PROJECT_ONBOARDING.md  operator's playbook for the coding agent
├── .gitignore             excludes .env, raw data, submissions, key material
├── .env                   LIVE CREDENTIALS -- never commit (gitignored)
├── .system/            manifest.json, global_rules.md, rate_limits.json,
│                       llm_cache/
├── .shared_workspace/  pattern_memory.json, anti_patterns.json,
│                       canonical_rules.md, draft_logs/
├── projects/
│   ├── project_alpha/  .agent/ (task_board.json, context.md,
│   │                   review_history.log, cycle_summary.json), src/, tests/
│   ├── project_beta/   (same layout)
│   └── project_main/   real-world example: AI stock trading system
│                       (complete: 20 tasks, wiring closed end-to-end,
│                       113 offline tests green — CLI scan and the smoke
│                       runner delegate to the pipeline with the SQLite
│                       decision audit restored on every path)
└── logs/               agent_log.jsonl
```

`config.ensure_workspace()` bootstraps the core tree idempotently — existing
state is never overwritten on re-runs. `--new-project` adds user projects.
