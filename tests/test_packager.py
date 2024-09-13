import unittest
from codenexus.packager import package_repository
from codenexus.models import Repository, db
from main import app

class TestPackager(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_package_repository(self):
        repo_url = 'https://github.com/psf/requests.git'
        repo_id = package_repository(repo_url)

        self.assertIsNotNone(repo_id)
        
        repository = Repository.query.get(repo_id)
        self.assertIsNotNone(repository)
        self.assertEqual(repository.url, repo_url)
        self.assertIsNotNone(repository.packaged_data)
        self.assertIn('files', repository.packaged_data)
        self.assertIn('commits', repository.packaged_data)
        self.assertIn('branches', repository.packaged_data)

if __name__ == '__main__':
    unittest.main()
