import os
import subprocess

def clone_repository(repo_url, target_dir):
    """Clone a git repository to a target directory."""
    try:
        subprocess.run(['git', 'clone', repo_url, target_dir], check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def get_file_contents(file_path):
    """Read and return the contents of a file."""
    try:
        with open(file_path, 'r') as file:
            return file.read()
    except IOError:
        return None

def get_file_size(file_path):
    """Get the size of a file in bytes."""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return None
