"""
Web interface for the Project Tools Runner.

Wraps the existing FileLoaderTool and ProjectStructureTool so the same
file-concatenation and directory-structure logic can be used from a browser.
Users upload a project as a .zip; the app extracts it to a temporary
workspace, runs the selected tools, and returns the results as JSON.

This module is intentionally free of any environment-specific code so it can
run unchanged on any host. Host/port are read from environment variables with
sensible defaults.
"""

import io
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)

from file_loader_tool import DEFAULT_EXCLUDE_DIRS, FileLoaderTool
from project_structure_tool import ProjectStructureTool

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB compressed upload
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # 500 MB total extracted (zip-bomb guard)
MAX_ARCHIVE_ENTRIES = 50_000  # Maximum number of members in an archive
PREVIEW_CHAR_LIMIT = 200_000  # Characters of concatenated text returned inline
RESULT_TTL_SECONDS = 60 * 60  # Keep generated results for one hour

BASE_TMP = Path(tempfile.gettempdir()) / "project_tools_runner"
BASE_TMP.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _parse_excludes(raw: str, use_defaults: bool) -> Set[str]:
    """Build the exclude set from the comma-separated form field."""
    custom = {part.strip() for part in (raw or "").split(",") if part.strip()}
    if use_defaults:
        return set(DEFAULT_EXCLUDE_DIRS) | custom
    return custom


def _cleanup_old_results() -> None:
    """Remove result directories older than the configured TTL."""
    now = time.time()
    try:
        for child in BASE_TMP.iterdir():
            if not child.is_dir():
                continue
            try:
                if now - child.stat().st_mtime > RESULT_TTL_SECONDS:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
    except OSError:
        pass


def _is_within(base: Path, target: Path) -> bool:
    """True if target is base itself or a descendant of base (robust check)."""
    try:
        return os.path.commonpath([str(base), str(target)]) == str(base)
    except ValueError:
        # Raised when paths are on different drives / cannot be compared.
        return False


def _safe_extract_zip(zip_bytes: bytes, dest: Path) -> None:
    """
    Extract a zip into dest, guarding against:
    - path traversal / zip-slip (including sibling-prefix bypasses),
    - absolute or drive-prefixed member paths,
    - decompression bombs (total uncompressed size and entry count).
    """
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        infos = zf.infolist()

        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise ValueError("Archive contains too many entries.")

        total_uncompressed = sum(max(0, info.file_size) for info in infos)
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Archive is too large when uncompressed.")

        for info in infos:
            member = info.filename
            # Reject absolute paths and drive letters outright.
            if member.startswith(("/", "\\")) or (len(member) > 1 and member[1] == ":"):
                raise ValueError(f"Unsafe path in archive: {member}")
            target = (dest / member).resolve()
            if not _is_within(dest_resolved, target):
                raise ValueError(f"Unsafe path in archive: {member}")

        zf.extractall(dest)


def _find_scan_root(extracted: Path) -> Path:
    """
    If the archive contains a single top-level folder (the common case when a
    project folder is zipped), scan inside it so the tree shows the project
    name rather than a synthetic wrapper directory.
    """
    entries = [e for e in extracted.iterdir() if not e.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        default_excludes=", ".join(sorted(DEFAULT_EXCLUDE_DIRS)),
    )


@app.route("/api/analyze", methods=["POST"])
def analyze():
    _cleanup_old_results()

    upload = request.files.get("project")
    if upload is None or upload.filename == "":
        return jsonify({"error": "No file uploaded. Please choose a .zip archive."}), 400

    filename = upload.filename or ""
    if not filename.lower().endswith(".zip"):
        return jsonify({"error": "Only .zip archives are supported."}), 400

    run_loader = request.form.get("run_loader", "true") == "true"
    run_structure = request.form.get("run_structure", "true") == "true"
    use_defaults = request.form.get("use_default_excludes", "true") == "true"
    excludes = _parse_excludes(request.form.get("exclude_dirs", ""), use_defaults)

    if not run_loader and not run_structure:
        return jsonify({"error": "Select at least one tool to run."}), 400

    token = uuid.uuid4().hex
    work_dir = BASE_TMP / token
    extract_dir = work_dir / "src"
    output_dir = work_dir / "outputs"
    extract_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        zip_bytes = upload.read()
        _safe_extract_zip(zip_bytes, extract_dir)
    except (zipfile.BadZipFile, ValueError) as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        return jsonify({"error": f"Could not read archive: {exc}"}), 400

    scan_root = _find_scan_root(extract_dir)
    logs: List[str] = []

    def collect(message: str) -> None:
        logs.append(message)

    response: Dict[str, object] = {"token": token, "root_name": scan_root.name}

    if run_structure:
        structure_tool = ProjectStructureTool(
            str(scan_root), logger=collect, exclude_dirs=excludes
        )
        structure = structure_tool.build_project_structure()
        structure_tool.save_project_structure(
            str(output_dir / "project_structure.json")
        )
        response["structure"] = structure

    if run_loader:
        loader = FileLoaderTool(str(scan_root), logger=collect, exclude_dirs=excludes)
        contents = loader.load_files_in_directory(str(scan_root))
        loader.save_file_contents(
            contents, str(output_dir / "loaded_files_output.txt")
        )
        loader.save_log(str(output_dir / "file_loader_log.txt"))

        combined_path = output_dir / "loaded_files_output.txt"
        full_text = combined_path.read_text(encoding="utf-8")
        response["loader"] = {
            "processed": len(loader.processed_files),
            "skipped": len(loader.skipped_files),
            "excluded_dirs": len(loader.excluded_dirs),
            "skipped_files": loader.skipped_files,
            "preview": full_text[:PREVIEW_CHAR_LIMIT],
            "truncated": len(full_text) > PREVIEW_CHAR_LIMIT,
            "total_chars": len(full_text),
        }

    response["logs"] = logs
    response["excludes"] = sorted(excludes)
    return jsonify(response)


@app.route("/api/download/<token>/<kind>")
def download(token: str, kind: str):
    if not token.isalnum():
        abort(404)

    files = {
        "text": "loaded_files_output.txt",
        "json": "project_structure.json",
        "log": "file_loader_log.txt",
    }
    name = files.get(kind)
    if name is None:
        abort(404)

    path = BASE_TMP / token / "outputs" / name
    if not path.exists():
        abort(404)

    return send_file(str(path), as_attachment=True, download_name=name)


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=False)
