import os
import json
import git
from repolens.models import Repository, db

def package_repository(repo_url):
    # Clone the repository
    repo_name = repo_url.split('/')[-1].replace('.git', '')
    repo_path = f'/tmp/{repo_name}'
    git.Repo.clone_from(repo_url, repo_path)

    # Collect repository data
    repo_data = {
        'name': repo_name,
        'url': repo_url,
        'files': [],
        'commits': [],
        'branches': []
    }

    # Collect file information
    for root, _, files in os.walk(repo_path):
        for file in files:
            file_path = os.path.join(root, file)
            relative_path = os.path.relpath(file_path, repo_path)
            repo_data['files'].append({
                'path': relative_path,
                'size': os.path.getsize(file_path)
            })

    # Collect commit information
    repo = git.Repo(repo_path)
    for commit in repo.iter_commits():
        repo_data['commits'].append({
            'hash': commit.hexsha,
            'author': str(commit.author),
            'message': commit.message,
            'date': commit.committed_datetime.isoformat()
        })

    # Collect branch information
    for branch in repo.branches:
        repo_data['branches'].append(str(branch))

    # Save packaged data to the database
    repository = Repository(name=repo_name, url=repo_url, packaged_data=repo_data)
    db.session.add(repository)
    db.session.commit()

    # Clean up temporary files
    os.system(f'rm -rf {repo_path}')

    return repository.id
