"""VIEW_GATE_PLAN V1: the view contract is checked before a visual task runs.

The failure class this pins: artifacts whose whole point is how they *look*
(slatepress pages, dashboards, rendered reports) are graded only by Python
assertions about the code that produced them.  Nobody ever observed the
artifact, and the loop's instruments cannot even represent the question "but
does it visibly work?".  V1 adds the contract plumbing -- task flags, an
authored expected-view file frozen like tests, and two deterministic critic
findings -- so V2/V3 have something to capture against and something to compare
to.  Everything here is deterministic and offline; the lane's own gates stay
default-OFF (V2/V3), and this file pins that off-state stays silent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import spec_critic
from test_integrity import TestIntegrityGuard, is_protected_path
from validation import TaskSpec


# ================================= full contract layer field set == encoding
def test_task_spec_carries_view_fields() -> None:
    """V1: TaskSpec gains requires_visual / view_command / authored_view_path.

    Pydantic drops unknown kwargs under ``extra="ignore"``, so pins assert on
    the schema itself rather than relying on construction failing loudly.
    """
    for name in ("requires_visual", "view_command", "authored_view_path"):
        assert name in TaskSpec.model_fields, (
            f"TaskSpec.{name} missing: the view lane has nowhere to ride")
    assert TaskSpec.model_fields["requires_visual"].annotation is not None
    # v2.9.1 lesson: Unknown is not false.  A task from a pre-lane board must
    # not be silently enrolled in visual gating, and a visual task must not be
    # silently dropped from it -- None encodes "no signal".
    assert TaskSpec.model_fields["requires_visual"].default is None


def test_all_workspace_boards_validate_with_view_fields_and_stay_default() -> None:
    """Every real board in the workspace parses under the extended schema, and
    the new fields default off there -- the byte-identical-when-off pin, at the
    data level, EXCEPT a task the operator enrolled explicitly.  An enrolled
    task (the V5 canary) must prove it is well-formed: the three fields ride
    together, because half-enrollment schedules a capture that can never run.
    Skips cleanly if the operator moves projects/.
    """
    roots = Path(__file__).resolve().parents[1] / "projects"
    boards = sorted(roots.glob("*/.agent/task_board.json")) if roots.is_dir() else []
    if not boards:
        pytest.skip("no workspace boards visible from the test tree")
    seen = 0
    canary_seen = False
    for board_path in boards:
        data = json.loads(board_path.read_text(encoding="utf-8"))
        for entry in data.get("tasks") or []:
            task = TaskSpec.model_validate(entry)
            if task.requires_visual is None:
                assert task.view_command is None and \
                    task.authored_view_path is None
            else:
                assert task.view_command and task.authored_view_path, (
                    f"{board_path}::{task.id} enrolled but half-formed")
                assert "slatepress" in str(board_path) and task.id == "T-005"
                canary_seen = True
            seen += 1
    assert seen > 0
    assert canary_seen, "the V5 canary enrollment went missing"


# ================================= deterministic critic findings == contract
def _board(tmp_path: Path) -> None:
    (tmp_path / ".agent").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agent" / "task_board.json").write_text(
        json.dumps({"tasks": []}), encoding="utf-8")


def test_visual_task_without_view_command_blocks(tmp_path: Path) -> None:
    """A visual task with no declared way to build its artifact is unschedulable:
    the capture tier would have nothing to run, so the task must say what makes
    the artifact before V2 can ever look at it."""
    _board(tmp_path)
    task = TaskSpec(id="T-1", title="page",
                    objective="render the landing page",
                    target_files=["src/site/render.py"],
                    requires_visual=True)
    kinds = {f.kind: f for f in
             spec_critic.project_structure_findings(task, tmp_path)}
    assert "visual_task_without_view" in kinds
    assert kinds["visual_task_without_view"].severity == "high"


def test_visual_task_with_view_command_is_held_silent(tmp_path: Path) -> None:
    _board(tmp_path)
    task = TaskSpec(id="T-1", title="page",
                    objective="render the landing page",
                    target_files=["src/site/render.py"],
                    requires_visual=True, view_command="python -m sitegen --out .site")
    kinds = [f.kind for f in
             spec_critic.project_structure_findings(task, tmp_path)]
    assert "visual_task_without_view" not in kinds


def test_not_visual_board_stays_silent(tmp_path: Path) -> None:
    """Default-off: every board authored before the lane must produce the
    findings it produced before V1."""
    _board(tmp_path)
    task = TaskSpec(id="T-1", title="lib", objective="sum ints",
                    target_files=["src/lib/math.py"])
    kinds = [f.kind for f in
             spec_critic.project_structure_findings(task, tmp_path)]
    assert not any(k.startswith("view_") or k.startswith("expected_view")
                   for k in kinds)


def test_expected_view_without_any_assertion_is_unverifiable(tmp_path: Path) -> None:
    """An authored expected view with nothing machine-checkable in it would
    freeze a rubric the capture tier cannot apply -- the "assert True" class,
    one plane up, caught at authoring time rather than at grading time."""
    _board(tmp_path)
    view_dir = tmp_path / "expected_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    (view_dir / "T-1.json").write_text(
        json.dumps({"view_command": "python -m sitegen --out .site"}),
        encoding="utf-8")
    task = TaskSpec(id="T-1", title="page", objective="render the landing page",
                    target_files=["src/site/render.py"],
                    requires_visual=True, view_command="python -m sitegen --out .site",
                    authored_view_path="expected_views/T-1.json")
    kinds = {f.kind: f for f in
             spec_critic.project_structure_findings(task, tmp_path)}
    assert "view_contract_unverifiable" in kinds
    assert kinds["view_contract_unverifiable"].severity == "medium"


def test_expected_view_with_assertions_is_silent(tmp_path: Path) -> None:
    _board(tmp_path)
    view_dir = tmp_path / "expected_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    (view_dir / "T-1.json").write_text(
        json.dumps({"view_command": "python -m sitegen --out .site",
                    "must_contain": ["<main>"],
                    "dom_asserts": [{"type": "headings_ascending"}]}),
        encoding="utf-8")
    task = TaskSpec(id="T-1", title="page", objective="render the landing page",
                    target_files=["src/site/render.py"],
                    requires_visual=True, view_command="python -m sitegen --out .site",
                    authored_view_path="expected_views/T-1.json")
    kinds = {f.kind: f for f in
             spec_critic.project_structure_findings(task, tmp_path)}
    assert "view_contract_unverifiable" not in kinds
    assert "expected_view_missing" not in kinds


def test_expected_view_declared_but_absent_is_a_low_finding(tmp_path: Path) -> None:
    """Mirrors ``target_test_missing``: a task may reference a view whose file
    does not exist YET (authored-then-frozen ordering); that is worth surfacing
    at low severity, never worth blocking like an empty contract."""
    _board(tmp_path)
    task = TaskSpec(id="T-1", title="page", objective="render the landing page",
                    target_files=["src/site/render.py"],
                    requires_visual=True, view_command="python -m sitegen --out .site",
                    authored_view_path="expected_views/T-1.json")
    kinds = {f.kind: f for f in
             spec_critic.project_structure_findings(task, tmp_path)}
    assert "expected_view_missing" in kinds
    assert kinds["expected_view_missing"].severity == "low"


# ================================= expected_views joins the frozen apparatus ==
def test_expected_views_dir_is_protected_by_path_shape() -> None:
    """The freeze is decided on path shape alone (test_integrity law): the
    artifact's grading rubric must be un-writable by the task being graded."""
    assert is_protected_path("expected_views/T-1.json")
    assert is_protected_path("expected_views/sub/deep/T-9.json")
    assert not is_protected_path("src/site/render.py")


def test_freeze_blocks_editing_an_existing_expected_view(tmp_path: Path) -> None:
    view_dir = tmp_path / "expected_views"
    view_dir.mkdir(parents=True, exist_ok=True)
    path = view_dir / "T-1.json"
    path.write_text(json.dumps({"must_contain": ["<main>"]}), encoding="utf-8")
    guard = TestIntegrityGuard.capture(tmp_path)
    assert len(guard) > 0, "expected_views/T-1.json must be baselined"
    assert not guard.check(["expected_views/T-1.json"])
    path.write_text(json.dumps({"must_contain": []}), encoding="utf-8")
    assert not guard.unchanged("expected_views/T-1.json"), \
        "rewriting the rubric must be detected as a violation"


def test_expected_view_authored_after_task_start_stays_writable() -> None:
    """"Frozen *at task start*, not forever: the authoring step happens before
    the task exists, and new files are still authorable once it does."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        guard = TestIntegrityGuard.capture(root)
        (root / "expected_views").mkdir(parents=True, exist_ok=True)
        (root / "expected_views" / "T-1.json").write_text("{}", encoding="utf-8")
        assert guard.check(["expected_views/T-1.json"]), \
            "tests-first, views-first: authoring new contract files is not the threat"
