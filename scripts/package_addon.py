"""
Package the src addon directory as a release zip.

Usage:
  python scripts/package_addon.py --version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import os
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="Version string, e.g. 1.0.0")
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


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    addon_dir = root / "src"
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_path = output_dir / f"src-v{args.version}.zip"
    checksum_path = output_dir / f"src-v{args.version}.sha256"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in addon_dir.rglob("*"):
            if file_path.is_dir():
                continue
            if "__pycache__" in str(file_path):
                continue
            if file_path.suffix == ".pyc":
                continue
            arc_path = file_path.relative_to(root).as_posix()
            zf.write(file_path, arc_path)

    checksum = sha256_file(zip_path)
    checksum_path.write_text(f"{checksum}  {zip_path.name}\n", encoding="utf-8")

    print(f"Created: {zip_path}")
    print(f"Created: {checksum_path}")


if __name__ == "__main__":
    main()
