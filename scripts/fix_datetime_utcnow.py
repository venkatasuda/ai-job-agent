"""
scripts/fix_datetime_utcnow.py — one-off migration
===================================================
Replaces deprecated `datetime.utcnow()` with timezone-aware
`datetime.now(timezone.utc)` across the codebase, adding the `timezone`
import wherever `datetime` is imported from the stdlib `datetime` module.

`datetime.utcnow()` is deprecated on Python 3.12+ and scheduled for removal.
The aware form is the recommended replacement.

Run once:
    python scripts/fix_datetime_utcnow.py
Then verify:
    python -m pytest tests/ -v

Safe to re-run: once migrated, files contain no `datetime.utcnow()` and are skipped.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "data", "resumes",
    "__pycache__", "node_modules", ".pytest_cache", "build", "dist",
}


def ensure_timezone_in_from_import(src: str) -> str:
    """Add `timezone` to a single-line `from datetime import ...` if missing."""

    def repl(m: re.Match) -> str:
        body = m.group(1)
        if "(" in body:  # parenthesized multi-line import — leave untouched
            return m.group(0)
        names = [n.strip() for n in body.split(",") if n.strip()]
        if "timezone" not in names:
            names.append("timezone")
        return "from datetime import " + ", ".join(names)

    return re.sub(r"from datetime import ([^\n]+)", repl, src, count=1)


def process(path: Path) -> bool:
    """Migrate one file. Returns True if it was changed."""
    src = path.read_text(encoding="utf-8")
    if "datetime.utcnow()" not in src:
        return False

    if re.search(r"^from datetime import ", src, re.M):
        # `from datetime import datetime` style → bare `datetime.utcnow()`
        new = src.replace("datetime.utcnow()", "datetime.now(timezone.utc)")
        new = ensure_timezone_in_from_import(new)
    else:
        # `import datetime` style → `datetime.datetime.utcnow()`
        new = src.replace(
            "datetime.datetime.utcnow()",
            "datetime.datetime.now(datetime.timezone.utc)",
        )

    if new != src:
        path.write_text(new, encoding="utf-8")
        return True
    return False


def main() -> None:
    self_path = Path(__file__).resolve()
    changed: list[Path] = []
    skipped_parenthesized: list[Path] = []

    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == self_path:
            continue
        before = path.read_text(encoding="utf-8")
        if process(path):
            changed.append(path.relative_to(ROOT))
        elif "datetime.utcnow()" in before:
            # Had occurrences but nothing changed — likely a parenthesized import
            skipped_parenthesized.append(path.relative_to(ROOT))

    print(f"Updated {len(changed)} file(s):")
    for c in sorted(changed):
        print(f"  {c}")
    if skipped_parenthesized:
        print("\nNeeds manual review (add `timezone` to their datetime import):")
        for s in sorted(skipped_parenthesized):
            print(f"  {s}")


if __name__ == "__main__":
    main()
