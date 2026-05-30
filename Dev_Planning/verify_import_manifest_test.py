"""
Tests for verify_import_manifest.py.

The import safety check is normally exercised only by manual runs against a real
upstream clone. These tests pin down its comparison logic against small, local
fixtures so future edits cannot silently break it:

  - MISSING is reported when a tracked source file is absent from the work tree.
  - DIFFERING is reported when content genuinely differs.
  - Text files that differ only by CRLF vs LF line endings are treated as equal.
  - Binary files are compared byte-for-byte (no line-ending normalization).
  - Excluded paths/globs are never flagged, even when missing or differing.
  - The CLI exits 0 on a clean import and 1 when something is missing/differing.

Run:
  python Dev_Planning/verify_import_manifest_test.py

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent

# Import the module under test by path so this works regardless of cwd.
_spec = importlib.util.spec_from_file_location(
    "verify_import_manifest", _THIS_DIR / "verify_import_manifest.py"
)
assert _spec and _spec.loader, "Could not locate verify_import_manifest.py"
vim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vim)


def _run_git(args, cwd: Path) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}"
        )


def _init_source_repo(root: Path) -> None:
    """git init *root* and commit whatever files already exist under it."""
    root.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-q"], cwd=root)
    _run_git(["config", "user.email", "test@example.com"], cwd=root)
    _run_git(["config", "user.name", "Test"], cwd=root)
    _run_git(["add", "-A"], cwd=root)
    _run_git(["commit", "-q", "-m", "fixture"], cwd=root)


def test_is_excluded_patterns() -> None:
    """Directory prefixes, exact paths, and globs all match correctly."""
    pats = ["webapp/", ".gitignore", "*.log"]
    assert vim.is_excluded("webapp/static/app.js", pats)
    assert vim.is_excluded("webapp", pats)  # the dir itself
    assert vim.is_excluded(".gitignore", pats)
    assert vim.is_excluded("logs/run.log", pats)
    assert not vim.is_excluded("webapps/other.txt", pats)  # not the prefix
    assert not vim.is_excluded("src/main.py", pats)


def test_content_hash_crlf_vs_binary() -> None:
    """Text normalizes CRLF/CR -> LF; binary content is hashed as-is."""
    assert vim.content_hash(b"a\r\nb\r\n") == vim.content_hash(b"a\nb\n")
    assert vim.content_hash(b"a\rb\r") == vim.content_hash(b"a\nb\n")
    # NUL byte => treated as binary => CRLF is significant => hashes differ.
    assert vim.content_hash(b"\x00a\r\nb") != vim.content_hash(b"\x00a\nb")


def test_compare_reports_missing_differing_and_honors_rules() -> None:
    base = Path(tempfile.mkdtemp(prefix="import_verify_test_"))
    try:
        source = base / "source"
        work = base / "work"

        # --- Source files (the upstream we are importing from) ---
        (source).mkdir(parents=True)
        (source / "same.txt").write_text("hello\nworld\n", encoding="utf-8")
        # LF in source; will be CRLF in the work tree (must compare equal).
        (source / "crlf.txt").write_bytes(b"line1\nline2\n")
        # Identical binary in both -> not flagged.
        (source / "img.bin").write_bytes(b"\x00\x01\x02\x03\xff")
        # Binary differing only by a CR -> must be flagged (byte compare).
        (source / "raw.bin").write_bytes(b"\x00data\r\nend")
        # Genuinely different text -> DIFFERING.
        (source / "changed.txt").write_text("original\n", encoding="utf-8")
        # Present in source, absent from work -> MISSING.
        (source / "dropped.txt").write_text("gone\n", encoding="utf-8")
        # Excluded by default-exclude glob even though it differs/missing.
        (source / "webapp").mkdir()
        (source / "webapp" / "local.js").write_text("x=1\n", encoding="utf-8")
        # Excluded by a caller-supplied glob; missing from work but ignored.
        (source / "notes.tmp").write_text("scratch\n", encoding="utf-8")

        _init_source_repo(source)

        # --- Work tree (our local copy after a copy-based import) ---
        work.mkdir(parents=True)
        (work / "same.txt").write_text("hello\nworld\n", encoding="utf-8")
        # CRLF version of the same logical text.
        (work / "crlf.txt").write_bytes(b"line1\r\nline2\r\n")
        (work / "img.bin").write_bytes(b"\x00\x01\x02\x03\xff")
        # Same text but LF instead of CRLF -> binary byte compare flags it.
        (work / "raw.bin").write_bytes(b"\x00data\nend")
        (work / "changed.txt").write_text("EDITED\n", encoding="utf-8")
        # dropped.txt intentionally NOT created -> MISSING.
        # webapp/ intentionally NOT created -> excluded, must not be MISSING.
        # notes.tmp intentionally NOT created -> excluded by caller glob.

        excludes = list(vim.DEFAULT_EXCLUDES) + ["*.tmp"]
        missing, differing, checked = vim.compare(source, work, excludes)

        assert missing == ["dropped.txt"], f"missing={missing}"
        assert differing == ["changed.txt", "raw.bin"], f"differing={differing}"
        # same/crlf/img are equal; changed/raw present-but-differ; all compared.
        assert checked == [
            "changed.txt",
            "crlf.txt",
            "img.bin",
            "raw.bin",
            "same.txt",
        ], f"checked={checked}"
        # Excluded paths never appear anywhere.
        for rel in ("webapp/local.js", "notes.tmp"):
            assert rel not in missing and rel not in differing and rel not in checked
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_cli_exit_codes() -> None:
    """End-to-end: main() returns 1 on a bad import and 0 on a clean one."""
    base = Path(tempfile.mkdtemp(prefix="import_verify_cli_"))
    try:
        source = base / "source"
        source.mkdir(parents=True)
        (source / "a.txt").write_text("alpha\n", encoding="utf-8")
        (source / "b.txt").write_text("beta\n", encoding="utf-8")
        _init_source_repo(source)

        # Bad work tree: b.txt missing -> expect exit code 1.
        bad = base / "bad"
        bad.mkdir()
        (bad / "a.txt").write_text("alpha\n", encoding="utf-8")
        rc_bad = vim.main(
            [
                "--source-dir",
                str(source),
                "--work-dir",
                str(bad),
                "--no-default-excludes",
            ]
        )
        assert rc_bad == 1, f"expected FAIL exit 1, got {rc_bad}"

        # Good work tree: identical content -> expect exit code 0.
        good = base / "good"
        good.mkdir()
        (good / "a.txt").write_text("alpha\n", encoding="utf-8")
        (good / "b.txt").write_text("beta\n", encoding="utf-8")
        rc_good = vim.main(
            [
                "--source-dir",
                str(source),
                "--work-dir",
                str(good),
                "--no-default-excludes",
            ]
        )
        assert rc_good == 0, f"expected PASS exit 0, got {rc_good}"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> None:
    test_is_excluded_patterns()
    test_content_hash_crlf_vs_binary()
    test_compare_reports_missing_differing_and_honors_rules()
    test_cli_exit_codes()
    print("import manifest tests: PASS")


if __name__ == "__main__":
    main()
