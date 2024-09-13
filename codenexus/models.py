from codenexus import db
from datetime import datetime

class Repository(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    packaged_data = db.Column(db.JSON)

class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    repository_id = db.Column(db.Integer, db.ForeignKey('repository.id'), nullable=False)
    analysis_type = db.Column(db.String(50), nullable=False)
    result = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    repository = db.relationship('Repository', backref=db.backref('analyses', lazy=True))
