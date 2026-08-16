import io
import json
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request, current_app, send_file
from flask_caching import Cache
from sqlalchemy.orm import joinedload

from repolens.packager import package_repository
from repolens.analyzer import analyze_repository
from repolens.models import Repository, Analysis
from repolens.database import db

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
    
    repository = db.session.get(Repository, repo_id)
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
        repository = db.session.get(Repository, repo_id)
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
        analysis = db.session.get(
            Analysis, analysis_id,
            options=[joinedload(Analysis.repository)],
        )
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
        repository = db.session.get(Repository, repo_id)
    if not repository:
        return jsonify({'error': 'Repository not found'}), 404

    # Serve from memory. The previous implementation wrote a NamedTemporaryFile
    # with delete=False and never unlinked it, so every download leaked a file
    # for the lifetime of the host.
    payload = json.dumps(repository.packaged_data, indent=2).encode('utf-8')

    return send_file(
        io.BytesIO(payload),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"{repository.name}_content.txt",
    )

@api_bp.route('/screenshot', methods=['POST'])
def take_screenshot():
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'Missing url'}), 400

    url = data['url']

    # Partial guard only. This blocks file:// and similar local schemes, which
    # otherwise let an unauthenticated caller read the host filesystem through
    # the browser. It does NOT stop SSRF against internal HTTP services --
    # that needs authentication plus address-range filtering. See the
    # provenance-lens addendum, security section.
    if urlparse(url).scheme not in ('http', 'https'):
        return jsonify({'error': 'Only http and https URLs are supported'}), 400

    # Imported lazily: selenium and webdriver-manager are needed by this one
    # endpoint, and a top-level import took the whole application down when
    # they were absent.
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        screenshot = driver.get_screenshot_as_png()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        driver.quit()

    # Served from memory; the temp file this used to write was never unlinked.
    return send_file(
        io.BytesIO(screenshot),
        mimetype='image/png',
        as_attachment=True,
        download_name='screenshot.png',
    )

def init_app(app):
    cache.init_app(app)
