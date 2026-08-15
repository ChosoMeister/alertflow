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
    secret_fields_configured: List[str] = []


class NotificationDestinationConfig(BaseModel):
    name: str
    channel_id: str
    type: str
    target: Dict[str, Any]
    enabled: bool = True


SECRET_FIELDS = {
    "telegram": ("bot_token",),
    "matrix": ("access_token",),
    "sms": ("api_key",),
    "phone": ("api_key",),
    "webhook": ("headers",),
}


def _public_channel(channel: Dict[str, Any]) -> Dict[str, Any]:
    """Return channel metadata while keeping credentials write-only."""
    public = dict(channel)
    config = dict(public.get("config") or {})
    configured = []
    for field in SECRET_FIELDS.get(public.get("type", ""), ()):
        if config.get(field):
            configured.append(field)
        config.pop(field, None)
    public["config"] = config
    public["secret_fields_configured"] = configured
    return public


def _preserve_channel_secrets(channel_type: str, incoming: Dict[str, Any], existing: Dict[str, Any]) -> Dict[str, Any]:
    """Blank/omitted secret fields mean unchanged during an update."""
    merged = dict(incoming or {})
    old_config = existing.get("config") or {}
    for field in SECRET_FIELDS.get(channel_type, ()):
        if not merged.get(field) and old_config.get(field):
            merged[field] = old_config[field]
    return merged


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
    return [_public_channel(channel) for channel in channels]


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
    return _public_channel(new_channel)


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
    return _public_channel(channel)


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

    channel_data = channel.model_dump()
    channel_data["config"] = _preserve_channel_secrets(
        channel.type, channel_data.get("config", {}), existing
    )
    updated = redis_svc.update_notification_channel(channel_id, channel_data)
    return _public_channel(updated)


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

    if any(item.get("channel_id") == channel_id for item in redis_svc.get_notification_destinations()):
        raise HTTPException(status_code=409, detail="Connector is used by one or more destinations")
    redis_svc.delete_notification_channel(channel_id)
    return {"message": "Channel deleted"}


def _validate_destination(redis_svc, item: NotificationDestinationConfig):
    channel = redis_svc.get_notification_channel(item.channel_id)
    if not channel:
        raise HTTPException(status_code=400, detail="Connector does not exist")
    if channel.get("type") != item.type:
        raise HTTPException(status_code=400, detail="Destination type must match connector type")
    required = {"telegram": "chat_id", "matrix": "room_id", "webhook": "url", "sms": "receptor"}.get(item.type)
    if required and not item.target.get(required):
        raise HTTPException(status_code=400, detail=f"Destination requires {required}")


@router.get("/destinations/list", response_model=List[dict])
async def list_notification_destinations(user: User = Depends(get_current_user)):
    redis_svc = get_redis_service()
    result = redis_svc.get_notification_destinations()
    usage = {}
    for rule in redis_svc.list_routing_rules():
        severity_ids = [item for items in rule.get("severity_destination_ids", {}).values() for item in items]
        for destination_id in set(rule.get("alert_destination_ids", []) + rule.get("resolved_destination_ids", []) + severity_ids):
            usage[destination_id] = usage.get(destination_id, 0) + 1
    for item in result:
        item["rule_count"] = usage.get(item["id"], 0)
    return result


@router.post("/destinations", response_model=dict)
async def create_notification_destination(item: NotificationDestinationConfig, user: User = Depends(require_admin)):
    redis_svc = get_redis_service()
    _validate_destination(redis_svc, item)
    return redis_svc.add_notification_destination(item.model_dump())


@router.put("/destinations/{destination_id}", response_model=dict)
async def update_notification_destination(destination_id: str, item: NotificationDestinationConfig, user: User = Depends(require_admin)):
    redis_svc = get_redis_service()
    _validate_destination(redis_svc, item)
    result = redis_svc.update_notification_destination(destination_id, item.model_dump())
    if not result:
        raise HTTPException(status_code=404, detail="Destination not found")
    return result


@router.delete("/destinations/{destination_id}")
async def delete_notification_destination(destination_id: str, user: User = Depends(require_admin)):
    redis_svc = get_redis_service()
    if not redis_svc.get_notification_destination(destination_id):
        raise HTTPException(status_code=404, detail="Destination not found")
    if not redis_svc.delete_notification_destination(destination_id):
        raise HTTPException(status_code=409, detail="Destination is used by one or more routing rules")
    return {"message": "Destination deleted"}


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
