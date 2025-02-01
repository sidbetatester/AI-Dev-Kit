"""
FileLoaderTool: A utility for recursive file content aggregation and logging.

This module provides a class for reading all text-based files from a directory structure,
storing them in a single output file, and generating detailed logs about processed,
skipped, and excluded content. Compatible with Windows, Linux, and macOS.
"""

import os
from typing import Dict, List, Set
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

    def __init__(self, project_root: str) -> None:
        """
        Initialize the FileLoaderTool with a project root directory.

        Args:
            project_root: The base directory path to start processing from.
        """
        self.project_root: Path = Path(project_root).resolve()
        self.processed_files: List[str] = []
        self.skipped_files: List[str] = []
        self.excluded_dirs: List[str] = []

    def load_files_in_directory(self, directory: str) -> Dict[str, str]:
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
        
        for root, dirs, files in os.walk(directory_path):
            root_path = Path(root)
            
            # Track and remove excluded directories
            removed_dirs = set(d for d in dirs if d in exclude_dirs)
            if removed_dirs:
                self.excluded_dirs.extend(str(root_path / d) for d in removed_dirs)
            
            # Update dirs in place to exclude unwanted directories
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            # Skip processing if the current directory is in an excluded path
            if any(ex_dir in root_path.parts for ex_dir in exclude_dirs):
                continue

            for file in files:
                file_path = root_path / file
                try:
                    # Attempt to read as UTF-8 text
                    content = file_path.read_text(encoding='utf-8')
                    file_contents[str(file_path)] = content
                    self.processed_files.append(str(file_path))
                except (UnicodeDecodeError, FileNotFoundError, PermissionError) as e:
                    error_msg = f"Skipped {file_path} due to error: {e}"
                    self.skipped_files.append(error_msg)
                    print(error_msg)
        
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

        with output_path.open('w', encoding='utf-8') as f:
            for file_path, content in file_contents.items():
                f.write(f"--- File: {file_path} ---\n")
                f.write(content + "\n\n")
        
        print(f"File contents saved to {output_path}")

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
        
        with log_path.open('w', encoding='utf-8') as f:
            f.write("Processed Files:\n")
            for file in self.processed_files:
                f.write(f"{file}\n")
            
            f.write("\nExcluded Directories:\n")
            for dir_path in self.excluded_dirs:
                f.write(f"{dir_path}\n")
            
            f.write("\nSkipped Files:\n")
            if self.skipped_files:
                for error in self.skipped_files:
                    f.write(f"{error}\n")
            else:
                f.write("No files were skipped during processing\n")
        
        print(f"Log saved to {log_path}")


if __name__ == "__main__":
    # Example usage with cross-platform path
    project_root = str(Path.cwd())  # Use current working directory as an example
    loader = FileLoaderTool(project_root)
    
    # Process all files in the project directory
    all_files = loader.load_files_in_directory(project_root)
    
    # Save the aggregated content and processing log
    loader.save_file_contents(all_files)
    loader.save_log()
