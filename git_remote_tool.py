"""
git_remote_tool.py

A utility for cloning and managing remote Git repositories.
Supports GitHub and GitLab with Personal Access Token (PAT) authentication.
"""

import os
import subprocess
import re
import tempfile
import shutil
from typing import Optional, Tuple
from pathlib import Path


class GitRemoteTool:
    """
    Handles cloning and management of remote Git repositories.
    
    Supports authentication via Personal Access Tokens (PAT) for GitHub and GitLab.
    """
    
    def __init__(self, logger: Optional[callable] = None):
        """
        Initialize GitRemoteTool.
        
        Args:
            logger: Optional logging function (defaults to print)
        """
        self._logger = logger if logger is not None else print
    
    def _log(self, message: str, level: str = "INFO") -> None:
        """Emit a structured log message."""
        formatted = f"[{level.upper()}] {message}"
        try:
            self._logger(formatted)
        except Exception:
            print(formatted)
    
    def check_git_installed(self) -> bool:
        """
        Check if git is installed and accessible.
        
        Returns:
            True if git is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['git', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self._log(f"Git found: {result.stdout.strip()}")
                return True
            return False
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._log("Git not found on system", level="ERROR")
            return False
    
    def validate_url(self, url: str) -> Optional[Tuple[str, str, str]]:
        """
        Validate and parse a Git repository URL.
        
        Args:
            url: Git repository URL (HTTPS or SSH format)
        
        Returns:
            Tuple of (platform, owner, repo_name) if valid, None otherwise
            
        Supported formats:
            - https://github.com/owner/repo
            - https://github.com/owner/repo.git
            - https://gitlab.com/owner/repo
            - git@github.com:owner/repo.git
        """
        # HTTPS patterns
        https_pattern = r'https?://(?:www\.)?(github|gitlab)\.com/([^/]+)/([^/]+?)(?:\.git)?/?$'
        match = re.match(https_pattern, url)
        if match:
            platform, owner, repo = match.groups()
            return (platform, owner, repo)
        
        # SSH pattern
        ssh_pattern = r'git@(github|gitlab)\.com:([^/]+)/([^/]+?)(?:\.git)?$'
        match = re.match(ssh_pattern, url)
        if match:
            platform, owner, repo = match.groups()
            return (platform, owner, repo)
        
        self._log(f"Invalid Git URL format: {url}", level="ERROR")
        return None
    
    def clone_repository(
        self,
        url: str,
        token: Optional[str],
        destination: Optional[str] = None,
        depth: int = 1
    ) -> Tuple[bool, str, str]:
        """
        Clone a Git repository to a destination folder.
        
        Args:
            url: Repository URL
            token: Personal Access Token (None for public repos)
            destination: Destination path (None for temp directory)
            depth: Clone depth (1 for shallow clone, 0 for full clone)
        
        Returns:
            Tuple of (success, destination_path, error_message)
        """
        parsed = self.validate_url(url)
        if not parsed:
            return (False, "", "Invalid repository URL")
        
        platform, owner, repo = parsed
        
        # Create destination path
        if destination is None:
            destination = tempfile.mkdtemp(prefix=f"git_{repo}_")
        else:
            os.makedirs(destination, exist_ok=True)
        
        # Build clone URL with token if provided
        if token:
            clone_url = f"https://{token}@{platform}.com/{owner}/{repo}.git"
        else:
            clone_url = f"https://{platform}.com/{owner}/{repo}.git"
        
        # Build git clone command
        cmd = ['git', 'clone']
        if depth > 0:
            cmd.extend(['--depth', str(depth)])
        cmd.extend([clone_url, destination])
        
        self._log(f"Cloning repository: {platform}.com/{owner}/{repo}")
        if depth > 0:
            self._log(f"Shallow clone (depth={depth})")
        
        try:
            # Run git clone (hide token from output)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                self._log(f"Successfully cloned to: {destination}")
                return (True, destination, "")
            else:
                # Parse error message (hide token)
                error_msg = result.stderr.replace(token or "", "***") if token else result.stderr
                self._log(f"Clone failed: {error_msg}", level="ERROR")
                
                # Clean up failed clone
                if os.path.exists(destination):
                    shutil.rmtree(destination, ignore_errors=True)
                
                return (False, "", error_msg)
                
        except subprocess.TimeoutExpired:
            self._log("Clone operation timed out (5 minutes)", level="ERROR")
            if os.path.exists(destination):
                shutil.rmtree(destination, ignore_errors=True)
            return (False, "", "Clone timed out after 5 minutes")
        
        except Exception as e:
            self._log(f"Unexpected error during clone: {str(e)}", level="ERROR")
            if os.path.exists(destination):
                shutil.rmtree(destination, ignore_errors=True)
            return (False, "", str(e))
    
    def cleanup(self, path: str) -> bool:
        """
        Remove a cloned repository directory.
        
        Args:
            path: Path to the cloned repository
        
        Returns:
            True if cleanup succeeded, False otherwise
        """
        try:
            if os.path.exists(path):
                shutil.rmtree(path)
                self._log(f"Cleaned up: {path}")
                return True
            return True
        except Exception as e:
            self._log(f"Cleanup failed for {path}: {str(e)}", level="ERROR")
            return False


if __name__ == "__main__":
    # Example usage
    tool = GitRemoteTool()
    
    # Check git
    if not tool.check_git_installed():
        print("Git is not installed!")
        exit(1)
    
    # Test URL validation
    test_urls = [
        "https://github.com/python/cpython",
        "https://gitlab.com/gitlab-org/gitlab",
        "git@github.com:torvalds/linux.git",
        "invalid-url"
    ]
    
    for url in test_urls:
        result = tool.validate_url(url)
        print(f"{url} -> {result}")
