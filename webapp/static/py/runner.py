"""
Pyodide runner: invoked in the browser to drive the unchanged core tools.

The JavaScript layer populates an in-browser virtual filesystem with the files
the user picked, then calls run_tools(...). This module imports the real
FileLoaderTool / ProjectStructureTool (fetched from /core/...) and uses their
own save_* methods so the produced text/JSON/log are byte-for-byte identical to
the desktop app's output. Nothing here touches the network or the server.
"""

import json
import os
import shutil

from file_loader_tool import DEFAULT_EXCLUDE_DIRS, FileLoaderTool
from project_structure_tool import ProjectStructureTool

PREVIEW_CHAR_LIMIT = 200_000
OUTPUT_DIR = "/outputs"


def _build_excludes(exclude_csv, use_defaults):
    customs = {part.strip() for part in (exclude_csv or "").split(",") if part.strip()}
    if use_defaults:
        return set(DEFAULT_EXCLUDE_DIRS) | customs
    return customs


def _inject_excluded_dirs(node, fs_path, excludes):
    """Re-add excluded directories to the *in-memory* structure as empty,
    flagged placeholder nodes so the web UI can show/hide them (desktop parity).

    The core ProjectStructureTool prunes excluded dirs entirely, and the saved
    project_structure.json is left untouched (pruned, byte-identical to desktop).
    This web-only pass only mutates the dict returned for display; it never
    descends into excluded dirs.
    """
    try:
        entries = list(os.scandir(fs_path))
    except OSError:
        return
    subs = node.setdefault("subfolders", {})
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if entry.name in excludes:
            if entry.name not in subs:
                subs[entry.name] = {
                    "files": [],
                    "subfolders": {},
                    "excluded": True,
                }
        elif entry.name in subs:
            _inject_excluded_dirs(subs[entry.name], entry.path, excludes)


def run_tools(root, run_loader, run_structure, exclude_csv, use_defaults):
    """Run the selected tools against an already-populated virtual filesystem."""
    logs = []

    def log(message):
        logs.append(message)

    excludes = _build_excludes(exclude_csv, use_defaults)

    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    result = {
        "root_name": os.path.basename(os.path.normpath(root)),
        "logs": logs,
        "excludes": sorted(excludes),
    }

    if run_structure:
        structure_tool = ProjectStructureTool(
            root, logger=log, exclude_dirs=excludes
        )
        structure = structure_tool.build_project_structure()
        json_path = os.path.join(OUTPUT_DIR, "project_structure.json")
        structure_tool.save_project_structure(json_path)
        with open(json_path, encoding="utf-8") as fh:
            result["structure_json"] = fh.read()
        # Web-only display pass: re-add excluded dirs as empty flagged nodes so
        # the UI can show/hide them. Done AFTER saving so the downloaded JSON
        # stays pruned and byte-identical to the desktop output.
        if excludes:
            for root_node in structure.values():
                _inject_excluded_dirs(root_node, root, excludes)
        result["structure"] = structure

    if run_loader:
        loader = FileLoaderTool(root, logger=log, exclude_dirs=excludes)
        contents = loader.load_files_in_directory(root)
        text_path = os.path.join(OUTPUT_DIR, "loaded_files_output.txt")
        log_path = os.path.join(OUTPUT_DIR, "file_loader_log.txt")
        loader.save_file_contents(contents, text_path)
        loader.save_log(log_path)

        with open(text_path, encoding="utf-8") as fh:
            full_text = fh.read()
        with open(log_path, encoding="utf-8") as fh:
            log_text = fh.read()

        result["loader_text"] = full_text
        result["loader_log"] = log_text
        result["loader"] = {
            "processed": len(loader.processed_files),
            "skipped": len(loader.skipped_files),
            "excluded_dirs": len(loader.excluded_dirs),
            "skipped_files": loader.skipped_files,
            "preview": full_text[:PREVIEW_CHAR_LIMIT],
            "truncated": len(full_text) > PREVIEW_CHAR_LIMIT,
            "total_chars": len(full_text),
        }

    return json.dumps(result)
