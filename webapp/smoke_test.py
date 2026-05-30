"""
Smoke test for the Project Tools Runner web app.

Proves the web re-verification objective without uploading anything:

  1. The ``/core`` allowlist serves ONLY the two shared core modules (200) and
     rejects every other module, including the desktop-only ones (404).
  2. The Pyodide runner logic still matches the current core module APIs and
     produces correct processed/skipped/excluded counts plus valid structure
     JSON (empty dirs preserved, excluded dirs pruned, new default excludes
     present).

Run:  python webapp/smoke_test.py
Exits non-zero on the first failure.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "webapp" / "static" / "py"))

import runner  # noqa: E402  (path set up above)
from webapp.app import CORE_MODULES, app  # noqa: E402


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"ok: {msg}")


def test_core_allowlist() -> None:
    client = app.test_client()
    check(client.get("/").status_code == 200, "GET / returns 200")

    for name in ("file_loader_tool.py", "project_structure_tool.py"):
        check(name in CORE_MODULES, f"{name} is in the /core allowlist")
        check(
            client.get(f"/core/{name}").status_code == 200,
            f"GET /core/{name} returns 200",
        )

    # Desktop-only / server modules must never be reachable from the browser.
    for name in (
        "app.py",
        "token_encryption.py",
        "git_remote_tool.py",
        "tool_runner_ui.py",
    ):
        check(name not in CORE_MODULES, f"{name} is NOT in the /core allowlist")
        check(
            client.get(f"/core/{name}").status_code == 404,
            f"GET /core/{name} returns 404",
        )


def test_runner_logic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "sample"
        (base / "pkg" / "sub").mkdir(parents=True)
        (base / "node_modules" / "dep").mkdir(parents=True)
        (base / "empty").mkdir(parents=True)
        (base / "pkg" / "main.py").write_text('print("hi")\n')
        (base / "README.md").write_text("# title\n")
        (base / "pkg" / "sub" / "util.py").write_text("a = 1\n")
        (base / "node_modules" / "dep" / "index.js").write_text("excluded\n")
        (base / "pkg" / "blob.bin").write_bytes(b"\x00\x01\x02bin\x00")

        runner.OUTPUT_DIR = os.path.join(tmp, "outputs")
        out = json.loads(runner.run_tools(str(base), True, True, "", True))

        loader = out["loader"]
        check(loader["processed"] == 3, "3 text files processed")
        check(loader["skipped"] == 1, "1 binary file skipped")
        check(loader["excluded_dirs"] == 1, "1 excluded dir (node_modules)")

        top = json.loads(out["structure_json"])["sample"]
        check("empty" in top["subfolders"], "empty dir preserved in structure")
        check(
            "node_modules" not in top["subfolders"],
            "node_modules pruned from structure",
        )
        check("htmlcov" in out["excludes"], "new default exclude (htmlcov) present")


if __name__ == "__main__":
    test_core_allowlist()
    test_runner_logic()
    print("ALL SMOKE TESTS PASSED")
