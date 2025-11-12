"""
FileLoaderTool: A utility for recursive file content aggregation and logging.

This module provides a class for reading all text-based files from a directory structure,
storing them in a single output file, and generating detailed logs about processed,
skipped, and excluded content. Compatible with Windows, Linux, and macOS.
"""

import os
import tempfile
from typing import Dict, List, Set, Optional, Callable, Any, Tuple
from pathlib import Path  # For cross-platform path handling


class FileLoaderTool:
    """
    A tool for loading and aggregating text files from a directory structure.

    This class recursively traverses a directory, loads text file contents while
    respecting exclusion patterns, and provides logging of processed, skipped,
    and excluded items. Uses Path for cross-platform compatibility.

    Attributes:
        project_root: The root directory path to process.
        processed_files: List of successfully processed file paths.
        skipped_files: List of files that couldn't be processed with error details.
        excluded_dirs: List of directories that were excluded from processing.
    """

    def __init__(self, project_root: str, logger: Optional[Callable[[str], None]] = None) -> None:
        """
        Initialize the FileLoaderTool with a project root directory.

        Args:
            project_root: The base directory path to start processing from.
        """
        self.project_root: Path = Path(project_root).resolve()
        self.processed_files: List[str] = []
        self.skipped_files: List[str] = []
        self.excluded_dirs: List[str] = []
        self._logger: Callable[[str], None] = logger if logger is not None else print

    def _log(self, message: str) -> None:
        try:
            self._logger(message)
        except Exception:
            # Fallback to print if provided logger fails
            print(message)

    def _is_probably_text(self, file_path: Path, sample_size: int = 2048) -> bool:
        """
        Heuristic to detect text vs binary by sampling bytes.
        - Returns False if NUL byte present.
        - Otherwise checks ratio of printable/whitespace bytes.
        """
        try:
            with file_path.open('rb') as fh:
                data = fh.read(sample_size)
        except Exception:
            # If we can't read as bytes, treat as non-text to be safe.
            return False
        if not data:
            return True
        if b"\x00" in data:
            return False
        # Count control bytes excluding common whitespace
        controls = 0
        for b in data:
            if b < 32 and b not in (9, 10, 12, 13):  # exclude \t, \n, \f, \r
                controls += 1
            elif b == 127:  # DEL
                controls += 1
        return (controls / max(1, len(data))) <= 0.30

    def _read_text_with_fallback(self, file_path: Path) -> Tuple[Optional[str], Optional[str]]:
        """
        Attempt to read text using a sequence of encodings.
        Returns (text, encoding_used). If it must fall back to replacement,
        returns ('decoded text', 'fallback-replace:<encoding>'). If it fails,
        returns (None, None).
        """
        encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1252', 'latin-1']
        for enc in encodings:
            try:
                return (file_path.read_text(encoding=enc, errors='strict'), enc)
            except Exception:
                continue
        # Last resort: decode with replacement to avoid crashing the run
        try:
            return (file_path.read_text(encoding='utf-8', errors='replace'), 'fallback-replace:utf-8')
        except Exception:
            return (None, None)

    def load_files_in_directory(
        self,
        directory: str,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
        cancel_event: Optional[Any] = None,
    ) -> Dict[str, str]:
        """
        Recursively load text files from the given directory and its subdirectories.

        Walks through the directory tree, respecting exclusion patterns, and attempts
        to read all text files. Binary files and files that can't be read are logged
        as skipped. Excluded directories are tracked.

        Args:
            directory: The directory path to process.

        Returns:
            A dictionary mapping file paths to their text contents.
        """
        file_contents: Dict[str, str] = {}
        exclude_dirs: Set[str] = {
            'venv', '__pycache__', '.venv',
            'env', 'node_modules', '.git'
        }
        
        directory_path = Path(directory).resolve()
        
        processed_count = 0
        total_estimate = 0  # 0/negative implies unknown

        for root, dirs, files in os.walk(directory_path):
            root_path = Path(root)
            
            # Track and remove excluded directories
            removed_dirs = set(d for d in dirs if d in exclude_dirs)
            if removed_dirs:
                self.excluded_dirs.extend(str(root_path / d) for d in removed_dirs)
            
            # Update dirs in place to exclude unwanted directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            # Deterministic traversal order: sort directories (case-insensitive)
            dirs.sort(key=lambda s: s.casefold())
            
            # Skip processing if the current directory is in an excluded path
            if any(ex_dir in root_path.parts for ex_dir in exclude_dirs):
                continue

            # Progress per directory (optional)
            if progress_callback is not None:
                progress_callback('file_loader', processed_count, total_estimate, str(root_path))

            # Deterministic file order within a directory
            for file in sorted(files, key=lambda s: s.casefold()):
                file_path = root_path / file
                if cancel_event is not None and getattr(cancel_event, 'is_set', lambda: False)():
                    return file_contents
                try:
                    # Skip likely binary files early
                    if not self._is_probably_text(file_path):
                        msg = f"Skipped (binary) {file_path}"
                        self.skipped_files.append(msg)
                        self._log(msg)
                        continue
                    # Attempt to read using encoding fallback strategy
                    content, used = self._read_text_with_fallback(file_path)
                    if content is None:
                        raise UnicodeDecodeError('unknown', b'', 0, 1, 'unable to decode with fallbacks')
                    file_contents[str(file_path)] = content
                    self.processed_files.append(str(file_path))
                    processed_count += 1
                    if used and used.startswith('fallback-replace'):
                        self._log(f"Decoded with replacement: {file_path} ({used})")
                except (UnicodeDecodeError, FileNotFoundError, PermissionError) as e:
                    error_msg = f"Skipped {file_path} due to error: {e}"
                    self.skipped_files.append(error_msg)
                    self._log(error_msg)
        
        return file_contents

    def save_file_contents(
        self, 
        file_contents: Dict[str, str], 
        output_file: str = 'Tools_Outputs/loaded_files_output.txt'
    ) -> None:
        """
        Save aggregated file contents to a single output file.

        Creates the output directory if it doesn't exist and writes all file
        contents with clear separators between files.

        Args:
            file_contents: Dictionary mapping file paths to their contents.
            output_file: Path where the aggregated content should be saved.
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Deterministic order by path
        sorted_paths = sorted(file_contents.keys(), key=lambda s: s.casefold())

        def _write(fh):
            for file_path in sorted_paths:
                content = file_contents[file_path]
                fh.write(f"--- File: {file_path} ---\n")
                fh.write(content + "\n\n")

        self._atomic_write_text(output_path, _write)
        self._log(f"File contents saved to {output_path}")

    def save_log(
        self, 
        log_file: str = 'Tools_Outputs/file_loader_log.txt'
    ) -> None:
        """
        Save processing results to a log file.

        Creates a detailed log containing lists of processed files, excluded
        directories, and any files that were skipped during processing.

        Args:
            log_file: Path where the log should be saved.
        """
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Sort lists for deterministic logs
        processed_sorted = sorted(self.processed_files, key=lambda s: s.casefold())
        excluded_sorted = sorted(self.excluded_dirs, key=lambda s: s.casefold())
        skipped_sorted = sorted(self.skipped_files, key=lambda s: s.casefold())
        summary_line = f"Summary: processed={len(processed_sorted)} excluded_dirs={len(excluded_sorted)} skipped={len(skipped_sorted)}\n\n"

        def _write(fh):
            fh.write(summary_line)
            fh.write("Processed Files:\n")
            for file in processed_sorted:
                fh.write(f"{file}\n")

            fh.write("\nExcluded Directories:\n")
            for dir_path in excluded_sorted:
                fh.write(f"{dir_path}\n")

            fh.write("\nSkipped Files:\n")
            if skipped_sorted:
                for error in skipped_sorted:
                    fh.write(f"{error}\n")
            else:
                fh.write("No files were skipped during processing\n")

        self._atomic_write_text(log_path, _write)
        self._log(f"Log saved to {log_path}")

    def _atomic_write_text(self, final_path: Path, write_callback: Callable[[Any], None]) -> None:
        """
        Atomically write text to final_path by writing to a temp file and replacing.
        Ensures best-effort atomicity across platforms using os.replace.
        """
        tmp_dir = final_path.parent
        prefix = final_path.name + "."
        fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(tmp_dir))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
                write_callback(fh)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    # fsync might not be available/necessary on some filesystems
                    pass
            os.replace(str(tmp_path), str(final_path))
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise


if __name__ == "__main__":
    # Example usage with cross-platform path
    project_root = str(Path.cwd())  # Use current working directory as an example
    loader = FileLoaderTool(project_root)
    
    # Process all files in the project directory
    all_files = loader.load_files_in_directory(project_root)
    
    # Save the aggregated content and processing log
    loader.save_file_contents(all_files)
    loader.save_log()
