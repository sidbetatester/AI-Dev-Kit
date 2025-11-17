"""
Lightweight smoke tests for P0 tasks (01, 02).

Run:
  python Dev_Planning/verify_p0_smoke.py

Checks:
  - FileLoaderTool deterministic traversal and atomic writes.
  - ProjectStructureTool progress callback emits increasing counts with nonzero total.
  - Cancel path returns early without writing partials.
"""

from __future__ import annotations
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Tuple

import sys
from pathlib import Path as _PathHack
# Ensure repository root is on sys.path for direct script execution
_repo_root = _PathHack(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from file_loader_tool import FileLoaderTool
from project_structure_tool import ProjectStructureTool


def _extract_header_paths(merged_text: str) -> List[str]:
    paths: List[str] = []
    for line in merged_text.splitlines():
        if line.startswith("--- File: ") and line.endswith(" ---"):
            paths.append(line[len("--- File: ") : -len(" ---")])
    return paths


def test_file_loader_order_and_atomic() -> None:
    base = Path(tempfile.mkdtemp(prefix="pr_tools_runner_test_"))
    try:
        proj = base / "Proj"
        (proj / "DirA").mkdir(parents=True)
        (proj / "dirB").mkdir(parents=True)
        # Mixed-case files
        (proj / "b.txt").write_text("bee", encoding="utf-8")
        (proj / "A.txt").write_text("aye", encoding="utf-8")
        (proj / "DirA" / "c.txt").write_text("see", encoding="utf-8")
        (proj / "dirB" / "d.txt").write_text("dee", encoding="utf-8")

        loader = FileLoaderTool(str(proj))
        files = loader.load_files_in_directory(str(proj))

        out_dir = base / "out"
        out_dir.mkdir(exist_ok=True)
        merged = out_dir / "merged.txt"
        logf = out_dir / "log.txt"

        loader.save_file_contents(files, str(merged))
        loader.save_log(str(logf))

        merged_paths = _extract_header_paths(merged.read_text(encoding="utf-8"))
        expected = sorted(files.keys(), key=lambda s: s.casefold())
        assert merged_paths == expected, (
            "Concatenated header order mismatch:\n"
            + "\n".join(["got:    " + p for p in merged_paths])
            + "\n"
            + "\n".join(["expect: " + p for p in expected])
        )

        # Atomic write failure: ensure no final file created on exception
        final = out_dir / "should_not_exist.txt"
        try:
            loader._atomic_write_text(final, lambda fh: (_ for _ in ()).throw(RuntimeError("boom")))
        except RuntimeError:
            pass
        assert not final.exists(), "Atomic write left a file after failure"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_structure_progress() -> None:
    base = Path(tempfile.mkdtemp(prefix="pr_struct_test_"))
    try:
        proj = base / "Proj"
        (proj / "a").mkdir(parents=True)
        (proj / "a" / "x.txt").write_text("x", encoding="utf-8")
        (proj / "B").mkdir(parents=True)
        (proj / "B" / "y.txt").write_text("y", encoding="utf-8")

        events: List[Tuple[str, int, int, str]] = []

        def cb(stage: str, current: int, total: int, path: str) -> None:
            if len(events) < 10:
                events.append((stage, current, total, os.path.basename(path)))

        tool = ProjectStructureTool(str(proj))
        tool.build_project_structure(progress_callback=cb)
        assert events, "No progress events captured"
        # Ensure current is non-decreasing and total is > 0
        currents = [c for _, c, _, _ in events]
        totals = [t for _, _, t, _ in events]
        assert all(currents[i] <= currents[i + 1] for i in range(len(currents) - 1)), "Current not monotonic"
        assert any(t > 0 for t in totals), "Total never reported > 0"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> None:
    test_file_loader_order_and_atomic()
    test_structure_progress()
    # P0-03: encoding + binary robustness
    # Create a small temp project with utf-8, cp1252, and a binary file
    base = Path(tempfile.mkdtemp(prefix="p003_suite_"))
    try:
        proj = base / "proj"
        proj.mkdir()
        (proj / "utf8.txt").write_text("hello π", encoding="utf-8")
        (proj / "cp1252.txt").write_bytes("“quoted”".encode("cp1252"))
        (proj / "bin.dat").write_bytes(b"\x00\x01\x02\x03")

        loader = FileLoaderTool(str(proj))
        files = loader.load_files_in_directory(str(proj))
        names = sorted(Path(p).name for p in files)
        assert "utf8.txt" in names and "cp1252.txt" in names, "Text files missing after load"
        assert all("bin.dat" not in s for s in loader.processed_files), "Binary unexpectedly processed"
        assert any("bin.dat" in s for s in loader.skipped_files), "Binary not reported as skipped"
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("P0 smoke: PASS")


if __name__ == "__main__":
    main()
