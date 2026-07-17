"""
Notification Channels API - CRUD for SMS, Telegram, Matrix, Webhook, etc.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import User, get_current_user, require_admin
from services.redis_service import get_redis_service

router = APIRouter(prefix="/notification-channels", tags=["notification-channels"])


class NotificationChannelConfig(BaseModel):
    name: str
    type: str  # telegram, matrix, sms, webhook, phone
    config: Dict[str, Any]  # type-specific config
    is_default: bool = False


class NotificationChannelResponse(NotificationChannelConfig):
    id: str


# Example configs by type:
# telegram: { bot_token, default_chat_id, default_thread_id }
# matrix: { homeserver_url, access_token, default_room_id }
# sms: { provider: "twilio"|"kavenegar", api_key, sender }
# webhook: { url, method, headers }
# phone: { provider, api_key, from_number }


@router.get("", response_model=List[NotificationChannelResponse])
async def list_notification_channels(user: User = Depends(get_current_user)):
    """List all notification channels."""
    redis_svc = get_redis_service()
    channels = redis_svc.get_notification_channels()
    return channels


@router.post("", response_model=NotificationChannelResponse)
async def create_notification_channel(
    channel: NotificationChannelConfig,
    user: User = Depends(require_admin)
):
    """Create a new notification channel."""
    redis_svc = get_redis_service()

    # If this is default, unset other defaults of same type
    if channel.is_default:
        redis_svc.unset_default_notification_channel()

    new_channel = redis_svc.add_notification_channel(channel.model_dump())
    return new_channel


@router.get("/{channel_id}", response_model=NotificationChannelResponse)
async def get_notification_channel(
    channel_id: str,
    user: User = Depends(get_current_user)
):
    """Get a specific notification channel."""
    redis_svc = get_redis_service()
    channel = redis_svc.get_notification_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.put("/{channel_id}", response_model=NotificationChannelResponse)
async def update_notification_channel(
    channel_id: str,
    channel: NotificationChannelConfig,
    user: User = Depends(require_admin)
):
    """Update a notification channel."""
    redis_svc = get_redis_service()

    existing = redis_svc.get_notification_channel(channel_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Channel not found")

    if channel.is_default:
        redis_svc.unset_default_notification_channel()

    updated = redis_svc.update_notification_channel(channel_id, channel.model_dump())
    return updated


@router.delete("/{channel_id}")
async def delete_notification_channel(
    channel_id: str,
    user: User = Depends(require_admin)
):
    """Delete a notification channel."""
    redis_svc = get_redis_service()

    existing = redis_svc.get_notification_channel(channel_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Channel not found")

    redis_svc.delete_notification_channel(channel_id)
    return {"message": "Channel deleted"}


@router.post("/{channel_id}/test")
def test_notification_channel(
    channel_id: str,
    user: User = Depends(require_admin)
):
    """Test a notification channel by sending a test message."""
    import requests

    redis_svc = get_redis_service()
    channel = redis_svc.get_notification_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel_type = channel.get("type", "")
    config = channel.get("config", {})

    try:
        if channel_type == "telegram":
            return _test_telegram(config)
        elif channel_type == "matrix":
            return _test_matrix(config)
        elif channel_type == "webhook":
            return _test_webhook(config)
        elif channel_type == "sms":
            return {"status": "info", "message": "SMS test not implemented - would send test SMS"}
        elif channel_type == "phone":
            return {"status": "info", "message": "Phone test not implemented - would make test call"}
        else:
            return {"status": "error", "message": f"Unknown channel type: {channel_type}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _test_telegram(config: Dict[str, Any]) -> Dict[str, str]:
    """Test Telegram bot connection."""
    import requests

    bot_token = config.get("bot_token", "")
    chat_id = config.get("default_chat_id", "")

    if not bot_token:
        return {"status": "error", "message": "Bot token not configured"}

    # Test getMe API
    response = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getMe",
        timeout=10
    )

    if response.status_code == 200:
        result = response.json()
        if result.get("ok"):
            bot_name = result.get("result", {}).get("username", "Unknown")
            return {"status": "success", "message": f"Bot @{bot_name} is reachable"}

    return {"status": "error", "message": f"Telegram API error: {response.text}"}


def _test_matrix(config: Dict[str, Any]) -> Dict[str, str]:
    """Test Matrix homeserver connection."""
    import requests

    homeserver = config.get("homeserver_url", "")
    access_token = config.get("access_token", "")

    if not homeserver or not access_token:
        return {"status": "error", "message": "Homeserver or token not configured"}

    # Test whoami API
    response = requests.get(
        f"{homeserver.rstrip('/')}/_matrix/client/v3/account/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10
    )

    if response.status_code == 200:
        result = response.json()
        user_id = result.get("user_id", "Unknown")
        return {"status": "success", "message": f"Matrix user {user_id} is authenticated"}

    return {"status": "error", "message": f"Matrix API error: {response.text}"}


def _test_webhook(config: Dict[str, Any]) -> Dict[str, str]:
    """Test webhook endpoint."""
    import requests

    url = config.get("url", "")
    method = config.get("method", "POST").upper()
    headers = config.get("headers", {})

    if not url:
        return {"status": "error", "message": "Webhook URL not configured"}

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        else:
            response = requests.post(url, headers=headers, json={"test": True}, timeout=10)

        if response.status_code < 400:
            return {"status": "success", "message": f"Webhook returned {response.status_code}"}
        else:
            return {"status": "error", "message": f"Webhook returned {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": str(e)}
