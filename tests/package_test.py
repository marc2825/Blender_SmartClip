# SPDX-FileCopyrightText: 2026 marc2825
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Checks of the release ZIP's contents (plain Python 3, no Blender needed).

Usage:
  python tests/package_test.py

- Only allowlisted add-on files and the LICENSE go in; anything else that is
  tracked stops the build, and untracked files (caches, local notes, settings)
  never go in.
- The ZIP has one top folder, ``smart_clipping/``, with fixed timestamps and
  permissions, and two builds of the same sources are byte-identical with a
  matching .sha256.

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
from package_addon import PackagingError, select_entries  # noqa: E402
from versioning import read_bl_info_version  # noqa: E402

_checked = []
_failures = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip(), flush=True)
    _checked.append(name)
    if not cond:
        _failures.append(name)


def rejects(tracked) -> bool:
    try:
        select_entries(tracked)
    except PackagingError:
        return True
    return False


def main() -> int:
    # The allowlist on its own
    entries = select_entries(["smart_clipping/__init__.py", "smart_clipping/ops.py",
                              "tests/headless_test_runner.py", "README.md"])
    check("allowlist_keeps_sources_and_license",
          [name for _src, name in entries] == ["smart_clipping/LICENSE",
                                               "smart_clipping/__init__.py",
                                               "smart_clipping/ops.py"], str(entries))
    for stray in ("smart_clipping/notes.txt", "smart_clipping/.env",
                  "smart_clipping/__pycache__/ops.cpython-311.pyc",
                  "smart_clipping/.DS_Store", "smart_clipping/blender_manifest.toml"):
        check(f"rejects_tracked:{stray}",
              rejects(["smart_clipping/__init__.py", stray]))
    check("rejects_empty", rejects(["README.md"]))

    # The real build
    tracked = package_addon.tracked_files(ROOT)
    expected = sorted([p for p in tracked if p.endswith(".py")] + ["smart_clipping/LICENSE"])
    stray_dir = ROOT / "smart_clipping" / "__pycache__"
    stray_files = [ROOT / "smart_clipping" / "_untracked_note.txt",
                   ROOT / "smart_clipping" / "_untracked_module.py"]
    made_cache = not stray_dir.exists()
    out = Path(tempfile.mkdtemp(prefix="smartclip-package-test-"))
    try:
        # Untracked files lying around must not end up in the ZIP
        for path in stray_files:
            path.write_text("# not part of the add-on\n", encoding="utf-8")
        stray_dir.mkdir(exist_ok=True)
        (stray_dir / "_test.cpython-311.pyc").write_bytes(b"\0")

        first = package_addon.build(ROOT, out / "a")
        second = package_addon.build(ROOT, out / "b")
        with zipfile.ZipFile(first) as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            license_ok = zf.read("smart_clipping/LICENSE") == (ROOT / "LICENSE").read_bytes()
            sources = {n: zf.read(n) for n in names if n.endswith(".py")}
        check("zip_contents_exact", names == expected,
              f"extra {sorted(set(names) - set(expected))}, missing {sorted(set(expected) - set(names))}")
        check("one_top_folder", {n.split("/", 1)[0] for n in names} == {"smart_clipping"})
        check("license_text", license_ok)
        check("sources_unchanged", all(data == (ROOT / n).read_bytes() for n, data in sources.items()))
        spdx = (b"# SPDX-FileCopyrightText: 2026 marc2825\n"
                b"# SPDX-License-Identifier: GPL-3.0-or-later\n")
        check("spdx_headers", all(data.startswith(spdx) for data in sources.values()),
              str([n for n, data in sources.items() if not data.startswith(spdx)]))
        check("fixed_metadata", all(i.date_time == (1980, 1, 1, 0, 0, 0)
                                    and i.external_attr == 0o644 << 16
                                    and i.create_system == 3 for i in infos))
        check("reproducible", first.read_bytes() == second.read_bytes())
        version = read_bl_info_version(ROOT)
        check("named_after_version", first.name == f"smart_clipping-v{version}.zip", first.name)
        digest = hashlib.sha256(first.read_bytes()).hexdigest()
        checksum = first.with_suffix(".sha256").read_text(encoding="utf-8")
        check("checksum_matches", checksum == f"{digest}  {first.name}\n", checksum.strip())
        check("version_mismatch_refused", _refuses_version(out / "c", "0.0.0"))
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


def _refuses_version(out, version) -> bool:
    try:
        package_addon.build(ROOT, out, version)
    except PackagingError:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
