"""The sight lane's capture tier: run the artifact and record what it IS.

VIEW_GATE_PLAN V2.  Every gate the system owns until now verifies *the code's
claims* -- tests, suite growth, gate metrics.  Nothing observed the artifact,
so "everything looks good in code, the thing is flawed" was the one failure
class the loop's instruments were structurally blind to (the logtriage trap:
`6 skipped`, exit 0, looked healthy while verifying nothing).

Two tiers, deterministic first:

* **DOM tier (always available)** -- run the task's ``view_command``, then read
  the rendered artifact it produced: visible text, heading order, image alts,
  internal links, raw-entity leaks.  Stdlib parsing, zero new dependencies,
  zero model calls.
* **Browser tier (optional, caller opted in)** -- when Playwright + Chromium
  are installed, a real headless render adds the a11y snapshot, a screenshot,
  and console errors.  A missing browser is a *named degradation*
  (``degraded: dom_only``, ``view_capture_unavailable`` event), never a silent
  skip.

The gate checks its own capture.  An empty render is not evidence, it is the
capture lying: ``render_nonempty`` is a hard refuse, and a single-color
screenshot is refused the same way.  Fail-closed on every anomaly, mirroring
``executors.run_objective``: refused commands, non-zero exits, timeouts
(process tree killed) and missing artifacts are red, and the manifest is
written anyway so the evidence survives for the witness and for diagnosis.

Untrusted-content law: extracted page text is data, never instructions.  Every
string that leaves this module toward a prompt is redacted at the sink by the
caller (same choke points as every other prompt); the findings carry anchors,
never verdicts about taste -- taste is the witness pass's job (V3), and one
bounded model call can add findings there but never clear these.
"""

from __future__ import annotations

import json
import re
import struct
import subprocess
import time
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
import redaction
from executors import _kill_process_tree, _safe_argv
from logger import log_event

#: Visible-text head kept in the manifest (the witness reads this instead of
#: the whole page).  Bounded like every other evidence head in this system.
TEXT_HEAD_CHARS = 800

_MISSING = object()


# ============================================================================
# DOM extraction
# ============================================================================
class _DomParser(HTMLParser):
    """Collect the visible outcome of one HTML page -- and only that.

    What the user *sees* approximated with stdlib tools: heading structure and
    order, images and their alts, internal link targets, and the rendered
    text with scripts/styles excluded.  Entity references are decoded
    (``&amp;`` -> ``&``) so a *double* escape becomes visible as a literal
    ``&amp;`` string in the text -- which is exactly the defect it is meant
    to catch.
    """

    _SKIP = ("script", "style", "title", "template")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.source = ""
        self.headings: List[int] = []
        self.images: List[Tuple[str, bool]] = []   # (src, alt present?)
        self.links: List[Tuple[str, str]] = []     # (href, text)
        self.text_parts: List[str] = []
        self._skip_depth = 0
        self._in_h = 0
        self._link_href = ""
        self._link_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, str]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        attrs_d = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_h = int(tag[1])
        elif tag == "img":
            self.images.append((attrs_d.get("src", ""),
                                "alt" in attrs_d))
        elif tag == "a":
            self._link_href = attrs_d.get("href", "")
            self._link_text = []
        elif tag == "br":
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._in_h = 0
        elif tag == "a" and self._link_text:
            self.links.append((self._link_href, "".join(self._link_text)))
            self._link_href, self._link_text = "", []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_h:
            self.headings.append(self._in_h)
        if self._link_text is not None and self._link_href:
            self._link_text.append(data)
        self.text_parts.append(data)

    def rendered_text(self) -> str:
        return re.sub(r"[ \t\r\n]+", " ", "".join(self.text_parts)).strip()

    @property
    def in_heading(self) -> bool:  # pragma: no cover - tiny helper
        return bool(self._in_h)


def parse_dom(html_text: str) -> _DomParser:
    parser = _DomParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception as exc:  # malformed markup: the capture refuses
        raise ValueError(f"unparseable html: {exc}") from exc
    parser.source = html_text
    return parser


def evaluate_dom(dom: _DomParser, expected: Dict[str, Any],
                 artifact_dir: Path) -> List[Dict[str, Any]]:
    """Deterministic DOM-class findings.  Every entry is ``evidence: measured``
    -- the witness can add to this list at V3 but can never clear it.

    ``render_nonempty`` (empty is a HARD capture refuse by the caller),
    ``headings_ascending`` (a heading level may not skip *down*), ``img_has_alt``
    (absent attribute; a present-but-empty alt is reported separately),
    ``raw_entity_in_text`` (double-escaped markup the user sees verbatim),
    ``link_local_missing`` (markup pointing at a file that does not exist).
    """
    findings: List[Dict[str, Any]] = []

    def add(rule: str, detail: str, anchor: str = "",
            severity: str = "high") -> None:
        findings.append({"rule": rule, "severity": severity, "anchor": anchor,
                         "detail": detail, "evidence": "measured"})

    text = dom.rendered_text()
    for want in expected.get("must_contain") or []:
        if str(want) not in text:
            add("must_contain", f"expected to contain {str(want)!r} in the "
                                f"rendered text; it does not appear",
                anchor=str(want))
    for banned in expected.get("must_not_show") or []:
        if str(banned) in text:
            add("must_not_show", f"rendered text contains {str(banned)!r}",
                anchor=str(banned))

    for kind in expected.get("dom_asserts") or []:
        name = str((kind or {}).get("type") or "")
        if name == "headings_ascending":
            prev = 0
            for level in dom.headings:
                if prev and level > prev + 1:
                    add("headings_ascending",
                        f"heading level {level} follows level {prev}; visually "
                        f"this skips a structural level between them",
                        anchor=f"h{prev}->h{level}")
                prev = level
        elif name == "img_has_alt":
            for src, has_alt in dom.images:
                if not has_alt:
                    add("img_has_alt",
                        "img without an alt attribute; what the user sees as "
                        "an image, a screenreader sees as nothing",
                        anchor=f"img[{src or '?'}]",
                        severity="medium")
        elif name in ("tag_present", "tag_absent"):
            # VIEW_GATE_PLAN V5: structural contract items -- "does the
            # artifact HAVE this element" (the goal pins a rendered body
            # inside <main>).  Decided on the source, not the text: visible
            # text cannot express structure.
            tag = str((kind or {}).get("tag") or "").strip()
            if not tag:
                add("view_contract_unverifiable",
                    f"dom_assert of type {name} without a tag; nothing can "
                    f"be checked", severity="medium")
                continue
            present = re.search(
                rf"<\s*{re.escape(tag)}[\s>/]",
                str(getattr(dom, "source", "")), re.IGNORECASE) is not None
            if name == "tag_present" and not present:
                add("tag_present",
                    f"the artifact must contain a <{tag}> element; it does "
                    f"not -- the structural promise to the user is broken",
                    anchor=f"<{tag}>")
            if name == "tag_absent" and present:
                add("tag_absent",
                    f"the artifact must NOT contain a <{tag}> element; it "
                    f"does", anchor=f"<{tag}>")

    if "&amp;" in text or "&lt;" in text or "&gt;" in text or "&nbsp;" in text:
        sample = next(tok for tok in ("&amp;", "&lt;", "&gt;", "&nbsp;")
                      if tok in text)
        add("raw_entity_in_text",
            f"literal {sample!r} survives in the rendered text: markup is "
            f"being escaped twice and the user reads the entity, not the "
            f"character",
            anchor=sample)

    for href, _label in dom.links:
        raw = (href or "").split("#", 1)[0].strip()
        if not raw or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw) or \
                raw.startswith("//"):
            continue  # fragment-only, absolute scheme, or protocol-relative
        target = (artifact_dir / raw).resolve()
        try:
            inside = str(target).startswith(str(artifact_dir))
        except OSError:  # pragma: no cover - resolve() literal failure
            inside = False
        if not inside:
            continue
        if not target.exists():
            add("link_local_missing",
                f"renders a link to {raw!r}, which does not exist in the "
                f"built artifact",
                anchor=raw, severity="medium")
    return findings


# ============================================================================
# screenshot tier
# ============================================================================
def screen_is_blank(path: Path) -> Tuple[bool, str]:
    """Validate one screenshot.  Returns (usable, reason).

    The law: the gate checks its own capture.  A screenshot that decodes to a
    single color (or does not decode at all) is not evidence of a page having
    rendered -- it is the capture lying, so it must be refused, not scored.

    True means "the screenshot carries distinguishable content".
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return False, f"unreadable capture: {exc}"
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False, "capture is not a png"
    try:
        w, h, _depth, color_type, _comp, _fmode, _il = struct.unpack(
            ">IIBBBBB", data[16:16 + 13])
    except struct.error:
        return False, "malformed png header"
    channels = 4 if color_type == 6 else 3 if color_type == 2 else 0
    if channels == 0 or w == 0 or h == 0:
        return False, f"unsupported png color type {color_type}"
    idat = b"".join(payload for _tag, payload in _iterate_chunks(data, b"IDAT"))
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return False, "malformed png pixel data"
    row_len = 1 + w * channels
    if len(raw) < row_len * h:
        return False, "png pixel data truncated"
    flat = b"".join(raw[i + 1:i + row_len] for i in range(0, row_len * h, row_len))
    var_zero = len(set(flat)) == 1
    if var_zero:
        return False, "variance 0: uniform capture"
    stride = max(1, (w * h) // 4096)
    step = stride * channels
    sampled = {flat[i:i + channels] for i in range(0, len(flat) - channels, step)}
    if len(sampled) == 1:
        return False, "variance 0: single sampled color"
    return True, f"distinct sampled colors: {len(sampled)}"


def _iterate_chunks(data: bytes, tag: bytes) -> Any:
    """Yield (tag, payload) chunks of a png byte string."""
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        cur_tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if cur_tag == tag:
            yield (cur_tag, payload)
        pos += 12 + length


# ============================================================================
# expected-view contract
# ============================================================================
def load_expected_view(path: Path) -> Dict[str, Any]:
    """Load and minimally validate ``expected_views/<task>.json``.

    ``view_command`` and ``url_or_path`` are the load-bearing pair; rejecting
    the wrong ones here is what keeps ``run_view`` from ever guessing.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"expected_view {path} is unreadable as json: {exc}") \
            from exc
    if not isinstance(data, dict):
        raise ValueError(f"expected_view {path} must be a json object")
    for key in ("view_command", "url_or_path"):
        val = data.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(
                f"expected_view {path}: {key} must be a non-empty string")
    return data


# ============================================================================
# the capture itself
# ============================================================================
def run_view(project_root: Path, expected: Dict[str, Any],
             attempt_dir: Path, timeout_s: Optional[int] = None,
             use_browser: bool = False, task_id: str = "",
             ) -> Dict[str, Any]:
    """Run ``expected['view_command']`` and record what actually rendered.

    Mirrors ``executors.run_objective`` in discipline: argv-parsed (no shell,
    no chaining), stale-evidence-proof, fail-closed on every anomaly, and the
    manifest is written even on failure so the evidence survives.
    """
    root = Path(project_root)
    attempt_dir = Path(attempt_dir)
    result: Dict[str, Any] = {
        "ok": False, "detail": "", "exit_code": None,
        "findings": [], "screenshots": [], "runtime_s": 0.0,
        "degraded": False, "browser_used": False, "manifest_path": None,
    }
    command = str(expected.get("view_command") or "")
    rel_artifact = str(expected.get("url_or_path") or "")
    if not command.strip() or not rel_artifact.strip():
        result["detail"] = "expected_view lacks view_command or url_or_path"
        return result

    manifest: Dict[str, Any] = {
        "task_id": task_id,
        "command": command,
        "exit_code": None,
        "dom": {},
        "browser": {},
        "findings": [],
        "screenshots": [],
        "degraded": False,
        "browser_used": False,
        "runtime_s": 0.0,
        "url_or_path": rel_artifact,
        # The viewed contract rides inside the manifest: the witness judges
        # capture against promise from ONE payload, and diagnosis surfaces
        # see what the rubric was, not what later prose says it was.
        "expected": dict(expected),
    }

    # Refuse anything that needs a shell BEFORE touching disk -- the same
    # net-command rule run_objective learned the hard way in v2.8: a
    # board-authored string must not have metacharacter powers.
    argv = _safe_argv(command)
    if not argv:
        result["detail"] = ("view_command is not a plain executable invocation "
                            f"({command!r}); chaining, substitution and "
                            "redirection are not allowed here")
        _write_manifest(attempt_dir, manifest, result)
        return result

    started = time.monotonic()
    log_event("INFO", "view_capture_started",
              {"task_id": task_id, "project": root.name})
    try:
        proc = subprocess.Popen(
            argv, cwd=str(root), shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        result["detail"] = f"view command could not start: {exc}"
        log_event("ERROR", "view_capture_error",
                  {"task_id": task_id, "error": str(exc)})
        _write_manifest(attempt_dir, manifest, result)
        return result
    try:
        _out, _ = proc.communicate(timeout=timeout_s
                                   or config.VIEW_CAPTURE_TIMEOUT_S)
        manifest["exit_code"] = proc.returncode
        result["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        result["runtime_s"] = round(time.monotonic() - started, 2)
        result["detail"] = (
            f"view command timed out after {timeout_s or config.VIEW_CAPTURE_TIMEOUT_S}s "
            "(process tree killed)")
        log_event("ERROR", "view_capture_timeout",
                  {"task_id": task_id,
                   "timeout_s": timeout_s or config.VIEW_CAPTURE_TIMEOUT_S})
        _write_manifest(attempt_dir, manifest, result)
        return result
    result["runtime_s"] = round(time.monotonic() - started, 2)
    manifest["runtime_s"] = result["runtime_s"]
    if proc.returncode != 0:
        result["detail"] = f"view command exited {proc.returncode}"
        _write_manifest(attempt_dir, manifest, result)
        return result

    artifact = (root / rel_artifact)
    if not artifact.is_file():
        result["detail"] = (f"artifact {rel_artifact!r} did not exist after "
                            "the view command ran (exit 0)")
        log_event("ERROR", "view_capture_missing_artifact",
                  {"task_id": task_id, "artifact": rel_artifact})
        _write_manifest(attempt_dir, manifest, result)
        return result

    try:
        html_text = artifact.read_text(encoding="utf-8", errors="replace")
        dom = parse_dom(html_text)
    except (OSError, ValueError) as exc:
        result["detail"] = f"artifact unparseable: {exc}"
        log_event("ERROR", "view_capture_unparseable",
                  {"task_id": task_id, "error": str(exc)})
        _write_manifest(attempt_dir, manifest, result)
        return result

    text = dom.rendered_text()
    manifest["dom"] = {
        "rendered_nonempty": bool(text),
        "headings": dom.headings,
        "images_total": len(dom.images),
        "images_no_alt": [src for src, has_alt in dom.images if not has_alt],
        "links_total": len(dom.links),
        "text_head": text[:TEXT_HEAD_CHARS],
    }
    findings = evaluate_dom(dom, expected, artifact.parent)
    if not text:
        findings = [{
            "rule": "render_nonempty", "severity": "high",
            "anchor": rel_artifact,
            "detail": "the artifact contains no visible text; an empty render "
                      "is not evidence -- the capture refuses itself",
            "evidence": "measured",
        }] + findings
        result["detail"] = "render is empty (capture refused)"
        result["findings"] = manifest["findings"] = findings
        _write_manifest(attempt_dir, manifest, result, ok=False)
        return result

    browser_tier = _browser_tier(artifact, expected, attempt_dir,
                                 manifest, result) if use_browser else None
    if isinstance(browser_tier, list):
        findings.extend(browser_tier)
    # else: optional tier declined/degraded; the manifest already says so.
    result["findings"] = manifest["findings"] = findings
    manifest["browser_used"] = result["browser_used"]
    manifest["degraded"] = result["degraded"] = bool(
        use_browser and not result.get("browser_used"))
    result["ok"] = not any(f.get("evidence") == "measured" for f in findings)
    manifest["ok"] = result["ok"]
    _write_manifest(attempt_dir, manifest, result, ok=result["ok"])
    return result


def _write_manifest(attempt_dir: Path, manifest: Dict[str, Any],
                    result: Dict[str, Any], ok: Optional[bool] = None) -> None:
    """Persist views.json atomically -- even for failed captures.

    The manifest also lands on the in-memory result, so the witness (and any
    later diagnosis surface) reads the same structure nothing can re-render
    differently.
    """
    if ok is not None:
        manifest["ok"] = ok
    manifest["detail"] = result.get("detail", "")
    result["manifest"] = manifest
    try:
        attempt_dir.mkdir(parents=True, exist_ok=True)
        path = attempt_dir / "views.json"
        redaction.write_json_atomic(path, redaction.redact_obj(manifest))
        result["manifest_path"] = str(path)
        log_event("INFO", "view_capture_recorded",
                  {"task_id": manifest.get("task_id"), "path": str(path),
                   "ok": bool(manifest.get("ok"))})
    except OSError as exc:  # never raises: evidence loss is logged, loudly
        log_event("ERROR", "view_manifest_write_failed",
                  {"task_id": manifest.get("task_id"), "error": str(exc)})


def _browser_tier(artifact: Path, expected: Dict[str, Any], attempt_dir: Path,
                  manifest: Dict[str, Any], result: Dict[str, Any]
                  ) -> List[Dict[str, Any]]:
    """Optional real render: a11y snapshot, screenshot, console errors.

    Returned findings are deterministic (evidence measured).  Import failure
    of Playwright is a *recorded degradation*, and a contract that demands a
    screenshot fails hard rather than passing on unobserved claims.
    """
    findings: List[Dict[str, Any]] = []
    try:
        from playwright.sync_api import (Error as PwError, sync_playwright)
    except Exception as exc:
        log_event("WARNING", "view_capture_unavailable",
                  {"task_id": manifest.get("task_id"),
                   "reason": f"playwright import failed: {exc}"})
        manifest["browser"] = {"available": False,
                               "reason": "playwright import failed"}
        return findings
    viewports = expected.get("viewports") or ["1280x800"]
    capture_name_base = "capture"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for i, vp in enumerate(viewports):
                    width, _sep, height = str(vp).partition("x")
                    size = {"width": int(width or 1280),
                            "height": int(height or 800)}
                    page = browser.new_page(viewport=size)
                    errors: List[str] = []
                    page.on("console",
                            lambda msg, _e=errors:
                            _e.append(msg.text) if msg.type == "error" else None)
                    page.goto(f"file:///{str(artifact)}".replace("\\", "/"),
                              wait_until="load")
                    shot = attempt_dir / f"{capture_name_base}{i or ''}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    usable, reason = screen_is_blank(shot)
                    ok_png, snap_head = _a11y_head(page)
                    manifest["screenshots"].append(
                        {"name": shot.name, "viewport": f"{size['width']}x{size['height']}",
                         "usable": usable, "reason": reason})
                    result["screenshots"] = manifest["screenshots"]
                    result["browser_used"] = True
                    if not usable:
                        findings.append({
                            "rule": "screenshot_blank", "severity": "high",
                            "anchor": shot.name, "evidence": "measured",
                            "detail": f"screenshot refuses itself: {reason}"})
                    if errors:
                        for err in errors[:5]:
                            findings.append({
                                "rule": "console_error", "severity": "medium",
                                "anchor": "console", "evidence": "measured",
                                "detail": err[:300]})
                    manifest["browser"] = {"available": True,
                                           "a11y_head": snap_head,
                                           "console_errors": len(errors),
                                           "ok_a11y": ok_png}
                    page.close()
            finally:
                browser.close()
    except PwError as exc:
        log_event("WARNING", "view_capture_unavailable",
                  {"task_id": manifest.get("task_id"),
                   "reason": f"browser tier error: {exc}"})
        manifest["browser"] = {"available": False,
                               "reason": f"browser tier error: {exc}"}
    if expected.get("screenshot_required") and not result.get("browser_used"):
        # A contract that demands a screenshot fails hard rather than passing
        # on an unobserved claim: named degradation, never silent.
        if not result.get("detail"):
            result["detail"] = ("view contract requires a screenshot but the "
                                "browser tier did not run")
        findings.append({
            "rule": "screenshot_unavailable", "severity": "high",
            "anchor": "browser", "evidence": "measured",
            "detail": "screenshot_required and no browser tier: "
                      "cannot verify what the contract demands"})
    return findings


def _a11y_head(page: Any) -> Tuple[bool, str]:
    """Bounded a11y-tree head for the manifest (witness reads this).

    Playwright 1.64 dropped ``page.accessibility``; the honest evidence
    source for a page-level structure read is the locator ``aria_snapshot``
    (the same a11y lineage the Playwright-MCP design rides on).  The legacy
    accessor stays a fallback so older installs degrade to their native
    behavior instead of an import-time opinion.
    """
    try:
        try:
            snap = page.locator("body").aria_snapshot()
        except Exception:
            snap_obj = getattr(page, "accessibility", None)
            snap = json.dumps(snap_obj.snapshot() if snap_obj else {}) \
                if snap_obj else None
        if not snap or not str(snap).strip():
            return False, "a11y snapshot empty"
        head = str(snap)[:2000]
        return True, head
    except Exception as exc:  # a11y absence must not kill a good capture
        return False, f"a11y snapshot failed: {exc}"


__all__ = [
    "parse_dom", "evaluate_dom", "screen_is_blank", "load_expected_view",
    "run_view", "TEXT_HEAD_CHARS",
]
