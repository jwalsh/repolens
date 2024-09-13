import json
import requests
from git import Repo
import tempfile
import os
import shutil

def convert_repository(repo_url):
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            Repo.clone_from(repo_url, temp_dir)
            
            repo_data = {
                'url': repo_url,
                'files': [],
                'commit_history': []
            }
            
            for root, _, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    relative_path = os.path.relpath(file_path, temp_dir)
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    repo_data['files'].append({
                        'path': relative_path,
                        'content': content
                    })
            
            repo = Repo(temp_dir)
            for commit in list(repo.iter_commits())[:10]:  # Limit to last 10 commits
                repo_data['commit_history'].append({
                    'hash': commit.hexsha,
                    'author': str(commit.author),
                    'message': commit.message,
                    'date': commit.committed_datetime.isoformat()
                })
            
            return repo_data
        except Exception as e:
            raise Exception(f"Error converting repository: {str(e)}")
