from flask import Flask, render_template

from config import Config
from repolens.api import api_bp, init_app as init_api
from repolens.database import db


def create_app(config_object: type = Config, **overrides: object) -> Flask:
    """Build the application.

    ``overrides`` lets tests inject a database URI without setting process
    environment variables.
    """
    app = Flask(__name__)

    app.config.from_object(config_object)
    app.config.update(overrides)

    # Initialize SQLAlchemy with the app
    db.init_app(app)

    # Register blueprints
    app.register_blueprint(api_bp, url_prefix='/api')

    # Initialize API (including cache)
    init_api(app)

    @app.route('/')
    def index():
        return render_template('index.html')

    return app


app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000)
