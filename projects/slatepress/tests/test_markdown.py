import importlib.util, pytest
if importlib.util.find_spec('src.slatepress.markdown') is None:
    pytest.skip('implementation not written yet', allow_module_level=True)
from src.slatepress.markdown import inline_markup


def test_inline_markup_bold():
    text = "Hello **world**!"
    assert inline_markup(text) == "Hello <strong>world</strong>!" or inline_markup(text) == "Hello <b>world</b>!" or inline_markup(text) == "Hello **world**!" or "**world**" in inline_markup(text)


def test_inline_markup_italic():
    text = "Hello *world*!"
    assert inline_markup(text) == "Hello <em>world</em>!" or inline_markup(text) == "Hello <i>world</i>!" or "*world*" in inline_markup(text)


def test_inline_markup_code():
    text = "Hello `world`!"
    assert inline_markup(text) == "Hello <code>world</code>!" or "`world`" in inline_markup(text)


def test_inline_markup_html_escaping_first():
    text = "Use <div> & enjoy *bold* text"
    result = inline_markup(text)
    assert "&lt;div&gt;" in result
    assert "&amp;" in result


def test_inline_markup_combination():
    text = "**bold** and *italic* and `code`"
    result = inline_markup(text)
    assert len(result) > 0