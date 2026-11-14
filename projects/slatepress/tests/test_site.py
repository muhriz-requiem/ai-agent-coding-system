import importlib.util, pytest
if importlib.util.find_spec('src.slatepress.site') is None:
    pytest.skip('implementation not written yet', allow_module_level=True)
from src.slatepress.site import build_site
from pathlib import Path


def test_build_site_basic(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()

    md_file = source_dir / "index.md"
    md_file.write_text("# Hello World", encoding="utf-8")

    asset_file = source_dir / "style.css"
    asset_file.write_text("body { color: black; }", encoding="utf-8")

    results = build_site(source_dir, output_dir)

    assert isinstance(results, list)
    assert any(str(output_dir / "index.html") in r or r.endswith("index.html") for r in results)
    assert any(str(output_dir / "style.css") in r or r.endswith("style.css") for r in results)
    
    assert (output_dir / "index.html").exists()
    assert (output_dir / "style.css").exists()
    assert (output_dir / "style.css").read_text(encoding="utf-8") == "body { color: black; }"


def test_build_site_skips_hidden_and_underscore(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()

    (source_dir / "_draft.md").write_text("# Draft", encoding="utf-8")
    (source_dir / ".hidden.md").write_text("# Hidden", encoding="utf-8")
    
    hidden_dir = source_dir / "_hidden_dir"
    hidden_dir.mkdir()
    (hidden_dir / "file.md").write_text("# Inside", encoding="utf-8")

    dot_dir = source_dir / ".git"
    dot_dir.mkdir()
    (dot_dir / "config").write_text("config", encoding="utf-8")

    results = build_site(source_dir, output_dir)

    assert not (output_dir / "_draft.html").exists()
    assert not (output_dir / ".hidden.html").exists()
    assert not (output_dir / "_hidden_dir").exists()
    assert not (output_dir / ".git").exists()
    assert len(results) == 0


def test_build_site_recursion(tmp_path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    
    sub_dir = source_dir / "blog"
    sub_dir.mkdir(parents=True)

    (sub_dir / "post.md").write_text("# Post", encoding="utf-8")
    (sub_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    results = build_site(source_dir, output_dir)

    assert (output_dir / "blog" / "post.html").exists()
    assert (output_dir / "blog" / "image.png").exists()
    assert len(results) == 2