from flask import Blueprint, jsonify, request, current_app, send_file
from repolens.packager import package_repository
from repolens.analyzer import analyze_repository
from repolens.models import Repository, Analysis
from repolens.database import db
from flask_caching import Cache
import tempfile
import json
import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

api_bp = Blueprint('api', __name__)
cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})

@api_bp.route('/package', methods=['POST'])
def package():
    data = request.json
    if not data or 'repo_url' not in data:
        return jsonify({'error': 'Missing repo_url'}), 400

    with current_app.app_context():
        repo_id, error = package_repository(data['repo_url'])
    if error:
        return jsonify({'error': error}), 500
    
    repository = Repository.query.get(repo_id)
    return jsonify({'repo_id': repo_id, 'repo_name': repository.name}), 201

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
        'repository_name': analysis.repository.name,
        'analysis_type': analysis.analysis_type,
        'result': analysis.result,
        'created_at': analysis.created_at.isoformat()
    })

@api_bp.route('/repository/repolens', methods=['GET'])
def get_repolens_repository():
    with current_app.app_context():
        repository = Repository.query.filter_by(name='repolens').first()
    if not repository:
        return jsonify({'error': 'RepoLens repository not found'}), 404

    return jsonify({
        'id': repository.id,
        'name': repository.name,
        'url': repository.url,
        'created_at': repository.created_at.isoformat()
    })

@api_bp.route('/download/<int:repo_id>', methods=['GET'])
@cache.cached(timeout=300)  # Cache for 5 minutes
def download_repository_content(repo_id):
    with current_app.app_context():
        repository = Repository.query.get(repo_id)
    if not repository:
        return jsonify({'error': 'Repository not found'}), 404

    # Create a temporary file to store the repository content
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as temp_file:
        json.dump(repository.packaged_data, temp_file, indent=2)

    # Send the file as an attachment
    return send_file(temp_file.name, as_attachment=True, download_name=f"{repository.name}_content.txt")

@api_bp.route('/screenshot', methods=['POST'])
def take_screenshot():
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing url'}), 400

    url = data['url']
    
    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Set up the Chrome WebDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        # Navigate to the URL and take a screenshot
        driver.get(url)
        screenshot = driver.get_screenshot_as_png()

        # Save the screenshot to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
            temp_file.write(screenshot)
            temp_file_path = temp_file.name

        # Send the file as an attachment
        return send_file(temp_file_path, mimetype='image/png', as_attachment=True, download_name='screenshot.png')
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        driver.quit()

def init_app(app):
    cache.init_app(app)
