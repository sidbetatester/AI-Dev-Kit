"""
Web interface for Project Context Kit.

Privacy-first design: the browser reads a folder the user picks and runs the
*actual* Python tools (file_loader_tool.py / project_structure_tool.py) entirely
client-side via Pyodide (WebAssembly). No project files are ever uploaded to or
stored on the server.

This server therefore does no file processing at all. It only:
  - serves the single-page UI, and
  - serves the unchanged core .py modules so the browser can load them into
    Pyodide (single source of truth — the same files the desktop app imports).

It is intentionally free of any environment-specific code; host/port come from
environment variables with sensible defaults.
"""

import os
from pathlib import Path

from flask import Flask, abort, render_template, send_from_directory

from file_loader_tool import DEFAULT_EXCLUDE_DIRS

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The core modules the browser is allowed to fetch and load into Pyodide.
CORE_MODULES = {"file_loader_tool.py", "project_structure_tool.py"}

app = Flask(__name__)


@app.route("/")
def index():
    defaults = sorted(DEFAULT_EXCLUDE_DIRS)
    return render_template(
        "index.html",
        default_excludes=", ".join(defaults),
        default_excludes_list=defaults,
    )


@app.route("/core/<path:name>")
def core(name: str):
    """Serve an unchanged core module so the browser can run it in Pyodide."""
    if name not in CORE_MODULES:
        abort(404)
    return send_from_directory(
        str(PROJECT_ROOT), name, mimetype="text/x-python"
    )


@app.after_request
def add_no_cache_headers(response):
    # Avoid stale assets while iterating in development.
    if os.environ.get("FLASK_ENV") != "production":
        response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
