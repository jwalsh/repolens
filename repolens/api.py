from flask import Blueprint, jsonify, request, current_app
from repolens.packager import package_repository
from repolens.analyzer import analyze_repository
from repolens.models import Repository, Analysis
from repolens.database import db

api_bp = Blueprint('api', __name__)

@api_bp.route('/package', methods=['POST'])
def package():
    data = request.json
    if not data or 'repo_url' not in data:
        return jsonify({'error': 'Missing repo_url'}), 400

    with current_app.app_context():
        repo_id, error = package_repository(data['repo_url'])
    if error:
        return jsonify({'error': error}), 500
    return jsonify({'repo_id': repo_id}), 201

@api_bp.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    if not data or 'repo_id' not in data or 'analysis_type' not in data:
        return jsonify({'error': 'Missing repo_id or analysis_type'}), 400

    with current_app.app_context():
        analysis_id = analyze_repository(data['repo_id'], data['analysis_type'])
    if not analysis_id:
        return jsonify({'error': 'Invalid repo_id or analysis_type'}), 400

    return jsonify({'analysis_id': analysis_id}), 201

@api_bp.route('/repository/<int:repo_id>', methods=['GET'])
def get_repository(repo_id):
    with current_app.app_context():
        repository = Repository.query.get(repo_id)
    if not repository:
        return jsonify({'error': 'Repository not found'}), 404

    return jsonify({
        'id': repository.id,
        'name': repository.name,
        'url': repository.url,
        'created_at': repository.created_at.isoformat()
    })

@api_bp.route('/analysis/<int:analysis_id>', methods=['GET'])
def get_analysis(analysis_id):
    with current_app.app_context():
        analysis = Analysis.query.get(analysis_id)
    if not analysis:
        return jsonify({'error': 'Analysis not found'}), 404

    return jsonify({
        'id': analysis.id,
        'repository_id': analysis.repository_id,
        'analysis_type': analysis.analysis_type,
        'result': analysis.result,
        'created_at': analysis.created_at.isoformat()
    })
