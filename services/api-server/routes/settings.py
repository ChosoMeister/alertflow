"""
Settings Routes - User management and password changes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth import get_current_user, require_admin, User, hash_password, verify_password
from services.redis_service import get_redis_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


class PasswordChangeRequest(BaseModel):
    """Request to change current user's password."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=4, max_length=100)


class AdminPasswordChangeRequest(BaseModel):
    """Request for admin to change any user's password."""
    new_password: str = Field(..., min_length=4, max_length=100)


class UserInfo(BaseModel):
    """User info without sensitive data."""
    username: str
    role: str


@router.get("/users", response_model=list[UserInfo])
async def list_users(user: User = Depends(require_admin)):
    """List all users (admin only)."""
    redis = get_redis_service()
    users = redis.get_users()
    return users


@router.put("/password")
async def change_own_password(
    request: PasswordChangeRequest,
    user: User = Depends(get_current_user)
):
    """Change current user's password."""
    redis = get_redis_service()
    
    # Get current user from Redis
    stored_user = redis.get_user(user.username)
    if not stored_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Verify current password
    if not verify_password(request.current_password, stored_user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect"
        )
    
    # Update password
    new_hash = hash_password(request.new_password)
    redis.update_user_password(user.username, new_hash)
    
    redis.add_log("info", "auth", f"User '{user.username}' changed their password")
    
    return {"message": "Password changed successfully. Please log in again."}


@router.put("/users/{username}/password")
async def admin_change_user_password(
    username: str,
    request: AdminPasswordChangeRequest,
    user: User = Depends(require_admin)
):
    """Admin: Change any user's password."""
    redis = get_redis_service()
    
    # Check if target user exists
    stored_user = redis.get_user(username)
    if not stored_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Update password
    new_hash = hash_password(request.new_password)
    redis.update_user_password(username, new_hash)
    
    redis.add_log("info", "auth", f"Admin '{user.username}' changed password for user '{username}'")
    
    return {"message": f"Password for '{username}' changed successfully."}


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current user info."""
    return {"username": user.username, "role": user.role}
