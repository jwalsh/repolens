import os


class Config:
    """Application configuration.

    ``DATABASE_URL`` is honoured when set. When it is not, fall back to a
    local SQLite file rather than handing ``None`` to SQLAlchemy, which
    fails at ``init_app`` with an error that names neither the variable nor
    the fix.
    """

    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
