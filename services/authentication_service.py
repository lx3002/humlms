from database.models import db, User
from utils.security import hash_password, check_password
from flask_jwt_extended import create_access_token, create_refresh_token
import re


class AuthenticationService:
    """Handles user registration, login, and token management."""

    @staticmethod
    def register(email, password, first_name, last_name, role):
        
        # Validate email format
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return None, 'Invalid email format.'

        # Check password strength
        if len(password) < 8:
            return None, 'Password must be at least 8 characters.'

        # Check if user exists
        if User.query.filter_by(email=email).first():
            return None, 'Email already registered.'

        # Validate role
        if role not in ('admin', 'lecturer', 'student'):
            return None, 'Invalid role.'

        user = User(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        db.session.add(user)
        db.session.commit()
        return user, None

    @staticmethod
    def login(email, password):
        """Authenticate user and return tokens."""
        user_row = db.session.query(
            User.id,
            User.email,
            User.password_hash,
            User.first_name,
            User.last_name,
            User.role,
            User.profile_image,
            User.phone_number,
            User.bio,
            User.is_active,
            User.share_contact,
            User.created_at,
            User.face_encoding.isnot(None).label('face_registered'),
        ).filter(
            User.email == email,
            User.is_active == True,
        ).first()

        if not user_row or not check_password(password, user_row.password_hash):
            return None, 'Invalid email or password.'

        profile_steps = [
            bool(user_row.profile_image),
            bool(user_row.phone_number),
            bool(user_row.bio),
            bool(user_row.face_registered),
        ]
        profile_complete = int(sum(profile_steps) / len(profile_steps) * 100)

        user_payload = {
            'id': user_row.id,
            'email': user_row.email,
            'first_name': user_row.first_name,
            'last_name': user_row.last_name,
            'role': user_row.role,
            'profile_image': user_row.profile_image,
            'phone_number': user_row.phone_number,
            'bio': user_row.bio,
            'is_active': user_row.is_active,
            'share_contact': user_row.share_contact,
            'profile_complete': profile_complete,
            'face_registered': bool(user_row.face_registered),
            'created_at': user_row.created_at.isoformat() if user_row.created_at else None,
        }

        claims = {'email': user_row.email, 'role': user_row.role}
        access_token = create_access_token(identity=str(user_row.id), additional_claims=claims)
        refresh_token = create_refresh_token(identity=str(user_row.id), additional_claims=claims)

        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'user': user_payload,
        }, None

    @staticmethod
    def get_user_by_id(user_id):
        """Get user by ID."""
        return User.query.get(user_id)

    @staticmethod
    def update_profile(user_id, **kwargs):
        """Update user profile fields."""
        user = User.query.get(user_id)
        if not user:
            return None, 'User not found.'

        allowed = ['first_name', 'last_name', 'profile_image', 'phone_number', 'bio', 'share_contact']
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(user, key, value)

        db.session.commit()
        return user, None

    @staticmethod
    def change_password(user_id, old_password, new_password):
        """Change user password."""
        user = User.query.get(user_id)
        if not user:
            return False, 'User not found.'
        if not check_password(old_password, user.password_hash):
            return False, 'Current password is incorrect.'
        if len(new_password) < 8:
            return False, 'New password must be at least 8 characters.'

        user.password_hash = hash_password(new_password)
        db.session.commit()
        return True, None
