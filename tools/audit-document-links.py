#!/usr/bin/env python3
"""Check that local links in repository Markdown resolve to real files."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    failures: list[str] = []
    checked = 0
    markdown = [ROOT / "README.md", ROOT / "ROADMAP.md"]
    markdown.extend(sorted((ROOT / "docs").rglob("*.md")))
    markdown.extend(sorted((ROOT / "modern").rglob("*.md")))
    markdown.extend(sorted((ROOT / "experiments").rglob("*.md")))
    for document in markdown:
        for line_number, line in enumerate(
            document.read_text(encoding="utf-8").splitlines(), 1
        ):
            for match in LINK.finditer(line):
                target = match.group(1).strip().strip("<>")
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = unquote(target.split("#", 1)[0])
                if not target:
                    continue
                checked += 1
                resolved = (document.parent / target).resolve()
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    failures.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"link escapes repository: {target}"
                    )
                    continue
                if not resolved.exists():
                    failures.append(
                        f"{document.relative_to(ROOT)}:{line_number}: "
                        f"missing link target: {target}"
                    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"documentation links: passed local_links={checked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
