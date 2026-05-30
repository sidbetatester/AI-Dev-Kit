"""
Security policy for the local MCP server (``mcp_server.py``).

This module is deliberately dependency-free (standard library only) so it can be
unit-tested without the optional ``mcp`` package installed, and so the safety
logic is easy to audit in isolation.

The MCP server is **read-only** and runs **entirely on the user's own machine**;
nothing it returns ever leaves their system via this code. These controls exist
so the server behaves as a well-mannered local citizen even when driven by an
automated agent:

* **Allowed-roots jail** — every requested path is resolved (symlinks included)
  and must live inside one of the configured root directories. This blocks path
  traversal (``../../etc/passwd``) and symlink escapes.
* **Secret-aware excludes** — files whose names look like credentials/keys are
  never returned, so an agent can't slurp ``.env`` or private keys into its
  context by accident.
* **Size/depth caps** — bound how much a single call *returns*, protecting the
  agent's context window. Note: the server reuses the core tools unchanged (for
  byte-for-byte parity with the desktop/web apps), so these caps filter the
  aggregated result rather than short-circuiting the directory walk. That is an
  accepted tradeoff for a local, read-only, single-user tool operating on the
  user's own files — it is not a defense against deliberate resource exhaustion.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

# Re-use the *exact* directory excludes the core tools ship with, so MCP results
# match the desktop/web behaviour. Imported lazily-safe at module load.
from file_loader_tool import DEFAULT_EXCLUDE_DIRS as _CORE_EXCLUDE_DIRS

# Filename glob patterns (matched case-insensitively against the base name) that
# must never be read or listed. Conservative by design.
DEFAULT_SECRET_FILE_PATTERNS: Set[str] = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "*.keystore",
    "*.jks",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*.ppk",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".htpasswd",
    "credentials",
    "credentials.json",
    "secrets.*",
    "*.secret",
    "*secrets*.json",
    "*.der",
    "*.crt",
}

# Default resource caps. Generous enough to be useful, bounded enough to be safe.
DEFAULT_MAX_FILES = 2000
DEFAULT_MAX_TOTAL_BYTES = 16 * 1024 * 1024  # 16 MiB aggregate
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB per file
DEFAULT_MAX_DEPTH = 25

# Environment variables honored by ``policy_from_env``.
ENV_ROOTS = "TOOLS_MCP_ALLOWED_ROOTS"
ENV_EXTRA_EXCLUDES = "TOOLS_MCP_EXTRA_EXCLUDES"
ENV_MAX_FILES = "TOOLS_MCP_MAX_FILES"
ENV_MAX_TOTAL_BYTES = "TOOLS_MCP_MAX_TOTAL_BYTES"
ENV_MAX_FILE_BYTES = "TOOLS_MCP_MAX_FILE_BYTES"
ENV_MAX_DEPTH = "TOOLS_MCP_MAX_DEPTH"


class AccessError(Exception):
    """Raised when a request violates the access policy (jail, secret, caps)."""


@dataclass
class AccessPolicy:
    """Immutable-ish bundle of the server's safety rules."""

    allowed_roots: List[Path]
    extra_excludes: Set[str] = field(default_factory=set)
    secret_patterns: Set[str] = field(default_factory=lambda: set(DEFAULT_SECRET_FILE_PATTERNS))
    max_files: int = DEFAULT_MAX_FILES
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_depth: int = DEFAULT_MAX_DEPTH

    def __post_init__(self) -> None:
        resolved: List[Path] = []
        for root in self.allowed_roots:
            p = Path(root).expanduser()
            real = Path(os.path.realpath(p))
            if not real.is_dir():
                raise AccessError(f"Allowed root is not a directory: {p}")
            resolved.append(real)
        if not resolved:
            raise AccessError(
                "No allowed roots configured. Refusing to start without an "
                "explicit allow-list of directories the server may read."
            )
        self.allowed_roots = resolved

    # -- directory excludes -------------------------------------------------
    @property
    def exclude_dirs(self) -> Set[str]:
        """Directory names the core tools should skip (core defaults + extras)."""
        return set(_CORE_EXCLUDE_DIRS) | set(self.extra_excludes)

    # -- path jail ----------------------------------------------------------
    def resolve_within_jail(self, requested: str) -> Path:
        """
        Resolve ``requested`` to a real absolute path and ensure it sits inside
        one of the allowed roots. Raises :class:`AccessError` otherwise.
        """
        if requested is None or str(requested).strip() == "":
            raise AccessError("A path is required.")
        candidate = Path(requested).expanduser()
        real = Path(os.path.realpath(candidate))
        for root in self.allowed_roots:
            try:
                real.relative_to(root)
            except ValueError:
                continue
            return real
        raise AccessError(
            f"Path is outside the allowed roots: {requested}. "
            f"Allowed roots: {', '.join(str(r) for r in self.allowed_roots)}"
        )

    def is_within_roots(self, path: str) -> bool:
        """
        True if ``path`` resolves (symlinks included) to a location inside one of
        the allowed roots. Non-raising companion to :meth:`resolve_within_jail`,
        used to re-validate each file discovered during a directory walk so an
        in-tree symlink can't smuggle out-of-jail content into a result.
        """
        try:
            real = Path(os.path.realpath(Path(path).expanduser()))
        except (OSError, ValueError):
            return False
        for root in self.allowed_roots:
            try:
                real.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def depth_within_jail(self, path: Path) -> int:
        """Depth of ``path`` below its containing allowed root (root == 0)."""
        for root in self.allowed_roots:
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            return len(rel.parts)
        raise AccessError(f"Path is outside the allowed roots: {path}")

    # -- secret filtering ---------------------------------------------------
    def is_secret_file(self, name: str) -> bool:
        """True if ``name`` (a base filename) matches any secret pattern."""
        base = os.path.basename(str(name))
        low = base.lower()
        return any(fnmatch.fnmatch(low, pat.lower()) for pat in self.secret_patterns)


def _split_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    # Accept both os.pathsep (":"/";") and "," as separators.
    parts: List[str] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def _int_env(env: dict, key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise AccessError(f"{key} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise AccessError(f"{key} must be a positive integer, got {value}")
    return value


def build_policy(
    roots: Sequence[str],
    extra_excludes: Optional[Iterable[str]] = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> AccessPolicy:
    """Construct an :class:`AccessPolicy` from explicit values."""
    return AccessPolicy(
        allowed_roots=[Path(r) for r in roots],
        extra_excludes=set(extra_excludes or set()),
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        max_file_bytes=max_file_bytes,
        max_depth=max_depth,
    )


def policy_from_env(env: Optional[dict] = None) -> AccessPolicy:
    """Construct an :class:`AccessPolicy` from environment variables."""
    env = dict(os.environ if env is None else env)
    roots = _split_list(env.get(ENV_ROOTS))
    if not roots:
        raise AccessError(
            f"Set {ENV_ROOTS} (or pass --root) to one or more directories the "
            f"MCP server is allowed to read."
        )
    return build_policy(
        roots=roots,
        extra_excludes=_split_list(env.get(ENV_EXTRA_EXCLUDES)),
        max_files=_int_env(env, ENV_MAX_FILES, DEFAULT_MAX_FILES),
        max_total_bytes=_int_env(env, ENV_MAX_TOTAL_BYTES, DEFAULT_MAX_TOTAL_BYTES),
        max_file_bytes=_int_env(env, ENV_MAX_FILE_BYTES, DEFAULT_MAX_FILE_BYTES),
        max_depth=_int_env(env, ENV_MAX_DEPTH, DEFAULT_MAX_DEPTH),
    )
