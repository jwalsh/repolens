from codenexus.models import Repository, Analysis, db

def analyze_repository(repo_id, analysis_type):
    repository = Repository.query.get(repo_id)
    if not repository:
        return None

    result = {}

    if analysis_type == 'file_count':
        result['total_files'] = len(repository.packaged_data['files'])
    elif analysis_type == 'commit_count':
        result['total_commits'] = len(repository.packaged_data['commits'])
    elif analysis_type == 'branch_count':
        result['total_branches'] = len(repository.packaged_data['branches'])
    elif analysis_type == 'file_types':
        file_types = {}
        for file in repository.packaged_data['files']:
            ext = file['path'].split('.')[-1] if '.' in file['path'] else 'unknown'
            file_types[ext] = file_types.get(ext, 0) + 1
        result['file_types'] = file_types
    else:
        return None

    analysis = Analysis(repository_id=repo_id, analysis_type=analysis_type, result=result)
    db.session.add(analysis)
    db.session.commit()

    return analysis.id
