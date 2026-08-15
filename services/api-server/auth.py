from datetime import datetime, timedelta
from typing import Optional
import hashlib
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from config import get_settings
from services.redis_service import get_redis_service

settings = get_settings()

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# Password hashing (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(BaseModel):
    username: str
    role: str = "operator"  # admin, operator, viewer


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return pwd_context.hash(password)


def _is_legacy_sha256(hashed: str) -> bool:
    """Check if hash is old SHA-256 format (64 hex chars)."""
    return len(hashed) == 64 and all(c in '0123456789abcdef' for c in hashed)


# Default users (used if Redis has no users)
DEFAULT_USERS = {
    "admin": {
        "username": "admin",
        "password_hash": hash_password("admin"),
        "role": "admin"
    },
    "operator": {
        "username": "operator",
        "password_hash": hash_password("operator"),
        "role": "operator"
    }
}


def init_default_users():
    """Initialize default users in Redis if none exist."""
    redis = get_redis_service()
    if not redis.has_any_users():
        for username, user_data in DEFAULT_USERS.items():
            redis.save_user(
                username=username,
                password_hash=user_data["password_hash"],
                role=user_data["role"]
            )
        redis.add_log("info", "auth", "Initialized default users (admin, operator)")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password — supports bcrypt and legacy SHA-256 with auto-upgrade."""
    if _is_legacy_sha256(hashed_password):
        return hashlib.sha256(plain_password.encode()).hexdigest() == hashed_password
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return hash_password(password)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Authenticate user against Redis (with fallback to defaults)."""
    redis = get_redis_service()

    # First, ensure default users exist
    if not redis.has_any_users():
        init_default_users()

    # Get user from Redis
    user = redis.get_user(username)

    if not user:
        return None

    if not verify_password(password, user.get("password_hash", "")):
        return None

    # Auto-upgrade legacy SHA-256 hash to bcrypt on successful login
    stored_hash = user.get("password_hash", "")
    if _is_legacy_sha256(stored_hash):
        new_hash = hash_password(password)
        redis.update_user_password(username, new_hash)
        redis.add_log("info", "auth", f"Auto-upgraded password hash to bcrypt for '{username}'")

    return {
        "username": user["username"],
        "role": user.get("role", "operator")
    }


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def get_current_user(
    request: Request,
    bearer_token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = bearer_token or request.cookies.get("alertflow_session")
    if not token:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        role: str = payload.get("role", "viewer")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=role)
    except JWTError:
        raise credentials_exception

    return User(username=token_data.username, role=token_data.role)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return user


def require_operator(user: User = Depends(get_current_user)) -> User:
    """Allow state-changing operational actions to operators and admins only."""
    if user.role not in {"admin", "operator"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required",
        )
    return user
