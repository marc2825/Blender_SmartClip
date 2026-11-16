"""
Single source of truth for the addon version: ``bl_info["version"]`` in
``src/__init__.py``.

Run as a script to verify that every other file quoting the version agrees:

  python scripts/versioning.py

Checks:
  - CHANGELOG.md: newest released entry is ``## [X.Y.Z] - YYYY-MM-DD``
  - CITATION.cff: ``version`` and ``date-released`` match that entry
  - README.md:    title line ends with ``vX.Y.Z``
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_CHANGELOG_ENTRY = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?", re.M)


def read_bl_info_version(root: Path = ROOT) -> str:
    """Return ``bl_info["version"]`` as ``"X.Y.Z"`` without importing bpy."""
    source = (root / "src" / "__init__.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
        ):
            info = ast.literal_eval(node.value)
            return ".".join(str(part) for part in info["version"])
    raise RuntimeError("bl_info not found in src/__init__.py")


def latest_changelog_release(root: Path = ROOT) -> "tuple[str, str | None]":
    """Return (version, date) of the newest non-"Unreleased" CHANGELOG entry."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    for match in _CHANGELOG_ENTRY.finditer(text):
        if match["version"].lower() != "unreleased":
            return match["version"], match["date"]
    raise RuntimeError("no released entry found in CHANGELOG.md")


def _cff_field(text: str, key: str) -> "str | None":
    match = re.search(rf'^{re.escape(key)}:\s*"?([^"\n]+?)"?\s*$', text, re.M)
    return match.group(1) if match else None


def check(root: Path = ROOT) -> "list[str]":
    """Return a list of human-readable mismatches (empty = consistent)."""
    version = read_bl_info_version(root)
    problems = []

    cl_version, cl_date = latest_changelog_release(root)
    if cl_version != version:
        problems.append(f"CHANGELOG.md newest release is {cl_version}, bl_info is {version}")
    if not cl_date:
        problems.append(f"CHANGELOG.md entry [{cl_version}] has no release date")

    cff = (root / "CITATION.cff").read_text(encoding="utf-8")
    cff_version = _cff_field(cff, "version")
    cff_date = _cff_field(cff, "date-released")
    if cff_version != version:
        problems.append(f"CITATION.cff version is {cff_version}, bl_info is {version}")
    if cl_date and cff_date != cl_date:
        problems.append(f"CITATION.cff date-released is {cff_date}, CHANGELOG [{cl_version}] is {cl_date}")

    readme_title = (root / "README.md").read_text(encoding="utf-8").splitlines()[0]
    if not readme_title.rstrip().endswith(f"v{version}"):
        problems.append(f"README.md title '{readme_title}' does not end with v{version}")

    return problems


def main() -> int:
    version = read_bl_info_version()
    problems = check()
    if problems:
        print(f"Version mismatch (source of truth: bl_info = {version}):")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Version files consistent: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
