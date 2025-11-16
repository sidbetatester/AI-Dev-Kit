"""
project_structure_tool.py

Creates a comprehensive JSON representation of a project directory structure,
capturing file metadata (size, creation date, modification date) along with
the nested directory structure. Works across Windows, Linux, and macOS.
"""

import os
import json
import datetime
import platform
import stat
from typing import Dict, Any, List, TypedDict, Optional, Callable

# Default directory names to exclude from traversal
DEFAULT_EXCLUDE_DIRS: set[str] = {
    'venv', '__pycache__', '.venv', 'env', 'node_modules', '.git', '.idea',
    '.tox', 'dist', 'build', '.mypy_cache', '.pytest_cache'
}

class FileInfo(TypedDict):
    """Type definition for file metadata"""
    name: str
    size: int
    created: Optional[str]  # Optional since creation time isn't available on all systems
    modified: str
    permissions: str  # Added for unix-like systems

class DirectoryStructure(TypedDict):
    """Type definition for directory structure"""
    files: List[FileInfo]
    subfolders: Dict[str, 'DirectoryStructure']

class ProjectStructureTool:
    """
    Traverses a given directory and builds a nested JSON-like structure describing
    files (with metadata) and subfolders. Provides functionality to save/load 
    this structure to/from disk. Works across different operating systems.
    """

    def __init__(self, project_root: str, logger: Optional[Callable[[str], None]] = None,
                 exclude_dirs: Optional[set[str]] = None) -> None:
        """
        Initialize the ProjectStructureTool with a root directory.

        Args:
            project_root (str): The absolute path to the top-level project directory.

        Raises:
            ValueError: If project_root is not a valid directory path.
        """
        if not os.path.isdir(project_root):
            raise ValueError(f"Invalid project directory: {project_root}")
            
        self.project_root: str = project_root
        self.project_map: Dict[str, DirectoryStructure] = {}
        self.system: str = platform.system().lower()
        self._logger: Callable[[str], None] = logger if logger is not None else print
        self.exclude_dirs: set[str] = set(exclude_dirs) if exclude_dirs is not None else set(DEFAULT_EXCLUDE_DIRS)

    def _log(self, message: str, level: str = "INFO") -> None:
        formatted = f"[{level.upper()}] {message}"
        try:
            self._logger(formatted)
        except Exception:
            print(formatted)

    def _count_items(self, root_path: str) -> int:
        """
        Count total items (files + directories) under root_path for progress reporting.
        Returns 0 if counting fails; callers may fall back to indeterminate progress.
        """
        total = 0
        try:
            for _root, dirs, files in os.walk(root_path):
                total += len(dirs) + len(files)
        except OSError:
            return 0
        return total

    def _format_datetime(self, timestamp: float) -> str:
        """
        Convert a timestamp to a formatted datetime string.

        Args:
            timestamp (float): Unix timestamp to convert

        Returns:
            str: Formatted datetime string (YYYY-MM-DD HH:MM:SS)
        """
        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def _get_file_creation_time(self, path: str) -> Optional[str]:
        """
        Get file creation time in a cross-platform way.

        Args:
            path (str): Path to the file

        Returns:
            Optional[str]: Formatted creation time or None if unavailable
        """
        try:
            if self.system == 'windows':
                # Windows provides actual creation time
                return self._format_datetime(os.path.getctime(path))
            elif self.system == 'darwin':  # macOS
                # macOS has birth time (creation time)
                stat_info = os.stat(path)
                if hasattr(stat_info, 'st_birthtime'):
                    return self._format_datetime(stat_info.st_birthtime)
            # On Linux, creation time isn't reliably available
            return None
        except (OSError, AttributeError):
            return None

    def _get_file_permissions(self, stats: os.stat_result) -> str:
        """
        Get file permissions in a readable format.

        Args:
            stats (os.stat_result): Result of os.stat() call

        Returns:
            str: String representation of file permissions
        """
        if self.system == 'windows':
            # Simple readonly check for Windows
            return 'read-only' if stats.st_mode & stat.S_IWRITE == 0 else 'read-write'
        else:
            # Unix-style permission string
            mode = stats.st_mode
            perms = []
            for who in ['USR', 'GRP', 'OTH']:
                for what in ['R', 'W', 'X']:
                    perm = getattr(stat, f'S_I{what}{who}')
                    perms.append(what.lower() if mode & perm else '-')
            return ''.join(perms)

    def _get_file_info(self, entry: os.DirEntry) -> FileInfo:
        """
        Gather metadata for a single file in a cross-platform manner.

        Args:
            entry (os.DirEntry): DirEntry object for the file

        Returns:
            FileInfo: Dictionary containing file metadata
        """
        stats = entry.stat()
        
        # Get creation time if available
        created_time = self._get_file_creation_time(entry.path)
        
        # Get modification time (available on all platforms)
        modified_time = self._format_datetime(stats.st_mtime)
        
        # Get permissions
        permissions = self._get_file_permissions(stats)
        
        return FileInfo(
            name=entry.name,
            size=stats.st_size,
            created=created_time,
            modified=modified_time,
            permissions=permissions
        )

    def _build_recursive(self, current_path: str,
                         progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
                         cancel_event: Optional[Any] = None,
                         counters: Optional[Dict[str, int]] = None) -> DirectoryStructure:
        """
        Recursively build the structure for the current directory.

        Args:
            current_path (str): Path to the current directory to process

        Returns:
            DirectoryStructure: Dictionary containing files and subfolders
        """
        structure: DirectoryStructure = {
            "files": [],
            "subfolders": {}
        }

        try:
            # Cooperative cancellation
            if cancel_event is not None and getattr(cancel_event, 'is_set', lambda: False)():
                return structure

            # Initial state notice is noisy; prefer per-entry increments below.

            with os.scandir(current_path) as entries:
                # Convert to list to avoid iterator invalidation issues on Windows
                entries_list = sorted(list(entries), key=lambda e: e.name.casefold())
                for entry in entries_list:
                    # Check cancellation before processing each entry
                    if cancel_event is not None and getattr(cancel_event, 'is_set', lambda: False)():
                        return structure

                    try:
                        # Update progress for each encountered entry (file or directory)
                        if counters is not None:
                            counters['processed'] = counters.get('processed', 0) + 1
                            if progress_callback is not None:
                                progress_callback('project_structure', counters.get('processed', 0), counters.get('total', 0), entry.path)

                        if entry.is_dir(follow_symlinks=False):
                            # Skip excluded directories by name
                            if entry.name in self.exclude_dirs:
                                continue
                            # Skip symlinks to avoid cycles
                            structure["subfolders"][entry.name] = self._build_recursive(
                                entry.path,
                                progress_callback=progress_callback,
                                cancel_event=cancel_event,
                                counters=counters
                            )
                        else:
                            # Process regular files only
                            if entry.is_file(follow_symlinks=False):
                                structure["files"].append(self._get_file_info(entry))
                    except PermissionError:
                        self._log(f"Permission denied accessing {entry.path}", level="WARNING")
                    except OSError as e:
                        self._log(f"Error accessing {entry.path}: {str(e)}", level="ERROR")
                        
        except PermissionError:
            self._log(f"Permission denied accessing directory {current_path}", level="WARNING")
        except OSError as e:
            # Detect long-path issues for clearer logging
            msg = str(e)
            try:
                import errno
                if getattr(e, 'errno', None) == errno.ENAMETOOLONG or getattr(e, 'winerror', None) in (206,):
                    msg = "Path too long"
            except Exception:
                pass
            self._log(f"Error accessing directory {current_path}: {msg}", level="ERROR")

        return structure

    def build_project_structure(self,
                                progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
                                cancel_event: Optional[Any] = None) -> Dict[str, DirectoryStructure]:
        """
        Build the complete project structure starting from the root directory.

        Returns:
            Dict[str, DirectoryStructure]: Nested dictionary of project structure
        """
        # Normalize path separators for consistency across platforms
        root_basename = os.path.basename(os.path.normpath(self.project_root))

        counters: Optional[Dict[str, int]] = None
        if progress_callback is not None:
            total = self._count_items(self.project_root)
            if total > 0:
                counters = {"processed": 0, "total": total}

        self.project_map = {
            root_basename: self._build_recursive(self.project_root,
                                                 progress_callback=progress_callback,
                                                 cancel_event=cancel_event,
                                                 counters=counters)
        }
        return self.project_map

    def save_project_structure(self, output_file: str = 'project_structure.json') -> None:
        """
        Save the project structure to a JSON file.

        Args:
            output_file (str): Path where the JSON file should be saved

        Raises:
            IOError: If there's an error writing to the output file
        """
        try:
            # Normalize path and ensure directory exists
            output_file = os.path.normpath(output_file)
            os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as json_file:
                json.dump(self.project_map, json_file, indent=4)
            self._log(f"Project structure saved to {output_file}", level="INFO")
            
        except IOError as e:
            raise IOError(f"Failed to save project structure: {e}") from e

    def load_project_structure(self, input_file: str = 'project_structure.json') -> Dict[str, DirectoryStructure]:
        """
        Load a previously saved project structure from a JSON file.

        Args:
            input_file (str): Path to the JSON file to load

        Returns:
            Dict[str, DirectoryStructure]: The loaded project structure

        Raises:
            FileNotFoundError: If the input file doesn't exist
            json.JSONDecodeError: If the input file isn't valid JSON
        """
        try:
            # Normalize path for cross-platform compatibility
            input_file = os.path.normpath(input_file)
            
            with open(input_file, 'r', encoding='utf-8') as json_file:
                self.project_map = json.load(json_file)
            self._log(f"Project structure loaded from {input_file}", level="INFO")
            return self.project_map
            
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Structure file not found: {input_file}") from e
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in structure file: {e}", e.doc, e.pos) from e


if __name__ == "__main__":
    try:
        # Get the directory containing this script in a cross-platform way
        project_root = os.path.dirname(os.path.abspath(__file__))
        tool = ProjectStructureTool(project_root)
        
        # Build and save the structure
        structure = tool.build_project_structure()
        tool.save_project_structure(os.path.join("output", "project_structure.json"))
        
        print("Project structure processing completed successfully.")
        
    except Exception as e:
        print(f"Error: {str(e)}")
