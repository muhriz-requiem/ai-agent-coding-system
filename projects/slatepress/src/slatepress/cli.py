from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Sequence


def build_site(source: Path, output: Path) -> None:
    """Build the static site by copying source content to output directory.

    This is a minimal implementation. In a full implementation, this would
    process markdown, templates, assets, etc.
    """
    output.mkdir(parents=True, exist_ok=True)

    if not source.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source}")

    if not source.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source}")

    # Copy all files from source to output
    for item in source.rglob("*"):
        if item.is_file():
            relative = item.relative_to(source)
            dest = output / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point for slatepress.

    Parses command line arguments, validates that the source directory exists,
    and runs the site builder. Returns 0 on success, 2 if the source directory
    does not exist or is invalid, and 1 on other failures.
    """
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="slatepress",
        description="SlatePress static site generator.",
    )
    parser.add_argument(
        "source",
        type=str,
        help="Path to the source content directory.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=str,
        default="_site",
        help="Path to the output build directory (default: _site).",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_opt",
        type=str,
        help="Path to the output build directory.",
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    source_path = Path(args.source)
    if not source_path.exists() or not source_path.is_dir():
        return 2

    # Use -o/--output if provided, otherwise positional output or default
    out_dir = args.output_opt if args.output_opt is not None else args.output
    output_path = Path(out_dir)

    try:
        build_site(source_path, output_path)
    except Exception:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
