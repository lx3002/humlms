from flask import Blueprint, request, jsonify, render_template, redirect, url_for, make_response, current_app
from flask_jwt_extended import (
    jwt_required, set_access_cookies,
    set_refresh_cookies, unset_jwt_cookies
)
from utils.security import get_identity, hash_password
from utils.helpers import save_uploaded_file, allowed_file
from services.authentication_service import AuthenticationService
import secrets
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)


# ──────────────── PAGE ROUTES ────────────────

@auth_bp.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')


@auth_bp.route('/register', methods=['GET'])
def register_page():
    return render_template('register.html')


# ──────────────── API ROUTES ────────────────

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 404

    required = ['email', 'password', 'first_name', 'last_name']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 404

    user, error = AuthenticationService.register(
        email=data['email'],
        password=data['password'],
        first_name=data['first_name'],
        last_name=data['last_name'],
        role=data.get('role', 'student'),
    )

    if error:
        return jsonify({'error': error}), 400

    return jsonify({'message': 'Registration successful', 'user': user.to_dict()}), 201


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Email and password are required'}), 400

    result, error = AuthenticationService.login(data['email'], data['password'])
    if error:
        return jsonify({'error': error}), 401

    # Set JWT cookies for browser-based auth + return tokens in body for API use
    response = make_response(jsonify({
        'message': 'Login successful',
        'access_token': result['access_token'],
        'user': result['user'],
    }))
    set_access_cookies(response, result['access_token'])
    set_refresh_cookies(response, result['refresh_token'])
    return response


@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({'message': 'Logged out successfully'}))
    unset_jwt_cookies(response)
    return response


@auth_bp.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    identity = get_identity()
    user = AuthenticationService.get_user_by_id(identity['id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'user': user.to_dict()})


@auth_bp.route('/api/auth/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    identity = get_identity()
    data = request.get_json()
    user, error = AuthenticationService.update_profile(identity['id'], **data)
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'message': 'Profile updated', 'user': user.to_dict()})


@auth_bp.route('/api/auth/change-password', methods=['PUT'])
@jwt_required()
def change_password():
    identity = get_identity()
    data = request.get_json()
    if not data or not data.get('old_password') or not data.get('new_password'):
        return jsonify({'error': 'Old and new passwords are required'}), 400

    success, error = AuthenticationService.change_password(
        identity['id'], data['old_password'], data['new_password']
    )
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'message': 'Password changed successfully'})


@auth_bp.route('/api/auth/profile/image', methods=['POST'])
@jwt_required()
def upload_profile_image():
    identity = get_identity()
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    file = request.files['image']
    if not file.filename or not allowed_file(file.filename, 'image'):
        return jsonify({'error': 'Invalid image file. Allowed: png, jpg, jpeg, gif, webp'}), 400

    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    relative_path = save_uploaded_file(file, upload_folder, subfolder='profiles')

    from database.models import db, User
    user = User.query.get(identity['id'])
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.profile_image = relative_path
    db.session.commit()

    return jsonify({'message': 'Profile image uploaded', 'user': user.to_dict()})


@auth_bp.route('/api/auth/profile/face', methods=['POST'])
@jwt_required()
def register_face():
    identity = get_identity()
    data = request.get_json()
    if not data or not data.get('image'):
        return jsonify({'error': 'No face image provided'}), 400

    try:
        from ai_modules.exam_proctoring.face_auth import FaceAuthenticator
        fa = FaceAuthenticator()
        success, msg = fa.register_face(identity['id'], data['image'])
    except Exception as e:
        return jsonify({'error': f'Face registration error: {str(e)}'}), 500

    if not success:
        return jsonify({'error': msg}), 400

    from database.models import User
    user = User.query.get(identity['id'])
    return jsonify({'message': msg, 'user': user.to_dict()})


# ──────────────── FORGOT PASSWORD ────────────────

@auth_bp.route('/forgot-password', methods=['GET'])
def forgot_password_page():
    return render_template('forgot_password.html')


@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    """Generate a reset token for the user."""
    data = request.get_json()
    email = (data or {}).get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    from database.models import db, User
    user = User.query.filter_by(email=email).first()

    # Always return success to prevent email enumeration
    if not user:
        return jsonify({'message': 'If an account with that email exists, a reset link has been generated.'})

    token = secrets.token_urlsafe(48)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(minutes=30)
    db.session.commit()

    return jsonify({
        'message': 'If an account with that email exists, a reset link has been generated.',
        'reset_token': token,
    })


@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    """Reset password using a valid token."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    token = (data.get('token') or '').strip()
    new_password = (data.get('new_password') or '').strip()

    if not token or not new_password:
        return jsonify({'error': 'Token and new password are required'}), 400

    if len(new_password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    from database.models import db, User
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        return jsonify({'error': 'Invalid or expired reset token'}), 400

    user.password_hash = hash_password(new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.session.commit()

    return jsonify({'message': 'Password has been reset successfully. You can now log in.'})
