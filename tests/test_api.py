import unittest
from flask import Flask
from repolens.api import api_bp, init_app
from repolens.models import Repository, Analysis
from repolens.database import db
from sqlalchemy.orm import close_all_sessions

class TestGetAnalysis(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        self.app.register_blueprint(api_bp)
        init_app(self.app)
        
        with self.app.app_context():
            db.create_all()
            
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        close_all_sessions()

    def test_get_existing_analysis(self):
        with self.app.app_context():
            repo = Repository()
            repo.name = 'test_repo'
            repo.url = 'https://github.com/test/repo.git'
            db.session.add(repo)
            db.session.commit()

            analysis = Analysis()
            analysis.repository_id = repo.id
            analysis.analysis_type = 'file_count'
            analysis.result = {'count': 10}
            db.session.add(analysis)
            db.session.commit()

            response = self.client.get(f'/api/analysis/{analysis.id}')
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data['id'], analysis.id)
            self.assertEqual(data['repository_id'], repo.id)
            self.assertEqual(data['repository_name'], repo.name)
            self.assertEqual(data['analysis_type'], 'file_count')
            self.assertEqual(data['result'], {'count': 10})

    def test_get_nonexistent_analysis(self):
        response = self.client.get('/api/analysis/999')
        self.assertEqual(response.status_code, 404)
        data = response.get_json()
        self.assertEqual(data['error'], 'Analysis not found')

    def test_get_analysis_with_invalid_id(self):
        response = self.client.get('/api/analysis/invalid')
        self.assertEqual(response.status_code, 404)

    def test_get_analysis_multiple_requests(self):
        with self.app.app_context():
            repo = Repository()
            repo.name = 'test_repo'
            repo.url = 'https://github.com/test/repo.git'
            db.session.add(repo)
            db.session.commit()

            analysis = Analysis()
            analysis.repository_id = repo.id
            analysis.analysis_type = 'file_count'
            analysis.result = {'count': 10}
            db.session.add(analysis)
            db.session.commit()

            for _ in range(5):  # Make multiple requests to test for DetachedInstanceError
                response = self.client.get(f'/api/analysis/{analysis.id}')
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertEqual(data['id'], analysis.id)
                self.assertEqual(data['repository_id'], repo.id)
                self.assertEqual(data['repository_name'], repo.name)

if __name__ == '__main__':
    unittest.main()
