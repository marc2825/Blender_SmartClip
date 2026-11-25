# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Single source of truth for the addon version: ``bl_info["version"]`` in
``smart_clipping/__init__.py``.

Run as a script to verify that every other file quoting the version agrees:

  python scripts/versioning.py

Print the CHANGELOG section of a version (used as GitHub release notes):

  python scripts/versioning.py --notes 1.2.0 [--output dist/RELEASE_NOTES.md]

Checks:
  - smart_clipping/blender_manifest.toml: ``version`` (the extension's)
  - CHANGELOG.md: newest released entry is ``## [X.Y.Z] - YYYY-MM-DD``
  - CITATION.cff: ``version`` and ``date-released`` match that entry
  - README.md / README.ja.md: the static version badge shows the version
  - .github/ISSUE_TEMPLATE/bug_report.yml: the example add-on version
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = "smart_clipping"
MANIFEST = "blender_manifest.toml"     # the extension manifest, in ADDON_DIR

_README_BADGE = re.compile(r"img\.shields\.io/badge/version-(?P<version>[0-9.]+)-")
_READMES = ("README.md", "README.ja.md")
_BUG_TEMPLATE = ".github/ISSUE_TEMPLATE/bug_report.yml"
_TEMPLATE_VERSION = re.compile(r'id: addon_version\n(?:.*\n)*?\s*placeholder: "(?P<version>[^"]*)"')
_CHANGELOG_ENTRY = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?", re.M)


def read_bl_info_version(root: Path = ROOT) -> str:
    """Return ``bl_info["version"]`` as ``"X.Y.Z"`` without importing bpy."""
    source = (root / ADDON_DIR / "__init__.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets
        ):
            info = ast.literal_eval(node.value)
            return ".".join(str(part) for part in info["version"])
    raise RuntimeError(f"bl_info not found in {ADDON_DIR}/__init__.py")


def read_manifest_version(root: Path = ROOT) -> str:
    """Return ``version`` from the extension manifest."""
    text = (root / ADDON_DIR / MANIFEST).read_text(encoding="utf-8")
    try:
        import tomllib                      # Python 3.11+
    except ModuleNotFoundError:
        match = re.search(r'^version\s*=\s*"([^"]*)"\s*$', text, re.M)
        if match is None:
            raise RuntimeError(f"no version in {ADDON_DIR}/{MANIFEST}") from None
        return match.group(1)
    return str(tomllib.loads(text)["version"])


def latest_changelog_release(root: Path = ROOT) -> "tuple[str, str | None]":
    """Return (version, date) of the newest non-"Unreleased" CHANGELOG entry."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    for match in _CHANGELOG_ENTRY.finditer(text):
        if match["version"].lower() != "unreleased":
            return match["version"], match["date"]
    raise RuntimeError("no released entry found in CHANGELOG.md")


def changelog_section(version: str, root: Path = ROOT) -> str:
    """Return the body of the ``## [version]`` CHANGELOG entry (without heading)."""
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    entries = list(_CHANGELOG_ENTRY.finditer(text))
    for i, match in enumerate(entries):
        if match["version"] == version:
            end = entries[i + 1].start() if i + 1 < len(entries) else len(text)
            body = text[match.end():end]
            # Drop trailing link reference definitions, if any
            body = re.sub(r"^\[[^\]]+\]:\s*\S+\s*$", "", body, flags=re.M)
            return body.strip() + "\n"
    raise RuntimeError(f"CHANGELOG.md has no entry for {version}")


def _cff_field(text: str, key: str) -> "str | None":
    match = re.search(rf'^{re.escape(key)}:\s*"?([^"\n]+?)"?\s*$', text, re.M)
    return match.group(1) if match else None


def check(root: Path = ROOT) -> "list[str]":
    """Return a list of human-readable mismatches (empty = consistent)."""
    version = read_bl_info_version(root)
    problems = []

    manifest_version = read_manifest_version(root)
    if manifest_version != version:
        problems.append(f"{ADDON_DIR}/{MANIFEST} version is {manifest_version}, bl_info is {version}")

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

    for name in _READMES:
        badges = _README_BADGE.findall((root / name).read_text(encoding="utf-8"))
        if badges != [version]:
            problems.append(f"{name} version badge shows {', '.join(badges) or 'nothing'}, "
                            f"bl_info is {version}")

    template = _TEMPLATE_VERSION.search((root / _BUG_TEMPLATE).read_text(encoding="utf-8"))
    shown = template["version"] if template else None
    if shown != version:
        problems.append(f"{_BUG_TEMPLATE} example version is {shown}, bl_info is {version}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--notes", metavar="VERSION",
                        help="print the CHANGELOG section for VERSION and exit")
    parser.add_argument("--output", metavar="PATH",
                        help="with --notes: write the section to PATH (UTF-8)")
    args = parser.parse_args()
    if args.notes:
        notes = changelog_section(args.notes.lstrip("v"))
        if args.output:
            Path(args.output).write_text(notes, encoding="utf-8")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(notes)
        return 0

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
