"""
Local, read-only MCP server exposing the Project Tools Runner core tools.

It wraps the unchanged core modules (``FileLoaderTool`` and
``ProjectStructureTool``) as Model Context Protocol tools so an AI agent running
on the user's own machine can understand and read a codebase. It runs over
stdio: nothing is hosted, no account is required, and no data leaves the user's
system through this server.

Tools exposed
-------------
* ``list_allowed_roots`` — report which directories the server may read and the
  active limits.
* ``get_project_structure`` — nested JSON tree of a directory (metadata only).
* ``load_files`` — aggregated text of readable files under a directory.
* ``get_file`` — contents of a single text file.

All paths are confined to the configured allowed roots, secret-looking files are
never returned, and per-call size/depth caps apply. See ``mcp_security.py``.

Usage
-----
    python mcp_server.py --root /path/to/project [--root /another]
    # or
    TOOLS_MCP_ALLOWED_ROOTS=/path/to/project python mcp_server.py

Wire the command above into your MCP-capable client (e.g. Claude Desktop,
an IDE agent) as a local stdio server.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from file_loader_tool import FileLoaderTool
from mcp_security import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_TOTAL_BYTES,
    AccessError,
    AccessPolicy,
    build_policy,
    policy_from_env,
)
from project_structure_tool import ProjectStructureTool

SERVER_NAME = "project-tools-runner"


def _stderr_logger(message: str) -> None:
    """
    Logger for the core tools.

    Critically, core tools default to ``print`` (stdout). In a stdio MCP server
    stdout is the protocol channel, so any stray write corrupts it. Route all
    tool logging to stderr instead.
    """
    print(message, file=sys.stderr)


# ---------------------------------------------------------------------------
# Pure functions (no MCP dependency) — these hold the real logic and are unit
# tested directly. The MCP tool wrappers below are thin adapters over them.
# ---------------------------------------------------------------------------

def roots_info(policy: AccessPolicy) -> Dict[str, object]:
    """Describe the active policy: roots and caps."""
    return {
        "allowed_roots": [str(r) for r in policy.allowed_roots],
        "limits": {
            "max_files": policy.max_files,
            "max_total_bytes": policy.max_total_bytes,
            "max_file_bytes": policy.max_file_bytes,
            "max_depth": policy.max_depth,
        },
        "excluded_dir_names": sorted(policy.exclude_dirs),
        "secret_file_patterns": sorted(policy.secret_patterns),
    }


def _depth_below(base: Path, file_path: str) -> int:
    """Directory levels of ``file_path`` below ``base`` (a file directly in ``base`` == 0)."""
    try:
        rel = Path(file_path).relative_to(base)
    except ValueError:
        return 0
    return max(len(rel.parts) - 1, 0)


def _prune_structure(node: dict, policy: AccessPolicy, depth: int = 0) -> dict:
    """
    Copy a structure node, dropping secret-looking files and capping recursion
    at ``policy.max_depth`` levels below the requested directory.
    """
    files = [f for f in node.get("files", []) if not policy.is_secret_file(f.get("name", ""))]
    subfolders: Dict[str, dict] = {}
    if depth < policy.max_depth:
        for name, child in node.get("subfolders", {}).items():
            subfolders[name] = _prune_structure(child, policy, depth + 1)
    return {"files": files, "subfolders": subfolders}


def get_project_structure(policy: AccessPolicy, path: str) -> str:
    """Build the nested JSON structure for ``path`` (metadata only).

    The core structure tool already ignores symlinks (``follow_symlinks=False``),
    so traversal cannot escape the jail; here we additionally drop secret-looking
    files and cap the depth.
    """
    target = policy.resolve_within_jail(path)
    if not target.is_dir():
        raise AccessError(f"Not a directory: {path}")
    tool = ProjectStructureTool(
        str(target), logger=_stderr_logger, exclude_dirs=policy.exclude_dirs
    )
    structure = tool.build_project_structure()
    pruned = {name: _prune_structure(node, policy) for name, node in structure.items()}
    return json.dumps(pruned, indent=2)


def load_files(policy: AccessPolicy, path: str) -> str:
    """
    Aggregate readable text files under ``path`` into one string, dropping
    secret files and honoring the size/count caps.
    """
    target = policy.resolve_within_jail(path)
    if not target.is_dir():
        raise AccessError(f"Not a directory: {path}")

    loader = FileLoaderTool(
        str(target), logger=_stderr_logger, exclude_dirs=policy.exclude_dirs
    )
    contents = loader.load_files_in_directory(str(target))

    # Deterministic order; drop secrets, jail escapees, too-deep, and over-large
    # files; enforce caps.
    selected: List[str] = []
    included = 0
    omitted_secret = 0
    omitted_outside_jail = 0
    omitted_too_deep = 0
    omitted_too_large = 0
    omitted_cap = 0
    total_bytes = 0
    truncated = False

    for file_path in sorted(contents.keys(), key=lambda s: s.casefold()):
        name = os.path.basename(file_path)
        if policy.is_secret_file(name):
            omitted_secret += 1
            continue
        # Re-validate containment per file: the core walk does not follow
        # directory symlinks, but a symlinked *file* inside a root could still
        # resolve to data outside the jail. Reject anything that escapes.
        if not policy.is_within_roots(file_path):
            omitted_outside_jail += 1
            continue
        if _depth_below(target, file_path) > policy.max_depth:
            omitted_too_deep += 1
            continue
        body = contents[file_path]
        size = len(body.encode("utf-8", errors="replace"))
        if size > policy.max_file_bytes:
            omitted_too_large += 1
            continue
        if included >= policy.max_files or total_bytes + size > policy.max_total_bytes:
            omitted_cap += 1
            truncated = True
            continue
        selected.append(f"--- File: {file_path} ---\n{body}\n")
        included += 1
        total_bytes += size

    header_lines = [
        f"# load_files for {target}",
        f"# included={included} bytes={total_bytes} "
        f"skipped_binary_or_unreadable={len(loader.skipped_files)} "
        f"omitted_secret={omitted_secret} omitted_outside_jail={omitted_outside_jail} "
        f"omitted_too_deep={omitted_too_deep} omitted_too_large={omitted_too_large} "
        f"omitted_over_cap={omitted_cap} truncated={truncated}",
        "",
    ]
    return "\n".join(header_lines) + "\n".join(selected)


def get_file(policy: AccessPolicy, path: str) -> str:
    """Return the text contents of a single file within the jail."""
    target = policy.resolve_within_jail(path)
    if not target.is_file():
        raise AccessError(f"Not a file: {path}")
    if policy.is_secret_file(target.name):
        raise AccessError(f"Refusing to read a secret-looking file: {target.name}")
    size = target.stat().st_size
    if size > policy.max_file_bytes:
        raise AccessError(
            f"File is larger than the per-file cap "
            f"({size} > {policy.max_file_bytes} bytes): {path}"
        )
    data = target.read_bytes()
    if b"\x00" in data:
        raise AccessError(f"Refusing to return a binary file: {path}")
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# MCP wiring
# ---------------------------------------------------------------------------

def build_server(policy: AccessPolicy):
    """Create a FastMCP server with the tools registered against ``policy``."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)

    @server.tool()
    def list_allowed_roots() -> str:
        """List the directories this server may read and its active limits."""
        return json.dumps(roots_info(policy), indent=2)

    @server.tool()
    def project_structure(path: str) -> str:
        """Return a nested JSON tree (files + metadata) for a directory.

        Use this first to understand a project's layout cheaply before reading
        file contents. The path must be inside an allowed root.
        """
        return get_project_structure(policy, path)

    @server.tool()
    def load_directory(path: str) -> str:
        """Return the aggregated text of readable files under a directory.

        Binary files, secret-looking files, and files over the size caps are
        omitted; a summary header reports what was included or skipped. The path
        must be inside an allowed root.
        """
        return load_files(policy, path)

    @server.tool()
    def read_file(path: str) -> str:
        """Return the text contents of a single file inside an allowed root."""
        return get_file(policy, path)

    return server


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Local, read-only MCP server exposing the Project Tools Runner core "
            "tools to an AI agent. Runs over stdio; no data leaves your machine."
        )
    )
    parser.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Directory the server is allowed to read. Repeatable. If omitted, "
            "TOOLS_MCP_ALLOWED_ROOTS is used."
        ),
    )
    parser.add_argument("--exclude", action="append", default=[], metavar="NAME",
                        help="Extra directory name to exclude. Repeatable.")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    return parser.parse_args(argv)


def policy_from_args(argv: Optional[List[str]] = None) -> AccessPolicy:
    """Build a policy from CLI args, falling back to environment variables."""
    args = _parse_args(argv)
    if args.root:
        return build_policy(
            roots=args.root,
            extra_excludes=args.exclude,
            max_files=args.max_files,
            max_total_bytes=args.max_total_bytes,
            max_file_bytes=args.max_file_bytes,
            max_depth=args.max_depth,
        )
    return policy_from_env()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        policy = policy_from_args(argv)
    except AccessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    server = build_server(policy)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
