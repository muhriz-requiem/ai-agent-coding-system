import html
import re

# Pre-compiled regular expressions for inline markup.
# We process inline code first, then bold, then italic.
_CODE_RE = re.compile(r'`([^`]+)`')
_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_ITALIC_RE = re.compile(r'\*([^*]+)\*')


def inline_markup(text: str) -> str:
    """Applies inline Markdown markup (bold, italic, inline code) to text.

    HTML special characters (&, <, >) are escaped FIRST so markup characters
    in source text are not treated as markup after escaping.
    """
    if not text:
        return ""

    # 1. Escape HTML special characters first
    escaped = html.escape(text)

    # 2. Apply inline code first to prevent inner asterisks from being parsed as bold/italic
    def replace_code(match: re.Match) -> str:
        return f"<code>{match.group(1)}</code>"

    processed = _CODE_RE.sub(replace_code, escaped)

    # 3. Apply bold (**text**)
    def replace_bold(match: re.Match) -> str:
        return f"<strong>{match.group(1)}</strong>"

    processed = _BOLD_RE.sub(replace_bold, processed)

    # 4. Apply italic (*text*)
    def replace_italic(match: re.Match) -> str:
        return f"<em>{match.group(1)}</em>"

    processed = _ITALIC_RE.sub(replace_italic, processed)

    return processed
