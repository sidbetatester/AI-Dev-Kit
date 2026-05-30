"""
Tests for the MCP server's tool logic (mcp_server pure functions).

Exercises get_project_structure, load_files, and get_file against a real
temporary tree, asserting the jail, secret filtering, exclude dirs, and caps all
take effect. Also verifies the FastMCP server builds and registers its tools
(skipped gracefully if the optional ``mcp`` package is absent).

Run:  python mcp_server_test.py
Exits non-zero on the first failed assertion.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mcp_security as sec  # noqa: E402
import mcp_server as srv  # noqa: E402


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


def _make_tree(tmp: str) -> Path:
    root = Path(tmp) / "project"
    (root / "pkg").mkdir(parents=True)
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "pkg" / "main.py").write_text('print("hi")\n')
    (root / "README.md").write_text("# title\n")
    (root / ".env").write_text("API_KEY=supersecret\n")
    (root / "server.pem").write_text("-----BEGIN KEY-----\n")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02bin\x00")
    (root / "node_modules" / "dep" / "index.js").write_text("excluded\n")
    return root


def test_structure_prunes_secrets_and_excludes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = sec.build_policy(roots=[str(root)])
        tree = json.loads(srv.get_project_structure(policy, str(root)))["project"]
        names = {f["name"] for f in tree["files"]}
        check("README.md" in names, "README.md present in structure")
        check(".env" not in names, ".env pruned from structure")
        check("server.pem" not in names, "server.pem pruned from structure")
        check("node_modules" not in tree["subfolders"], "node_modules excluded")
        check("pkg" in tree["subfolders"], "pkg subfolder present")


def test_load_files_filters_and_caps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = sec.build_policy(roots=[str(root)])
        out = srv.load_files(policy, str(root))
        check("README.md" in out, "README.md content included")
        check("main.py" in out, "pkg/main.py content included")
        check("supersecret" not in out, ".env contents never returned")
        check("BEGIN KEY" not in out, "server.pem contents never returned")
        check("excluded" not in out, "node_modules contents excluded")
        check("omitted_secret=2" in out, "summary reports 2 secret files omitted")

        # Per-file cap: a large file is omitted.
        (root / "big.txt").write_text("x" * 5000)
        tight = sec.build_policy(roots=[str(root)], max_file_bytes=1000)
        out2 = tight.is_secret_file  # noqa: F841 (touch to keep linters quiet)
        loaded = srv.load_files(tight, str(root))
        check("big.txt" not in loaded, "file over per-file cap is omitted")
        check("omitted_too_large=1" in loaded, "summary reports oversize omission")


def test_load_files_blocks_symlink_escape() -> None:
    if not hasattr(__import__("os"), "symlink"):
        print("ok: symlinks unsupported on platform, skipping escape test")
        return
    import os as _os
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        # A sensitive file OUTSIDE the jail, linked to from inside it.
        outside = Path(tmp) / "outside_secret.txt"
        outside.write_text("TOP_SECRET_OUTSIDE_JAIL\n")
        link = root / "pkg" / "innocuous.txt"
        try:
            _os.symlink(str(outside), str(link))
        except (OSError, NotImplementedError):
            print("ok: cannot create symlink here, skipping escape test")
            return
        policy = sec.build_policy(roots=[str(root)])
        out = srv.load_files(policy, str(root))
        check("TOP_SECRET_OUTSIDE_JAIL" not in out,
              "load_files never returns content of an out-of-jail symlink")
        check("omitted_outside_jail=1" in out,
              "summary reports the jail-escaping symlink omission")
        # read_file must also refuse the escaping link.
        expect_error(
            lambda: srv.get_file(policy, str(link)),
            "get_file refuses an in-tree symlink that escapes the jail",
        )


def test_depth_cap_enforced() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "deep"
        deep = root / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (root / "top.txt").write_text("top\n")
        (deep / "buried.txt").write_text("buried\n")
        policy = sec.build_policy(roots=[str(root)], max_depth=2)
        out = srv.load_files(policy, str(root))
        check("top" in out, "shallow file within depth cap is included")
        check("buried" not in out, "file deeper than max_depth is omitted")
        check("omitted_too_deep=" in out and "omitted_too_deep=0" not in out,
              "summary reports a too-deep omission")
        tree = json.loads(srv.get_project_structure(policy, str(root)))["deep"]
        # depth cap = 2 -> a (1), a/b (2) kept; a/b/c (3) pruned.
        a = tree["subfolders"]["a"]
        check("b" in a["subfolders"], "structure keeps folders within depth cap")
        check("c" not in a["subfolders"]["b"]["subfolders"],
              "structure prunes folders beyond depth cap")


def test_no_stdout_pollution() -> None:
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)  # contains blob.bin -> triggers a WARNING log
        policy = sec.build_policy(roots=[str(root)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            srv.load_files(policy, str(root))
            srv.get_project_structure(policy, str(root))
        check(buf.getvalue() == "",
              "tool logging never writes to stdout (MCP protocol channel)")


def test_get_file_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = sec.build_policy(roots=[str(root)])
        check(
            srv.get_file(policy, str(root / "README.md")) == "# title\n",
            "get_file returns text content",
        )
        expect_error(
            lambda: srv.get_file(policy, str(root / ".env")),
            "get_file refuses a secret file",
        )
        expect_error(
            lambda: srv.get_file(policy, str(root / "blob.bin")),
            "get_file refuses a binary file",
        )
        expect_error(
            lambda: srv.get_file(policy, str(root / "pkg")),
            "get_file refuses a directory",
        )
        expect_error(
            lambda: srv.get_file(policy, "/etc/hostname"),
            "get_file refuses a path outside the jail",
        )


def test_roots_info() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = sec.build_policy(roots=[str(root)], max_files=7)
        info = srv.roots_info(policy)
        check(info["limits"]["max_files"] == 7, "roots_info reports max_files")
        check(
            any(str(root) == r for r in info["allowed_roots"]),
            "roots_info lists the allowed root",
        )


def test_build_server_registers_tools() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = sec.build_policy(roots=[str(root)])
        try:
            import mcp  # noqa: F401
        except ImportError:
            print("ok: mcp package absent, skipping server-build check")
            return
        import asyncio

        server = srv.build_server(policy)
        tools = asyncio.run(server.list_tools())
        tool_names = {t.name for t in tools}
        for expected in ("list_allowed_roots", "project_structure",
                         "load_directory", "read_file"):
            check(expected in tool_names, f"tool registered: {expected}")


def test_policy_from_args() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_tree(tmp)
        policy = srv.policy_from_args(["--root", str(root), "--max-files", "9"])
        check(policy.max_files == 9, "policy_from_args parses --max-files")
        check(len(policy.allowed_roots) == 1, "policy_from_args parses --root")


if __name__ == "__main__":
    test_structure_prunes_secrets_and_excludes()
    test_load_files_filters_and_caps()
    test_load_files_blocks_symlink_escape()
    test_depth_cap_enforced()
    test_no_stdout_pollution()
    test_get_file_rules()
    test_roots_info()
    test_build_server_registers_tools()
    test_policy_from_args()
    print("mcp server tests: PASS")
