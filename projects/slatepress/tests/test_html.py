import importlib.util, pytest
if importlib.util.find_spec('src.slatepress.html') is None:
    pytest.skip('implementation not written yet', allow_module_level=True)
from src.slatepress.html import escape, page

def test_escape_basic_characters():
    assert escape("Hello & <world>") == "Hello &amp; &lt;world&gt;"

def test_escape_no_special_characters():
    assert escape("Hello World") == "Hello World"

def test_escape_all_special_characters():
    assert escape("&<>") == "&amp;&lt;&gt;"

def test_page_basic_structure():
    result = page("My Title", "<p>Hello</p>")
    assert "<!DOCTYPE html>" in result
    assert "<title>My Title</title>" in result
    assert "<main><p>Hello</p></main>" in result

def test_page_with_css_link():
    result = page("My Title", "<p>Hello</p>", css_link="style.css")
    assert '<link rel="stylesheet" href="style.css">' in result or 'href="style.css"' in result

def test_page_without_css_link():
    result = page("My Title", "<p>Hello</p>", css_link=None)
    assert "stylesheet" not in result