"""
Package the add-on as a release zip (``smart_clipping/`` at the zip root,
installable via Blender > Preferences > Add-ons > Install from Disk).

The version comes from ``bl_info`` in ``smart_clipping/__init__.py``.
``--version`` (e.g. from a release tag) is optional and must match it.

Usage:
  python scripts/package_addon.py
  python scripts/package_addon.py --version 1.1.0
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

from versioning import ADDON_DIR, read_bl_info_version


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


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]

    version = read_bl_info_version(root)
    if args.version is not None and args.version.lstrip("v") != version:
        print(
            f"error: requested version {args.version} does not match "
            f"bl_info version {version} in {ADDON_DIR}/__init__.py",
            file=sys.stderr,
        )
        return 1

    addon_dir = root / ADDON_DIR
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_path = output_dir / f"{ADDON_DIR}-v{version}.zip"
    checksum_path = output_dir / f"{ADDON_DIR}-v{version}.sha256"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(addon_dir.rglob("*")):
            if file_path.is_dir():
                continue
            if "__pycache__" in file_path.parts or file_path.suffix == ".pyc":
                continue
            arc_path = file_path.relative_to(root).as_posix()
            zf.write(file_path, arc_path)

    checksum = sha256_file(zip_path)
    checksum_path.write_text(f"{checksum}  {zip_path.name}\n", encoding="utf-8")

    print(f"Created: {zip_path}")
    print(f"Created: {checksum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
