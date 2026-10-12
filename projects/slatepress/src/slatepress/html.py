from typing import Optional

# Pre-compiled translation table for HTML escaping
_HTML_ESCAPE_TABLE = str.maketrans({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#x27;",
})


def escape(text: str) -> str:
    """Encode special HTML characters (&, <, >, ", ')."""
    if not text:
        return ""
    return text.translate(_HTML_ESCAPE_TABLE)


def page(title: str, body: str, css_link: Optional[str] = None) -> str:
    """Produce a complete HTML5 document string with doctype, head, and body containing a main element."""
    escaped_title = escape(title)

    css_tag = f'    <link rel="stylesheet" href="{escape(css_link)}">\n' if css_link else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{escaped_title}</title>
{css_tag}</head>
<body>
    <main>{body}</main>
</body>
</html>
"""
