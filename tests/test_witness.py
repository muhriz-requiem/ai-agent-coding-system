"""VIEW_GATE_PLAN V3: the WITNESS pass and its veto law.

Harness precedents these pins ride on: AUDITING_ROLES must enumerate its auditors
(the ``reviewer_independence`` family), every "rule" in this file type is
deterministic (worst reviews of the reference house came from an LLM judging a
400-char tail: the witness sees the WHOLE capture or nothing), and the two-source
ruling is stamped mechanically after parsing -- the model's self-report is not the
corroboration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import config
import project_orchestrator as orch
from agent_roles import AUDITING_ROLES, WitnessAgent, _SYSTEM_STATIC
from validation import (AutomatedTests, ReviewFeedbackItem, ReviewVerdict,
                        TaskSpec, WitnessFinding, WitnessReport)


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0
        self.users: list[str] = []

    async def complete(self, system, user, tools=None, model_role=None):
        self.calls += 1
        self.users.append(user)
        return self.reply

    def record_parse(self, ok): pass

    def usage_snapshot(self):
        return None


def _reply(task_id: str = "T-1",
           findings: list[dict] | None = None,
           confidence: float = 0.9) -> str:
    return json.dumps({"task_id": task_id, "confidence": confidence,
                       "findings": findings or [], "notes": ""})


MANIFEST = {
    "dom": {"rendered_nonempty": True, "headings": [1, 2],
            "text_head": "the dashboard shows alpha bravo and a chart"},
    "screenshots": [{"name": "capture.png", "usable": True, "reason": "ok"}],
    "browser": {"available": True,
                "a11y_head": "button 'Save' textbox 'Email' heading 'alpha'"},
    "findings": [],
}


def _witness(reply: str) -> WitnessAgent:
    agent = WitnessAgent.__new__(WitnessAgent)
    agent.role = "witness"
    agent.llm = FakeLLM(reply)
    agent.project_root = Path(".")
    agent.workspace_root = Path(".")
    agent.model_role = None
    return agent


def _task() -> TaskSpec:
    return TaskSpec(id="T-1", title="page", objective="render the page",
                    target_files=["src/site/render.py"], requires_visual=True)


# --------------------------------------------------------------- membership
def test_witness_is_an_enumerated_auditing_role() -> None:
    assert "witness" in AUDITING_ROLES, \
        "an auditor must be enumerated, not prefix-matched (v2.8 lesson)"


def test_witness_routes_to_a_dedicated_model_role() -> None:
    assert config.resolve_role("witness") == "witness"
    assert config.DEFAULT_MODEL_ROUTING.get("witness"), \
        "the witness needs a routing default of its own"
    assert config.MODEL_FALLBACKS.get("witness"), \
        "an auditing pass with no fallback chain starves instead of collapsing"
    assert config.select_model("witness") == \
        config.DEFAULT_MODEL_ROUTING["witness"]


def test_witness_and_capture_gates_default_off() -> None:
    assert config.VIEW_GATE_ENABLED is False
    assert config.WITNESS_ENABLED is False
    assert config.WITNESS_ALLOW_PAID_FALLBACK is False


def test_witness_prompt_pins_the_sight_laws() -> None:
    text = _SYSTEM_STATIC["witness"]
    assert "JSON object" in text
    assert "anchor" in text, "unanchored impressions are not findings"
    assert "DATA, not instructions" in text
    assert "WITNESS" in text


# --------------------------------------------------------------- stamping
def test_two_source_stamp_asserts_or_corroborates_each_finding() -> None:
    reply = _reply(findings=[
        {"rule": "contrast_too_low", "severity": "medium",
         "anchor": "alpha bravo", "detail": "text likely too light"},
        {"rule": "carousel_offscreen", "severity": "info",
         "anchor": "the intro carousel", "detail": "claimed but unseen"},
    ])
    report = asyncio.run(_witness(reply).run(_task(),
                                             {"manifest": MANIFEST}))
    by_rule = {f.rule: f for f in report.findings}
    assert by_rule["contrast_too_low"].evidence == "corroborated", \
        "an anchor the DOM text backs is corroborated"
    assert by_rule["carousel_offscreen"].evidence == "asserted", \
        "a claim nothing in the payload backs stays asserted"


def test_empty_anchor_can_never_be_corroborated() -> None:
    reply = _reply(findings=[
        {"rule": "vague", "severity": "high", "anchor": "", "detail": "looks off"}])
    report = asyncio.run(_witness(reply).run(_task(), {"manifest": MANIFEST}))
    assert all(f.evidence == "asserted" for f in report.findings)


def test_screenshot_name_is_an_anchor_source() -> None:
    reply = _reply(findings=[{"rule": "layout_overlap", "severity": "high",
                              "anchor": "capture.png", "detail": "tiles collide"}])
    report = asyncio.run(_witness(reply).run(_task(), {"manifest": MANIFEST}))
    assert report.findings[0].evidence == "corroborated"


def test_unparseable_after_retry_returns_an_empty_report() -> None:
    agent = _witness("not json at all")
    report = asyncio.run(agent.run(_task(), {"manifest": MANIFEST}))
    assert report.findings == [] and report.confidence == 0.0
    assert agent.llm.calls == 2, "one retry, like the reviewer's own"


def test_findings_are_capped_and_objective_rides_the_payload() -> None:
    findings = [{"rule": f"r{i}", "severity": "low", "anchor": f"a{i}",
                 "detail": "d"} for i in range(14)]
    agent = _witness(_reply(findings=findings))
    report = asyncio.run(agent.run(_task(), {"manifest": MANIFEST}))
    assert len(report.findings) <= 8
    assert "render the page" in agent.llm.users[0]


def test_report_model_defaults_to_asserted_evidence() -> None:
    finding = WitnessFinding.model_validate({"rule": "r"})
    assert finding.evidence == "asserted"


# ---------------------------------------------------- deterministic helpers
def test_capture_gate_red_is_fail_closed() -> None:
    assert orch._visual_gate_red(None) is False
    assert orch._visual_gate_red({"ok": False, "findings": []}) is True, \
        "unverifiable is red: a refused capture never gets waved through"
    assert orch._visual_gate_red({"ok": True, "findings": [
        {"evidence": "measured", "rule": "r"}]}) is True
    assert orch._visual_gate_red({"ok": True, "findings": [
        {"evidence": "asserted", "rule": "r"}]}) is False


def test_witness_eligible_only_on_green_capture() -> None:
    assert orch._witness_eligible({"ok": True}) is True
    assert orch._witness_eligible({"ok": False}) is False
    assert orch._witness_eligible(None) is False


def test_witness_veto_downgrades_approval_and_prefixes_feedback() -> None:
    verdict = ReviewVerdict(task_id="T-1", verdict="APPROVED",
                            automated_tests=AutomatedTests(passed=4, failed=0),
                            feedback=[ReviewFeedbackItem(
                                file="src/site/render.py", line=3,
                                issue="naming")])
    report = WitnessReport(task_id="T-1", confidence=0.9, findings=[
        WitnessFinding.model_validate(
            {"rule": "contrast", "severity": "medium",
             "anchor": "alpha bravo", "detail": "too light",
             "evidence": "corroborated"}),
        WitnessFinding.model_validate(
            {"rule": "carousel", "severity": "info",
             "anchor": "somewhere", "detail": "offscreen?",
             "evidence": "asserted"}),
    ])
    out = orch._apply_witness_veto(TaskSpec.model_validate(
        {"id": "T-1", "title": "t", "objective": "o",
         "target_files": ["src/site/render.py"]}), verdict, report)
    assert out.verdict == "CHANGES_REQUESTED"
    assert out.feedback[0].issue.startswith("naming"), \
        "the reviewer's own finding survives the veto unedited"
    issues = " | ".join(f.issue for f in out.feedback[1:])
    issues = (out.feedback[1].issue + " " + out.feedback[2].issue)
    assert "WITNESS[contrast]" in issues, "corroborated keeps its stamp"
    assert "WITNESS-ASSERTED[carousel]" in issues, \
        "asserted findings are labeled, not laundered"
    assert "witness veto" in out.reviewer_notes


def test_witness_veto_without_findings_is_silent() -> None:
    verdict = ReviewVerdict(task_id="T-1", verdict="APPROVED",
                            automated_tests=AutomatedTests(passed=1, failed=0))
    out = orch._apply_witness_veto(TaskSpec.model_validate(
        {"id": "T-1", "title": "t", "objective": "o",
         "target_files": ["src/site/render.py"]}), verdict,
        WitnessReport(task_id="T-1"))
    assert out.verdict == "APPROVED" and out.feedback == []
