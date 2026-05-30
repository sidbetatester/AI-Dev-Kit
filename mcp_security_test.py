"""
Tests for mcp_security.AccessPolicy.

Verifies the jail (allowed-roots containment, traversal + symlink escapes),
secret-file detection, and env/CLI parsing. Pure stdlib; no mcp dependency.

Run:  python mcp_security_test.py
Exits non-zero on the first failed assertion.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_security as sec  # noqa: E402


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"ok: {msg}")


def expect_error(fn, msg: str) -> None:
    try:
        fn()
    except sec.AccessError:
        print(f"ok: {msg}")
        return
    print(f"FAIL: {msg} (expected AccessError)")
    sys.exit(1)


def test_requires_roots() -> None:
    expect_error(lambda: sec.build_policy(roots=[]), "empty roots is rejected")
    expect_error(
        lambda: sec.policy_from_env({}),
        "policy_from_env with no env var is rejected",
    )


def test_jail_containment_and_traversal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        (root / "sub").mkdir(parents=True)
        (root / "sub" / "a.txt").write_text("hi\n")
        outside = Path(tmp) / "secret_zone"
        outside.mkdir()
        (outside / "leak.txt").write_text("nope\n")

        policy = sec.build_policy(roots=[str(root)])

        inside = policy.resolve_within_jail(str(root / "sub" / "a.txt"))
        check(inside.name == "a.txt", "path inside the root resolves")

        expect_error(
            lambda: policy.resolve_within_jail(str(outside / "leak.txt")),
            "a sibling directory outside the root is blocked",
        )
        expect_error(
            lambda: policy.resolve_within_jail(str(root / ".." / "secret_zone" / "leak.txt")),
            "../ traversal out of the root is blocked",
        )
        expect_error(lambda: policy.resolve_within_jail(""), "empty path is rejected")


def test_symlink_escape_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        root.mkdir()
        outside = Path(tmp) / "outside"
        outside.mkdir()
        (outside / "target.txt").write_text("secret\n")
        link = root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            print("ok: symlink unsupported here, skipping symlink-escape check")
            return

        policy = sec.build_policy(roots=[str(root)])
        expect_error(
            lambda: policy.resolve_within_jail(str(link / "target.txt")),
            "symlink pointing outside the root is blocked (realpath jail)",
        )


def test_secret_detection() -> None:
    policy = sec.build_policy(roots=[os.getcwd()])
    for name in (".env", ".env.production", "id_rsa", "server.pem", "app.key",
                 ".npmrc", "credentials.json", "my.secret", "store.keystore",
                 "SECRETS.json", "Backup.PFX"):
        check(policy.is_secret_file(name), f"{name} flagged as secret")
    for name in ("main.py", "README.md", "config.yaml", "index.js", "data.csv"):
        check(not policy.is_secret_file(name), f"{name} not flagged as secret")
    # base name only — directory components must not matter
    check(policy.is_secret_file("/home/u/proj/.env"), "full path to .env flagged")


def test_exclude_dirs_merge() -> None:
    policy = sec.build_policy(roots=[os.getcwd()], extra_excludes={"my_cache"})
    check("node_modules" in policy.exclude_dirs, "core default exclude present")
    check("htmlcov" in policy.exclude_dirs, "new core default exclude present")
    check("my_cache" in policy.exclude_dirs, "caller extra exclude merged in")


def test_env_parsing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "a"
        b = Path(tmp) / "b"
        a.mkdir()
        b.mkdir()
        env = {
            sec.ENV_ROOTS: f"{a}{os.pathsep}{b}",
            sec.ENV_MAX_FILES: "5",
            sec.ENV_EXTRA_EXCLUDES: "foo,bar",
        }
        policy = sec.policy_from_env(env)
        check(len(policy.allowed_roots) == 2, "two roots parsed from env")
        check(policy.max_files == 5, "max_files parsed from env")
        check({"foo", "bar"}.issubset(policy.exclude_dirs), "comma excludes parsed")
        expect_error(
            lambda: sec.policy_from_env({sec.ENV_ROOTS: str(a), sec.ENV_MAX_FILES: "0"}),
            "non-positive cap is rejected",
        )


if __name__ == "__main__":
    test_requires_roots()
    test_jail_containment_and_traversal()
    test_symlink_escape_blocked()
    test_secret_detection()
    test_exclude_dirs_merge()
    test_env_parsing()
    print("mcp security tests: PASS")
