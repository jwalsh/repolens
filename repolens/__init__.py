"""RepoLens package.

Deliberately empty of state. The single SQLAlchemy instance lives in
``repolens.database``; importing it from anywhere else creates a second
registry whose models are invisible to ``db.create_all()``.
"""
