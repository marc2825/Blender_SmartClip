# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Checks of the release ZIPs' contents (plain Python 3, no Blender needed).

Usage:
  python tests/package_test.py

- Only allowlisted add-on files and the LICENSE go in; anything else that is
  tracked stops the build, and untracked files (caches, local notes, settings)
  never go in.  The manifest goes into the extension only.
- The legacy ZIP has one top folder, ``smart_clipping/``; the extension ZIP
  has its files at the root, next to ``blender_manifest.toml``.
- Both have fixed timestamps and permissions, the sources and LICENSE exactly
  as in the repository, and two builds of the same sources are byte-identical
  with a matching .sha256.

Exit code 0 = all checks passed.
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_addon  # noqa: E402
from package_addon import EXTENSION, LEGACY, PackagingError, select_entries  # noqa: E402
from versioning import read_bl_info_version, read_manifest_version  # noqa: E402

SPDX = (b"# SPDX-FileCopyrightText: 2026 marc2825\n"
        b"# SPDX-License-Identifier: GPL-3.0-or-later\n")

_checked = []
_failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip(), flush=True)
    _checked.append(name)
    if not cond:
        _failures.append(name)


def rejects(tracked, fmt=LEGACY) -> bool:
    try:
        select_entries(tracked, fmt)
    except PackagingError:
        return True
    return False


def check_lists():
    sample = ["smart_clipping/__init__.py", "smart_clipping/ops.py",
              "smart_clipping/blender_manifest.toml", "tests/headless_test_runner.py",
              "README.md"]
    entries = select_entries(sample, LEGACY)
    check("legacy_keeps_sources_and_license",
          [name for _src, name in entries] == ["smart_clipping/LICENSE",
                                               "smart_clipping/__init__.py",
                                               "smart_clipping/ops.py"], str(entries))
    entries = select_entries(sample, EXTENSION)
    check("extension_keeps_sources_manifest_and_license",
          [name for _src, name in entries] == ["LICENSE", "__init__.py",
                                               "blender_manifest.toml", "ops.py"], str(entries))
    for fmt in (LEGACY, EXTENSION):
        for stray in ("smart_clipping/notes.txt", "smart_clipping/.env",
                      "smart_clipping/__pycache__/ops.cpython-311.pyc",
                      "smart_clipping/.DS_Store", "smart_clipping/settings.toml",
                      "smart_clipping/sub/blender_manifest.toml"):
            check(f"{fmt}_rejects_tracked:{stray}",
                  rejects(["smart_clipping/__init__.py", "smart_clipping/blender_manifest.toml",
                           stray], fmt))
        check(f"{fmt}_rejects_empty", rejects(["README.md"], fmt))
    check("extension_needs_manifest", rejects(["smart_clipping/__init__.py"], EXTENSION))
    check("unknown_format_refused", rejects(["smart_clipping/__init__.py"], "wheel"))


def check_manifest():
    """Rules of the manifest that building the ZIP does not check."""
    try:
        import tomllib
    except ModuleNotFoundError:
        print("[SKIP] manifest_fields (needs Python 3.11+ for tomllib)")
        return
    text = (ROOT / "smart_clipping" / "blender_manifest.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    check("manifest_version_is_bl_info", read_manifest_version(ROOT) == read_bl_info_version(ROOT))
    check("manifest_id_is_folder", data.get("id") == "smart_clipping", str(data.get("id")))
    check("manifest_license", data.get("license") == ["SPDX:GPL-3.0-or-later"],
          str(data.get("license")))
    tagline = data.get("tagline", "")
    check("manifest_tagline", 0 < len(tagline) <= 64 and tagline[-1].isalnum()
          and "blender" not in tagline.lower(), repr(tagline))
    check("manifest_name_without_blender", "blender" not in data.get("name", "").lower())
    check("manifest_no_empty_values", all(value not in ("", [], {}) for value in data.values()))
    check("manifest_no_permissions", "permissions" not in data)


def check_build(fmt, out, tracked):
    sources = sorted(p for p in tracked if p.endswith(".py"))
    if fmt == LEGACY:
        expected = sorted(sources + ["smart_clipping/LICENSE"])
        repo_path = {n: n for n in sources}
        license_name = "smart_clipping/LICENSE"
    else:
        names = [p.split("/", 1)[1] for p in sources]
        expected = sorted(names + ["LICENSE", "blender_manifest.toml"])
        repo_path = {n: f"smart_clipping/{n}" for n in names}
        license_name = "LICENSE"

    first = package_addon.build(ROOT, out / f"{fmt}-a", fmt=fmt)
    second = package_addon.build(ROOT, out / f"{fmt}-b", fmt=fmt)
    with zipfile.ZipFile(first) as zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        license_ok = zf.read(license_name) == (ROOT / "LICENSE").read_bytes()
        code = {n: zf.read(n) for n in names if n.endswith(".py")}
        manifest = zf.read("blender_manifest.toml") if "blender_manifest.toml" in names else None
    check(f"{fmt}_zip_contents_exact", names == expected,
          f"extra {sorted(set(names) - set(expected))}, missing {sorted(set(expected) - set(names))}")
    if fmt == LEGACY:
        check("legacy_one_top_folder", {n.split("/", 1)[0] for n in names} == {"smart_clipping"})
        check("legacy_has_no_manifest", not any(n.endswith("blender_manifest.toml") for n in names))
    else:
        check("extension_files_at_root", all("/" not in n for n in names))
        check("extension_manifest_unchanged",
              manifest == (ROOT / "smart_clipping" / "blender_manifest.toml").read_bytes())
    check(f"{fmt}_license_text", license_ok)
    check(f"{fmt}_sources_unchanged",
          all(data == (ROOT / repo_path[n]).read_bytes() for n, data in code.items()))
    check(f"{fmt}_spdx_headers", all(data.startswith(SPDX) for data in code.values()),
          str([n for n, data in code.items() if not data.startswith(SPDX)]))
    check(f"{fmt}_fixed_metadata", all(i.date_time == (1980, 1, 1, 0, 0, 0)
                                       and i.external_attr == 0o644 << 16
                                       and i.create_system == 3 for i in infos))
    check(f"{fmt}_reproducible", first.read_bytes() == second.read_bytes())
    version = read_bl_info_version(ROOT)
    suffix = "-extension" if fmt == EXTENSION else ""
    check(f"{fmt}_named_after_version", first.name == f"smart_clipping-v{version}{suffix}.zip",
          first.name)
    digest = hashlib.sha256(first.read_bytes()).hexdigest()
    checksum = first.with_suffix(".sha256").read_bytes()     # as written: LF, for sha256sum -c
    check(f"{fmt}_checksum_matches", checksum == f"{digest}  {first.name}\n".encode("ascii"),
          repr(checksum))
    check(f"{fmt}_version_mismatch_refused", _refuses_version(out / f"{fmt}-c", "0.0.0", fmt))


def main() -> int:
    check_lists()
    check_manifest()

    tracked = package_addon.tracked_files(ROOT)
    stray_dir = ROOT / "smart_clipping" / "__pycache__"
    stray_files = [ROOT / "smart_clipping" / "_untracked_note.txt",
                   ROOT / "smart_clipping" / "_untracked_module.py"]
    made_cache = not stray_dir.exists()
    out = Path(tempfile.mkdtemp(prefix="smartclip-package-test-"))
    try:
        # Untracked files lying around must not end up in the ZIPs
        for path in stray_files:
            path.write_text("# not part of the add-on\n", encoding="utf-8")
        stray_dir.mkdir(exist_ok=True)
        (stray_dir / "_test.cpython-311.pyc").write_bytes(b"\0")
        for fmt in (LEGACY, EXTENSION):
            check_build(fmt, out, tracked)
    finally:
        for path in stray_files:
            path.unlink(missing_ok=True)
        (stray_dir / "_test.cpython-311.pyc").unlink(missing_ok=True)
        if made_cache:
            shutil.rmtree(stray_dir, ignore_errors=True)
        shutil.rmtree(out, ignore_errors=True)

    # Nothing the test left behind is tracked or lying around
    status = subprocess.run(["git", "status", "--porcelain", "--", "smart_clipping"],
                            cwd=ROOT, capture_output=True, text=True).stdout
    leftover = [line for line in status.splitlines() if "_untracked" in line]
    check("tree_left_clean", not leftover, "; ".join(leftover))

    print(f"[package:test] summary: passed={len(_checked) - len(_failures)} "
          f"failed={len(_failures)}")
    return 1 if _failures else 0


def _refuses_version(out, version, fmt) -> bool:
    try:
        package_addon.build(ROOT, out, version, fmt)
    except PackagingError:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
