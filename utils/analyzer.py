import json
from collections import Counter

def analyze_repository(repo_data):
    analysis = {
        'file_count': len(repo_data['files']),
        'file_types': Counter(),
        'total_lines': 0,
        'commit_count': len(repo_data['commit_history']),
        'top_contributors': Counter()
    }

    for file in repo_data['files']:
        file_extension = file['path'].split('.')[-1] if '.' in file['path'] else 'unknown'
        analysis['file_types'][file_extension] += 1
        analysis['total_lines'] += len(file['content'].splitlines())

    for commit in repo_data['commit_history']:
        analysis['top_contributors'][commit['author']] += 1

    analysis['file_types'] = dict(analysis['file_types'].most_common(5))
    analysis['top_contributors'] = dict(analysis['top_contributors'].most_common(5))

    return analysis
