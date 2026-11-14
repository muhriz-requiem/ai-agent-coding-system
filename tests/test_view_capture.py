"""VIEW_GATE_PLAN V2: the capture tier observes the artifact, not the code.

Law under test: fail-closed on every anomaly, and the gate checks its own
capture -- an empty render, a blank screenshot, an unparseable page or a
refused command can never produce a green manifest.  Every pin here is
offline: the DOM tier runs on fixtures via stdlib parsing, and the screenshot
tier is exercised through hand-constructed PNG bytes, so CI never needs a
browser (the browser tier itself is a caller-visible option, exercised live on
the V5 canary).
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import sight
from sight import run_view


# -------------------------------------------------------------- helpers
def _project(tmp_path: Path, build_script: str) -> Path:
    (tmp_path / "build_view.py").write_text(build_script, encoding="utf-8")
    (tmp_path / ".agent").mkdir(exist_ok=True)
    return tmp_path


def _expected(view_command: str = "python build_view.py", **extra) -> dict:
    out = {"view_command": view_command, "url_or_path": ".site/index.html"}
    out.update(extra)
    return out


FULL_PAGE = ("<!doctype html><html><head><title>t</title></head>"
             "<body><main><h1>Welcome</h1><h2>Section</h2>"
             "<p>plain sentence</p>"
             "<a href=\"other.html\">next</a></main></body></html>")

HAPPY_BUILD = (
    "import pathlib\n"
    "pathlib.Path('.site').mkdir(exist_ok=True)\n"
    f"pathlib.Path('.site/index.html').write_text({FULL_PAGE!r}, "
    "encoding='utf-8')\n"
    "pathlib.Path('.site/other.html').write_text("
    "'<html><body>ok</body></html>', encoding='utf-8')\n")


def _png_pixels(colors: list[tuple[int, int, int, int]],
                w: int = 4, h: int = 4) -> bytes:
    """Independent minimal PNG encoder (filter 0, truecolor+alpha).

    Written in the test on purpose: encoder and decoder share only the PNG
    format, so a bug in one cannot mask a bug in the other.
    """
    raw = b""
    for _ in range(h):
        row = b"".join(bytes(px) for px in colors)
        raw += b"\x00" + row  # filter type 0 (None) per scanline

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SOLID_RED = [(200, 30, 30, 255)] * 4
STRIPED = [(200, 30, 30, 255), (30, 200, 30, 255),
           (200, 30, 30, 255), (30, 200, 30, 255)]


# -------------------------------------------------------------- happy path
def test_dom_capture_happy_path(tmp_path) -> None:
    root = _project(tmp_path, HAPPY_BUILD)
    view_dir = root / "expected_views"
    view_dir.mkdir()
    contract = _expected(must_contain=["Welcome"],
                         dom_asserts=[{"type": "headings_ascending"},
                                      {"type": "img_has_alt"}])
    (view_dir / "T-1.json").write_text(json.dumps(contract), encoding="utf-8")
    result = run_view(root, sight.load_expected_view(view_dir / "T-1.json"),
                      attempt_dir=tmp_path / ".agent" / "views" / "T-1" / "a1",
                      use_browser=False)
    assert result["ok"], result.get("detail")
    assert result["findings"] == [], "a clean artifact produces no findings"
    manifest = json.loads((tmp_path / ".agent" / "views" / "T-1" / "a1"
                           / "views.json").read_text(encoding="utf-8"))
    assert manifest["dom"]["rendered_nonempty"] is True
    assert manifest["dom"]["headings"] == [1, 2]
    assert manifest["browser_used"] is False
    assert manifest["degraded"] is False


# -------------------------------------------------------------- fail-closed
def test_missing_artifact_is_red(tmp_path) -> None:
    root = _project(tmp_path, "import pathlib\npathlib.Path('x').touch()\n")
    result = run_view(root, _expected(), attempt_dir=tmp_path / "att",
                      use_browser=False)
    assert result["ok"] is False
    assert "artifact" in result["detail"].lower()


def test_unsafe_command_is_refused_without_running(tmp_path) -> None:
    root = _project(tmp_path, "raise SystemExit(1)")
    result = run_view(root, _expected("python build_view.py && echo pwned"),
                      attempt_dir=tmp_path / "att", use_browser=False)
    assert result["ok"] is False
    assert "plain" in result["detail"].lower(), \
        "chaining/substitution must be refused before any subprocess starts"


def test_failing_command_is_red(tmp_path) -> None:
    root = _project(tmp_path, "import sys\nsys.exit(2)\n")
    result = run_view(root, _expected(), attempt_dir=tmp_path / "att",
                      use_browser=False)
    assert result["ok"] is False
    assert result["exit_code"] == 2


def test_timeout_is_red(tmp_path) -> None:
    root = _project(tmp_path, "import time\ntime.sleep(8)\n")
    result = run_view(root, _expected(), attempt_dir=tmp_path / "att",
                      timeout_s=2, use_browser=False)
    assert result["ok"] is False
    assert "timed out" in result["detail"].lower()


def test_empty_render_refuses_the_capture(tmp_path) -> None:
    """The gate validates its own capture: a render that produced no visible
    text is not evidence, it is the capture lying."""
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              "pathlib.Path('.site/index.html').write_text("
              "'<!doctype html><html><body></body></html>', encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(), attempt_dir=tmp_path / "att",
                      use_browser=False)
    assert result["ok"] is False
    rules = {f["rule"] for f in result["findings"]}
    assert "render_nonempty" in rules


# -------------------------------------------------------------- dom asserts
SKIPPED_HEADING = ("<!doctype html><html><body><main><h1>A</h1>"
                   "<h3>C</h3></main></body></html>")


def test_heading_order_violation(tmp_path) -> None:
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              f"pathlib.Path('.site/index.html').write_text("
              f"{SKIPPED_HEADING!r}, encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(must_contain=["A"],
                                      dom_asserts=[{"type": "headings_ascending"}]),
                      attempt_dir=tmp_path / "att", use_browser=False)
    rules = {f["rule"] for f in result["findings"]}
    assert "headings_ascending" in rules


IMG_LACKS_ALT = ("<!doctype html><html><body><main><h1>Hi</h1>"
                 "<img src=\"x.png\"><img src=\"y.png\" alt=\"\"></main>"
                 "</body></html>")


def test_img_alt_violation_and_empty_alt_is_ok(tmp_path) -> None:
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              f"pathlib.Path('.site/index.html').write_text("
              f"{IMG_LACKS_ALT!r}, encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(must_contain=["Hi"],
                                      dom_asserts=[{"type": "img_has_alt"}]),
                      attempt_dir=tmp_path / "att", use_browser=False)
    lacks = [f for f in result["findings"] if f["rule"] == "img_has_alt"]
    assert len(lacks) == 1, \
        "empty-string alt is present-but-empty; only the absent alt violates"
    assert "x.png" in lacks[0]["anchor"]


# Source with a double-escaped ampersand: one decode pass leaves the literal
# "Q&amp;A" in the rendered text, which is what the user reads.
DOUBLE_ESCAPED = ("<!doctype html><html><body><main><h1>Q&amp;amp;A</h1>"
                  "</main></body></html>")


def test_double_escape_leak_detected(tmp_path) -> None:
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              f"pathlib.Path('.site/index.html').write_text("
              f"{DOUBLE_ESCAPED!r}, encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(must_contain=["Q"]),
                      attempt_dir=tmp_path / "att", use_browser=False)
    rules = {f["rule"] for f in result["findings"]}
    assert "raw_entity_in_text" in rules


BROKEN_LINK = ("<!doctype html><html><body><main><h1>Hi</h1>"
               "<a href=\"nowhere.html\">gone</a>"
               "<a href=\"other.html\">real</a></main></body></html>")


def test_broken_internal_links_detected(tmp_path) -> None:
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              f"pathlib.Path('.site/index.html').write_text("
              f"{BROKEN_LINK!r}, encoding='utf-8')\n"
              "pathlib.Path('.site/other.html').write_text("
              "'<html><body>ok</body></html>', encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(must_contain=["Hi"]),
                      attempt_dir=tmp_path / "att", use_browser=False)
    broken = [f for f in result["findings"] if f["rule"] == "link_local_missing"]
    assert len(broken) == 1 and "nowhere.html" in broken[0]["anchor"]


# -------------------------------------------------------------- screenshot
def test_solid_screenshot_is_blank_stripes_are_not(tmp_path) -> None:
    solid = tmp_path / "solid.png"
    solid.write_bytes(_png_pixels(SOLID_RED))
    striped = tmp_path / "striped.png"
    striped.write_bytes(_png_pixels(STRIPED))
    ok, reason = sight.screen_is_blank(solid)
    assert not ok and "variance 0" in reason
    ok, reason = sight.screen_is_blank(striped)
    assert ok, f"distinct rows must not read blank: {reason}"


def test_garbage_screenshot_is_refused(tmp_path) -> None:
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not a png")
    ok, reason = sight.screen_is_blank(junk)
    assert not ok and "png" in reason.lower(), \
        "an unreadable capture is not evidence"


def test_expected_view_loader_rejects_bad_json(tmp_path) -> None:
    bad = tmp_path / "expected_views"
    bad.mkdir()
    (bad / "T-1.json").write_text("{not json", encoding="utf-8")
    try:
        sight.load_expected_view(bad / "T-1.json")
        assert False, "must refuse"
    except ValueError as exc:
        assert "json" in str(exc).lower()


# ----------------------------------------------------- structural contracts
# (VIEW_GATE_PLAN V5: a goal pins structure, not just text -- slatepress's
# goal pins the page body inside <main>.  Visible text cannot express that.)
NO_MAIN = ("<!doctype html><html><body>"
           "<p>content sits nowhere structured</p>"
           "<h1>Welcome</h1></body></html>")
WITH_MAIN = ("<!doctype html><html><body><main>"
             "<h1>Welcome</h1></main></body></html>")


def _render(tmp_path, source_html: str, **expected_extra):
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              f"pathlib.Path('.site/index.html').write_text("
              f"{source_html!r}, encoding='utf-8')\n")
    root = _project(tmp_path, script)
    return run_view(root, _expected(must_contain=["Welcome"],
                                    **expected_extra),
                    attempt_dir=tmp_path / "att", use_browser=False)


def test_tag_present_catches_the_missing_main(tmp_path) -> None:
    result = _render(tmp_path, NO_MAIN,
                     dom_asserts=[{"type": "tag_present", "tag": "main"}])
    rules = {f["rule"] for f in result["findings"]}
    assert rules == {"tag_present"}, \
        "the slatepress canary catch: tests green, structure missing"
    assert result["ok"] is False


def test_tag_present_passes_on_structured_artifact(tmp_path) -> None:
    result = _render(tmp_path, WITH_MAIN,
                     dom_asserts=[{"type": "tag_present", "tag": "main"}])
    assert result["ok"] is True, result["detail"]


def test_tag_absent_and_tagless_declared_assert(tmp_path) -> None:
    # script.html: never used; the WITH_MAIN fixture but with a <div> instead
    # of main so tag_absent div fires:
    script = ("import pathlib\n"
              "pathlib.Path('.site').mkdir(exist_ok=True)\n"
              "pathlib.Path('.site/index.html').write_text("
              "'<html><body><main><h1>Welcome</h1></main></body></html>', "
              "encoding='utf-8')\n")
    root = _project(tmp_path, script)
    result = run_view(root, _expected(
        must_contain=["Welcome"],
        dom_asserts=[{"type": "tag_absent", "tag": "div"},
                     {"type": "tag_present"}]),  # tagless -> unverifiable
        attempt_dir=tmp_path / "att", use_browser=False)
    rules = {f["rule"] for f in result["findings"]}
    assert "tag_absent" not in rules, "absent means clean when it is absent"
    assert "view_contract_unverifiable" in rules, \
        "a structural assert with no tag cannot pretend to have checked"
