import importlib.util, pytest
if importlib.util.find_spec('src.slatepress.frontmatter') is None:
    pytest.skip('implementation not written yet', allow_module_level=True)
from src.slatepress.frontmatter import split_front_matter, parse_front_matter

def test_split_front_matter_valid():
    text = "---\ntitle: Hello\n---\nContent goes here."
    fm, content = split_front_matter(text)
    assert fm == "title: Hello"
    assert content == "Content goes here."

def test_split_front_matter_no_front_matter():
    text = "Just regular content."
    fm, content = split_front_matter(text)
    assert fm is None
    assert content == "Just regular content."

def test_split_front_matter_unclosed():
    text = "---\ntitle: Unclosed"
    with pytest.raises(ValueError):
        split_front_matter(text)

def test_parse_front_matter_valid():
    fm_text = "title: My Page\n# This is a comment\nauthor: John Doe"
    result = parse_front_matter(fm_text)
    assert result == {"title": "My Page", "author": "John Doe"}