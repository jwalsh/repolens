import unittest
from codenexus.analyzer import analyze_repository
from codenexus.models import Repository, Analysis, db
from main import app

class TestAnalyzer(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()

        # Create a test repository
        self.test_repo = Repository(
            name='test_repo',
            url='https://github.com/test/test_repo.git',
            packaged_data={
                'files': [{'path': 'file1.py'}, {'path': 'file2.js'}],
                'commits': [{'hash': 'abc123'}, {'hash': 'def456'}],
                'branches': ['main', 'develop']
            }
        )
        db.session.add(self.test_repo)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_analyze_repository(self):
        analysis_types = ['file_count', 'commit_count', 'branch_count', 'file_types']

        for analysis_type in analysis_types:
            analysis_id = analyze_repository(self.test_repo.id, analysis_type)
            self.assertIsNotNone(analysis_id)

            analysis = Analysis.query.get(analysis_id)
            self.assertIsNotNone(analysis)
            self.assertEqual(analysis.repository_id, self.test_repo.id)
            self.assertEqual(analysis.analysis_type, analysis_type)
            self.assertIsNotNone(analysis.result)

        # Test invalid analysis type
        invalid_analysis_id = analyze_repository(self.test_repo.id, 'invalid_type')
        self.assertIsNone(invalid_analysis_id)

if __name__ == '__main__':
    unittest.main()
