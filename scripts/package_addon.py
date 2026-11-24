# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Package the add-on as a release zip (``smart_clipping/`` at the zip root,
installable via Blender > Preferences > Add-ons > Install from Disk).

What goes in is an explicit list, so nothing else can slip in:

  - the files of ``smart_clipping/`` tracked by git whose suffix is in
    ALLOWED_SUFFIXES (untracked files, caches and local settings never go in;
    a tracked file of any other kind stops the build until the list says what
    to do with it)
  - the repository's LICENSE, as ``smart_clipping/LICENSE``

The version comes from ``bl_info`` in ``smart_clipping/__init__.py``.
``--version`` (e.g. from a release tag) is optional and must match it.

Usage:
  python scripts/package_addon.py
  python scripts/package_addon.py --version 1.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from versioning import ADDON_DIR, read_bl_info_version

# Kinds of file the add-on ships.  Add a suffix here when the add-on starts
# to need, say, an icon; the build fails on anything not listed.
ALLOWED_SUFFIXES = (".py",)
# Files from outside the add-on folder: (path in the repository, path in the ZIP)
EXTRA_FILES = (("LICENSE", f"{ADDON_DIR}/LICENSE"),)


class PackagingError(Exception):
    pass


def tracked_files(root: Path) -> "list[str]":
    """Repository-relative POSIX paths of the files git tracks in the add-on folder."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", ADDON_DIR], cwd=root,
            capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PackagingError(
            "the release ZIP is built from the files git tracks; run this in a git "
            f"checkout with git available ({exc})") from exc
    return [p for p in out.decode("utf-8").split("\0") if p]


def select_entries(tracked: "list[str]") -> "list[tuple[str, str]]":
    """``[(path in the repository, path in the ZIP), ...]`` in ZIP order.

    Raises PackagingError for a tracked file the allowlist does not cover.
    """
    rejected = []
    entries = []
    for path in tracked:
        pure = PurePosixPath(path)
        if pure.parts[0] != ADDON_DIR:
            continue
        if pure.suffix in ALLOWED_SUFFIXES and "__pycache__" not in pure.parts:
            entries.append((path, path))
        else:
            rejected.append(path)
    if rejected:
        raise PackagingError(
            "not allowed in the release ZIP (see ALLOWED_SUFFIXES in "
            f"scripts/package_addon.py): {', '.join(sorted(rejected))}")
    if not entries:
        raise PackagingError(f"no add-on files found under {ADDON_DIR}/")
    entries.extend(EXTRA_FILES)
    return sorted(entries, key=lambda entry: entry[1])


def write_zip(root: Path, entries, zip_path: Path) -> None:
    # Fixed order, timestamps and permissions: the same sources always give a
    # byte-identical ZIP (and checksum).
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for source, name in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3          # Unix, whatever OS builds the ZIP
            info.external_attr = 0o644 << 16
            zf.writestr(info, (root / source).read_bytes())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        default=None,
        help="Expected version, e.g. 1.1.0 (defaults to bl_info; must match it)",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for packaged files",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(root: Path, output_dir: Path, expected_version: "str | None" = None) -> Path:
    """Write the ZIP and its .sha256 into *output_dir*; returns the ZIP path."""
    version = read_bl_info_version(root)
    if expected_version is not None and expected_version.lstrip("v") != version:
        raise PackagingError(
            f"requested version {expected_version} does not match "
            f"bl_info version {version} in {ADDON_DIR}/__init__.py")

    entries = select_entries(tracked_files(root))
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{ADDON_DIR}-v{version}.zip"
    checksum_path = output_dir / f"{ADDON_DIR}-v{version}.sha256"
    write_zip(root, entries, zip_path)
    checksum_path.write_text(f"{sha256_file(zip_path)}  {zip_path.name}\n", encoding="utf-8")
    return zip_path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        zip_path = build(root, root / args.output_dir, args.version)
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created: {zip_path}")
    print(f"Created: {zip_path.with_suffix('.sha256')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
