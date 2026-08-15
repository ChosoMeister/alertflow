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


from models import GeneralSettings

@router.get("/general", response_model=GeneralSettings)
async def get_general_settings(user: User = Depends(get_current_user)):
    """Get general system settings."""
    redis = get_redis_service()
    settings_data = redis.client.hgetall("settings:general")

    # Fallback to env or default
    retention = settings_data.get("alert_retention_days")
    summary_chat = settings_data.get("summary_telegram_chat_id")
    summary_thread = settings_data.get("summary_telegram_thread_id")
    summary_token = settings_data.get("summary_telegram_bot_token")

    import os
    if not retention:
        retention = os.getenv("ALERT_RETENTION_DAYS", "14")
    if not summary_chat:
        summary_chat = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
    if not summary_thread:
        summary_thread = os.getenv("TELEGRAM_DEFAULT_THREAD_ID", "0")
    if not summary_token:
        summary_token = os.getenv("TELEGRAM_DEFAULT_BOT_TOKEN", "")
    def int_setting(name, default):
        return int(settings_data.get(name) or os.getenv(name.upper(), str(default)))

    return GeneralSettings(
        alert_retention_days=int(retention),
        summary_telegram_chat_id=summary_chat,
        summary_telegram_thread_id=summary_thread,
        # Secrets are write-only. Never return the stored token to a browser.
        summary_telegram_bot_token="",
        summary_telegram_bot_token_configured=bool(summary_token),
        global_storm_max_notifications=int_setting("global_storm_max_notifications", 20),
        global_storm_window_seconds=int_setting("global_storm_window_seconds", 300),
        storm_summary_interval_seconds=int_setting("storm_summary_interval_seconds", 300),
        incident_sla_minutes=int_setting("incident_sla_minutes", 60),
    )

@router.put("/general", response_model=GeneralSettings)
async def update_general_settings(
    settings: GeneralSettings,
    user: User = Depends(require_admin)
):
    """Update general system settings."""
    redis = get_redis_service()
    existing_token = redis.client.hget("settings:general", "summary_telegram_bot_token") or ""

    mapping = {
        "alert_retention_days": str(settings.alert_retention_days),
        "summary_telegram_chat_id": settings.summary_telegram_chat_id or "",
        "summary_telegram_thread_id": settings.summary_telegram_thread_id or "0",
        "global_storm_max_notifications": str(settings.global_storm_max_notifications),
        "global_storm_window_seconds": str(settings.global_storm_window_seconds),
        "storm_summary_interval_seconds": str(settings.storm_summary_interval_seconds),
        "incident_sla_minutes": str(settings.incident_sla_minutes),
    }
    if settings.summary_telegram_bot_token:
        mapping["summary_telegram_bot_token"] = settings.summary_telegram_bot_token
    redis.client.hset("settings:general", mapping=mapping)
    redis.add_log("info", "settings", f"Admin '{user.username}' updated general settings")

    return GeneralSettings(
        alert_retention_days=settings.alert_retention_days,
        summary_telegram_chat_id=settings.summary_telegram_chat_id,
        summary_telegram_thread_id=settings.summary_telegram_thread_id,
        summary_telegram_bot_token="",
        summary_telegram_bot_token_configured=bool(
            settings.summary_telegram_bot_token or existing_token
        ),
        global_storm_max_notifications=settings.global_storm_max_notifications,
        global_storm_window_seconds=settings.global_storm_window_seconds,
        storm_summary_interval_seconds=settings.storm_summary_interval_seconds,
        incident_sla_minutes=settings.incident_sla_minutes,
    )
