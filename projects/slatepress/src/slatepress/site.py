import os
from pathlib import Path
import yaml
import markdown


def build_site(source_dir: Path, output_dir: Path) -> list[str]:
    if not source_dir.is_dir():
        return []
    written = []
    for root, dirs, files in os.walk(source_dir, topdown=True):
        # Skip directories starting with _ or .
        dirs[:] = [d for d in dirs if not d.startswith('_') and not d.startswith('.')]
        for file in files:
            if file.startswith('_') or file.startswith('.'):
                continue
            file_path = Path(root) / file
            try:
                rel_path = file_path.relative_to(source_dir)
            except ValueError:
                continue
            if file_path.suffix == '.md':
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                except Exception:
                    continue
                # Parse front matter
                if content.startswith('---\n'):
                    parts = content.split('---\n', 2)
                    if len(parts) >= 3:
                        front_matter = parts[1]
                        markdown_content = parts[2]
                        try:
                            metadata = yaml.safe_load(front_matter)
                        except Exception:
                            metadata = {}
                    else:
                        metadata = {}
                        markdown_content = content
                else:
                    metadata = {}
                    markdown_content = content
                # Convert markdown to HTML
                try:
                    html_content = markdown.markdown(markdown_content)
                except Exception:
                    html_content = markdown_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Apply template
                title = metadata.get('title', file_path.stem)
                template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>__TITLE__</title>
</head>
<body>
    __CONTENT__
</body>
</html>"""
                html_output = template.replace('__TITLE__', title).replace('__CONTENT__', html_content)
                output_path = output_dir / rel_path.with_suffix('.html')
                try:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write(html_output)
                    written.append(str(output_path))
                except Exception:
                    continue
            else:
                output_path = output_dir / rel_path
                try:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(file_path, 'rb') as f_in, open(output_path, 'wb') as f_out:
                        f_out.write(f_in.read())
                    written.append(str(output_path))
                except Exception:
                    continue
    return sorted(written)
