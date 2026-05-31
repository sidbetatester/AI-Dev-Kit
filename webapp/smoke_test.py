"""
Smoke test for the Project Context Kit web app.

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

    # Discover every Python module in the project root so a newly added
    # sensitive file is caught automatically: anything not in CORE_MODULES
    # must be unreachable (404), the two core modules must be served (200).
    root_modules = sorted(p.name for p in ROOT.glob("*.py"))
    check(len(root_modules) > 0, "found at least one .py module in project root")

    for name in root_modules:
        if name in CORE_MODULES:
            resp = client.get(f"/core/{name}")
            check(
                resp.status_code == 200,
                f"core module GET /core/{name} returns 200",
            )
            # Privacy/parity promise: the browser must run the *exact same*
            # bytes the desktop app imports. A 200 alone is not enough — assert
            # the served body is byte-for-byte identical to the on-disk module.
            on_disk = (ROOT / name).read_bytes()
            check(
                resp.data == on_disk,
                f"core module GET /core/{name} is byte-for-byte identical to disk",
            )
        else:
            check(
                client.get(f"/core/{name}").status_code == 404,
                f"non-core module GET /core/{name} returns 404",
            )

    # Every allowlisted core module must actually exist in the root.
    for name in CORE_MODULES:
        check(name in root_modules, f"{name} (allowlisted) exists in project root")


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
