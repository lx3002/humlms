import bcrypt
from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, get_jwt, verify_jwt_in_request
import cryptography


def hash_password(password: str) -> str:
    
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, password_hash: str) -> bool:
   return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def hash_emails(email:str)->str:
    return cryptography.hash(email.encode("uft-8"), cryptography.SHA256()).hexdigest()


def get_identity():
 
    user_id = get_jwt_identity()
    claims = get_jwt()
    return {
        'id': int(user_id),
        'email': claims.get('email', ''),
        'role': claims.get('role', ''),
    }


def role_required(*roles):

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            identity = get_identity()
            if identity.get('role') not in roles:
                return jsonify({'error': 'Access denied. Insufficient permissions.'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
