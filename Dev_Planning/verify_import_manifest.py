"""
verify_import_manifest.py

Safety check for copy-based imports.

Because real `git merge` is blocked in some environments, the latest upstream
code is sometimes brought into this working tree by *copying files* from a fresh
clone of a source branch. That process risks silently omitting a new file or
leaving an old (stale) copy behind. This script makes those imports verifiable:
it clones (or reuses) the source branch, then compares every tracked source
file against the working tree and reports anything MISSING or DIFFERING.

Run it BEFORE accepting a copy-based import:

  # Clone the upstream branch and compare against the current working tree
  python Dev_Planning/verify_import_manifest.py --branch main

  # Reuse an existing clone instead of cloning again
  python Dev_Planning/verify_import_manifest.py --source-dir /tmp/AI-Dev-Kit

Exit status:
  0  every importable source file is present and identical in the working tree
  1  one or more files are MISSING or DIFFERING
  2  a setup/usage error (e.g. clone failed, source dir invalid)

Notes:
  - Only files git tracks in the source branch are considered, so anything the
    source ignores is automatically out of scope.
  - Text files are compared after normalizing CRLF -> LF so line-ending policy
    differences are not reported as false positives. Binary files are compared
    byte-for-byte.
    files that are reconciled by hand on import (.gitignore, requirements.txt)
    are excluded by default; override with --exclude / --no-default-excludes.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# Upstream repository used when --url is not provided and no `origin` remote
# can be detected.
DEFAULT_REPO_URL = "https://github.com/sidbetatester/AI-Dev-Kit"

# Paths that legitimately live only in this working tree, or are reconciled by
# hand during an import, and therefore must not be flagged as missing/differing.
# Entries ending in "/" match a directory and everything under it; other entries
# are matched against the relative POSIX path and as fnmatch globs.
DEFAULT_EXCLUDES: Tuple[str, ...] = (
    # Browser web app added locally (not part of the upstream source branch).
    "webapp/",
    ".upm/",
    ".config/",
    ".agents/",
    ".local/",
    ".cache/",
    ".breakpoints",
    ".gitignore",
    "requirements.txt",
)


def _run_git(args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run a git command, returning (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def detect_origin_url(repo_root: Path) -> Optional[str]:
    """Return the working tree's `origin` remote URL, if any."""
    code, out, _ = _run_git(["remote", "get-url", "origin"], cwd=repo_root)
    if code == 0:
        url = out.strip()
        return url or None
    return None


def clone_source(url: str, branch: str) -> Path:
    """Shallow-clone *branch* of *url* into a temp dir; return the clone path."""
    dest = Path(tempfile.mkdtemp(prefix="import_verify_"))
    code, _, err = _run_git(
        ["clone", "--depth", "1", "--branch", branch, url, str(dest)]
    )
    if code != 0:
        raise RuntimeError(f"git clone failed for {url}@{branch}:\n{err.strip()}")
    return dest


def list_tracked_files(repo: Path) -> List[str]:
    """Return git-tracked files of *repo* as relative POSIX paths."""
    code, out, err = _run_git(["ls-files"], cwd=repo)
    if code != 0:
        raise RuntimeError(f"git ls-files failed in {repo}:\n{err.strip()}")
    return [line for line in out.splitlines() if line]


def is_excluded(rel_path: str, patterns: Iterable[str]) -> bool:
    """True if *rel_path* matches any exclusion pattern."""
    for pat in patterns:
        if pat.endswith("/"):
            prefix = pat.rstrip("/")
            if rel_path == prefix or rel_path.startswith(prefix + "/"):
                return True
        elif rel_path == pat or fnmatch.fnmatch(rel_path, pat):
            return True
    return False


def _looks_binary(data: bytes) -> bool:
    """Heuristic: treat content with a NUL byte as binary."""
    return b"\x00" in data[:8192]


def content_hash(data: bytes) -> str:
    """SHA-256 of *data*, normalizing CRLF/CR -> LF for text content."""
    if not _looks_binary(data):
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def compare(
    source_root: Path,
    work_root: Path,
    excludes: Iterable[str],
) -> Tuple[List[str], List[str], List[str]]:
    """
    Compare tracked source files against the working tree.

    Returns (missing, differing, checked):
      missing   - tracked in source (not excluded) but absent from working tree
      differing - present in both but content differs
      checked   - source files actually compared (present in both)
    """
    excludes = list(excludes)
    missing: List[str] = []
    differing: List[str] = []
    checked: List[str] = []

    for rel in list_tracked_files(source_root):
        if is_excluded(rel, excludes):
            continue
        work_file = work_root / rel
        if not work_file.exists():
            missing.append(rel)
            continue
        src_bytes = (source_root / rel).read_bytes()
        work_bytes = work_file.read_bytes()
        checked.append(rel)
        if content_hash(src_bytes) != content_hash(work_bytes):
            differing.append(rel)

    return sorted(missing), sorted(differing), sorted(checked)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a copy-based import did not miss or stale any file.",
    )
    parser.add_argument(
        "--url",
        help="Source repository URL to clone (default: working tree's origin, "
        f"else {DEFAULT_REPO_URL}).",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Source branch to clone and compare against (default: main).",
    )
    parser.add_argument(
        "--source-dir",
        help="Reuse an existing clone/checkout instead of cloning. Mutually "
        "exclusive with --url/--branch cloning.",
    )
    parser.add_argument(
        "--work-dir",
        default=".",
        help="Working tree to verify (default: current directory).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Additional path/glob to exclude (repeatable). Dir prefixes end "
        "with '/'.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        "reconciled files).",
    )
    args = parser.parse_args(argv)

    work_root = Path(args.work_dir).resolve()
    if not work_root.is_dir():
        print(f"ERROR: working dir not found: {work_root}", file=sys.stderr)
        return 2

    excludes: List[str] = []
    if not args.no_default_excludes:
        excludes.extend(DEFAULT_EXCLUDES)
    excludes.extend(args.exclude)

    cleanup_dir: Optional[Path] = None
    try:
        if args.source_dir:
            source_root = Path(args.source_dir).resolve()
            if not source_root.is_dir():
                print(
                    f"ERROR: source dir not found: {source_root}", file=sys.stderr
                )
                return 2
            print(f"Source:  {source_root} (existing checkout)")
        else:
            url = args.url or detect_origin_url(work_root) or DEFAULT_REPO_URL
            print(f"Source:  {url}@{args.branch} (cloning...)")
            source_root = clone_source(url, args.branch)
            cleanup_dir = source_root

        print(f"Working: {work_root}")
        print(f"Excludes: {', '.join(excludes) if excludes else '(none)'}")
        print("-" * 60)

        missing, differing, checked = compare(source_root, work_root, excludes)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if cleanup_dir is not None:
            import shutil

            shutil.rmtree(cleanup_dir, ignore_errors=True)

    print(f"Checked {len(checked)} importable file(s).")
    if missing:
        print(f"\nMISSING ({len(missing)}) — in source but not in working tree:")
        for rel in missing:
            print(f"  - {rel}")
    if differing:
        print(f"\nDIFFERING ({len(differing)}) — content does not match source:")
        for rel in differing:
            print(f"  - {rel}")

    if missing or differing:
        print("\nRESULT: FAIL — import is incomplete or stale (see above).")
        return 1

    print("\nRESULT: PASS — every importable source file is present and identical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
