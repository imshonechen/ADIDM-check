from flask import Flask
from flask_login import LoginManager

from app.config import Config
from app.models import init_db, get_user_by_id

login_manager = LoginManager()
login_manager.login_view = 'admin.login'


def create_app():
    app = Flask(__name__, template_folder='../templates', static_folder='static')
    app.config.from_object(Config)

    # Ensure data directory exists
    import os
    os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)

    # Init database
    init_db(app.config['DATABASE_PATH'])

    # Init login manager
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(app.config['DATABASE_PATH'], int(user_id))

    # Register blueprints
    from app.api.routes import api_bp
    from app.admin.routes import admin_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(admin_bp)

    # Register index route
    @app.route('/')
    def index():
        from flask import send_from_directory
        return send_from_directory('../templates', 'index.html')

    # Start scheduler
    from app.scheduler import start_scheduler
    start_scheduler(app)

    return app
