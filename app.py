import os
from flask import Flask, redirect, url_for, send_from_directory
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from config import config_by_name
from database.models import db


def create_app(config_name='development'):
    
    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    
    os.makedirs(app.config.get('UPLOAD_FOLDER', 'uploads'), exist_ok=True)
    os.makedirs(app.config.get('SCREENSHOT_FOLDER', 'screenshots'), exist_ok=True)

  
    db.init_app(app)
    JWTManager(app)
    CORS(app)

    # Register blueprints
    from routes.auth_routes import auth_bp
    from routes.student_routes import student_bp
    from routes.lecturer_routes import lecturer_bp
    from routes.exam_routes import exam_bp
    from routes.analytics_routes import analytics_bp
    from routes.admin_routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(lecturer_bp)
    app.register_blueprint(exam_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(admin_bp)

    # Root route
    @app.route('/')
    def index():
        return redirect(url_for('auth.login_page'))

    # Serve uploaded files
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Initialize database
    from database.db_init import init_database
    init_database(app)

    return app


if __name__ == '__main__':
    env = os.getenv('FLASK_ENV', 'development')
    app = create_app(env)
    app.run(host='0.0.0.0', port=5000, debug=(env == 'development'))
