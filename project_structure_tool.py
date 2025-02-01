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
from typing import Dict, Any, List, TypedDict, Optional

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

    def __init__(self, project_root: str) -> None:
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

    def _build_recursive(self, current_path: str) -> DirectoryStructure:
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
            with os.scandir(current_path) as entries:
                # Convert to list to avoid iterator invalidation issues on Windows
                entries_list = list(entries)
                for entry in entries_list:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            # Skip symlinks to avoid cycles
                            structure["subfolders"][entry.name] = self._build_recursive(entry.path)
                        else:
                            # Process regular files only
                            if entry.is_file(follow_symlinks=False):
                                structure["files"].append(self._get_file_info(entry))
                    except PermissionError:
                        print(f"Warning: Permission denied accessing {entry.path}")
                    except OSError as e:
                        print(f"Error accessing {entry.path}: {str(e)}")
                        
        except PermissionError:
            print(f"Warning: Permission denied accessing directory {current_path}")
        except OSError as e:
            print(f"Error accessing directory {current_path}: {str(e)}")

        return structure

    def build_project_structure(self) -> Dict[str, DirectoryStructure]:
        """
        Build the complete project structure starting from the root directory.

        Returns:
            Dict[str, DirectoryStructure]: Nested dictionary of project structure
        """
        # Normalize path separators for consistency across platforms
        root_basename = os.path.basename(os.path.normpath(self.project_root))
        self.project_map = {
            root_basename: self._build_recursive(self.project_root)
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
            print(f"Project structure saved to {output_file}")
            
        except IOError as e:
            raise IOError(f"Failed to save project structure: {str(e)}")

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
            print(f"Project structure loaded from {input_file}")
            return self.project_map
            
        except FileNotFoundError:
            raise FileNotFoundError(f"Structure file not found: {input_file}")
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in structure file: {str(e)}", e.doc, e.pos)


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
