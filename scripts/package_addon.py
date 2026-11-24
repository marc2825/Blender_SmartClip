# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Package the add-on in both formats, from the same sources:

  legacy     ``smart_clipping-vX.Y.Z.zip``: ``smart_clipping/`` at the zip root,
             for Preferences > Add-ons > Install from Disk on Blender 4.0+
             (it has no manifest, so Blender 4.2+ installs it as a legacy
             add-on too)
  extension  ``smart_clipping-vX.Y.Z-extension.zip``: the files at the zip
             root with ``blender_manifest.toml``, as
             ``blender --command extension build`` lays them out, for
             Blender 4.2+ and extensions.blender.org

What goes in is an explicit list, so nothing else can slip in:

  - the files of ``smart_clipping/`` tracked by git whose suffix is in
    SOURCE_SUFFIXES (untracked files, caches and local settings never go in)
  - ``smart_clipping/blender_manifest.toml``, in the extension only
  - the repository's LICENSE
  - a tracked file of any other kind stops the build until the lists say
    what to do with it

The version comes from ``bl_info`` in ``smart_clipping/__init__.py``, and the
manifest must say the same.  ``--version`` (e.g. from a release tag) is
optional and must match it.  Each ZIP gets a ``.sha256`` next to it.

Usage:
  python scripts/package_addon.py [--format legacy|extension|all]
  python scripts/package_addon.py --version 2.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

from versioning import ADDON_DIR, MANIFEST, read_bl_info_version, read_manifest_version

LEGACY = "legacy"
EXTENSION = "extension"
FORMATS = (LEGACY, EXTENSION)

# Kinds of file the add-on ships.  Add a suffix here when the add-on starts
# to need, say, an icon; the build fails on anything not listed.
SOURCE_SUFFIXES = (".py",)
# Files from outside the add-on folder: (path in the repository, name in the add-on)
EXTRA_FILES = (("LICENSE", "LICENSE"),)


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
            "the release ZIPs are built from the files git tracks; run this in a git "
            f"checkout with git available ({exc})") from exc
    return [p for p in out.decode("utf-8").split("\0") if p]


def zip_name(fmt: str, name: str) -> str:
    """Where a file of the add-on (``name``, relative to it) goes in the ZIP."""
    return f"{ADDON_DIR}/{name}" if fmt == LEGACY else name


def select_entries(tracked: "list[str]", fmt: str = LEGACY) -> "list[tuple[str, str]]":
    """``[(path in the repository, path in the ZIP), ...]`` in ZIP order.

    Raises PackagingError for a tracked file the lists do not cover.
    """
    if fmt not in FORMATS:
        raise PackagingError(f"unknown format {fmt!r}, expected one of {', '.join(FORMATS)}")
    manifest = f"{ADDON_DIR}/{MANIFEST}"
    rejected = []
    entries = []
    for path in tracked:
        pure = PurePosixPath(path)
        if pure.parts[0] != ADDON_DIR:
            continue
        name = PurePosixPath(*pure.parts[1:]).as_posix()
        if path == manifest:
            if fmt == EXTENSION:
                entries.append((path, zip_name(fmt, name)))
        elif pure.suffix in SOURCE_SUFFIXES and "__pycache__" not in pure.parts:
            entries.append((path, zip_name(fmt, name)))
        else:
            rejected.append(path)
    if rejected:
        raise PackagingError(
            "not allowed in the release ZIPs (see SOURCE_SUFFIXES in "
            f"scripts/package_addon.py): {', '.join(sorted(rejected))}")
    if not any(PurePosixPath(src).suffix in SOURCE_SUFFIXES for src, _ in entries):
        raise PackagingError(f"no add-on files found under {ADDON_DIR}/")
    if fmt == EXTENSION and not any(src == manifest for src, _ in entries):
        raise PackagingError(f"the extension needs {manifest}, which git does not track")
    entries.extend((src, zip_name(fmt, name)) for src, name in EXTRA_FILES)
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_filename(version: str, fmt: str = LEGACY) -> str:
    suffix = "-extension" if fmt == EXTENSION else ""
    return f"{ADDON_DIR}-v{version}{suffix}.zip"


def build(root: Path, output_dir: Path, expected_version: "str | None" = None,
          fmt: str = LEGACY) -> Path:
    """Write one ZIP and its .sha256 into *output_dir*; returns the ZIP path."""
    version = read_bl_info_version(root)
    if expected_version is not None and expected_version.lstrip("v") != version:
        raise PackagingError(
            f"requested version {expected_version} does not match "
            f"bl_info version {version} in {ADDON_DIR}/__init__.py")
    manifest_version = read_manifest_version(root)
    if manifest_version != version:
        raise PackagingError(
            f"{ADDON_DIR}/{MANIFEST} says version {manifest_version}, "
            f"bl_info says {version}")

    entries = select_entries(tracked_files(root), fmt)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / zip_filename(version, fmt)
    write_zip(root, entries, zip_path)
    # LF on every OS, so that `sha256sum -c` reads it anywhere
    zip_path.with_suffix(".sha256").write_bytes(
        f"{sha256_file(zip_path)}  {zip_path.name}\n".encode("ascii"))
    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        default=None,
        help="Expected version, e.g. 2.1.0 (defaults to bl_info; must match it)",
    )
    parser.add_argument(
        "--format",
        choices=(*FORMATS, "all"),
        default="all",
        help="Which ZIP to build (default: both)",
    )
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for packaged files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    formats = FORMATS if args.format == "all" else (args.format,)
    try:
        for fmt in formats:
            zip_path = build(root, root / args.output_dir, args.version, fmt)
            print(f"Created: {zip_path}")
            print(f"Created: {zip_path.with_suffix('.sha256')}")
    except PackagingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
