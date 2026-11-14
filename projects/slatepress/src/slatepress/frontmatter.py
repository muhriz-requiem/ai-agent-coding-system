"""Front matter parsing utilities."""

from __future__ import annotations
from typing import Optional, Tuple


def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    """
    Split ``text`` into front matter and content.

    The front matter is expected to be delimited by lines that consist
    solely of three dashes (``---``), optionally surrounded by whitespace.
    If no opening delimiter is found, returns ``(None, text)``.
    If an opening delimiter is found but no closing delimiter follows,
    raises ``ValueError``.

    Parameters
    ----------
    text: str
        The input string possibly containing front matter.

    Returns
    -------
    tuple[Optional[str], str]
        A tuple where the first element is the front matter string (or
        ``None`` if absent) and the second element is the remaining content.
    """
    lines = text.splitlines()
    n = len(lines)
    i = 0
    # locate opening delimiter
    while i < n and lines[i].strip() != "---":
        i += 1
    if i == n:
        # No front matter
        return (None, text)
    # locate closing delimiter
    j = i + 1
    while j < n and lines[j].strip() != "---":
        j += 1
    if j == n:
        raise ValueError("Unclosed front matter delimiter")
    # Extract front matter and content
    front_matter_lines = lines[i + 1 : j]
    content_lines = lines[j + 1 :]
    front_matter = "\n".join(front_matter_lines)
    content = "\n".join(content_lines)
    return (front_matter, content)


def parse_front_matter(text: str) -> dict[str, str]:
    """
    Parse front matter text into a dictionary.

    Supports simple ``key: value`` lines. Blank lines and lines starting
    with ``#`` (after stripping whitespace) are ignored. Whitespace around
    keys and values is stripped.

    Parameters
    ----------
    text: str
        The front matter string (without the delimiters).

    Returns
    -------
    dict[str, str]
        Mapping of keys to values.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            # Skip malformed lines; alternatively could treat as key with empty value.
            continue
        key, value = stripped.split(":", 1)
        result[key.strip()] = value.strip()
    return result
