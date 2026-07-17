"""
Integrations API - Telegram and Matrix settings.
"""
from fastapi import APIRouter, Depends
from typing import List

from auth import User, get_current_user, require_admin
from models import IntegrationSettings
from services.redis_service import get_redis_service

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/settings")
async def get_integration_settings(user: User = Depends(get_current_user)):
    """Get current integration settings."""
    redis_svc = get_redis_service()
    config = redis_svc.get_all_config()

    return {
        "telegram_enabled": config.get("telegram_enabled", "true") == "true",
        "matrix_enabled": config.get("matrix_enabled", "false") == "true",
        "failover_enabled": config.get("failover_enabled", "true") == "true",
        "message_verbosity": config.get("message_verbosity", "standard"),
    }


@router.put("/settings")
async def update_integration_settings(
    settings: IntegrationSettings,
    user: User = Depends(require_admin)
):
    """Update integration settings."""
    redis_svc = get_redis_service()

    redis_svc.set_config("telegram_enabled", str(settings.telegram_enabled).lower())
    redis_svc.set_config("matrix_enabled", str(settings.matrix_enabled).lower())
    redis_svc.set_config("failover_enabled", str(settings.failover_enabled).lower())
    redis_svc.set_config("message_verbosity", settings.message_verbosity)

    redis_svc.add_log("INFO", "api", "Integration settings updated")

    return {"message": "Settings updated"}



@router.post("/telegram/test")
async def test_telegram(user: User = Depends(get_current_user)):
    """Send a test message to Telegram (default destination)."""
    # This will be handled by the processor
    redis_svc = get_redis_service()

    email_data = {
        "from": "system@alertflow.local",
        "to": "test@localhost",
        "subject": "Telegram Test",
        "text": "This is a test message from AlertFlow.",
        "is_test": True,
        "force_channel": "telegram",
    }

    trace_id = redis_svc.push_to_queue(email_data)
    redis_svc.add_log("INFO", "api", "Telegram test message queued", {"trace_id": trace_id})

    return {"message": "Test message queued", "trace_id": trace_id}


@router.post("/matrix/test")
async def test_matrix(user: User = Depends(get_current_user)):
    """Send a test message to Matrix (default destination)."""
    redis_svc = get_redis_service()

    email_data = {
        "from": "system@alertflow.local",
        "to": "test@localhost",
        "subject": "Matrix Test",
        "text": "This is a test message from AlertFlow.",
        "is_test": True,
        "force_channel": "matrix",
    }

    trace_id = redis_svc.push_to_queue(email_data)
    redis_svc.add_log("INFO", "api", "Matrix test message queued", {"trace_id": trace_id})

    return {"message": "Test message queued", "trace_id": trace_id}


# ========================
# Mutes Management
# ========================

@router.get("/mutes/from", response_model=List[str])
async def list_from_mutes(user: User = Depends(get_current_user)):
    """List muted sender addresses."""
    redis_svc = get_redis_service()
    return redis_svc.list_mutes("from")


@router.post("/mutes/from/{address}")
async def add_from_mute(address: str, user: User = Depends(require_admin)):
    """Mute a sender address."""
    redis_svc = get_redis_service()
    redis_svc.add_mute("from", address)
    redis_svc.add_log("INFO", "api", f"Muted sender: {address}")
    return {"message": f"Muted {address}"}


@router.delete("/mutes/from/{address}")
async def remove_from_mute(address: str, user: User = Depends(require_admin)):
    """Unmute a sender address."""
    redis_svc = get_redis_service()
    redis_svc.remove_mute("from", address)
    redis_svc.add_log("INFO", "api", f"Unmuted sender: {address}")
    return {"message": f"Unmuted {address}"}


@router.get("/mutes/domain", response_model=List[str])
async def list_domain_mutes(user: User = Depends(get_current_user)):
    """List muted domains."""
    redis_svc = get_redis_service()
    return redis_svc.list_mutes("domain")


@router.post("/mutes/domain/{domain}")
async def add_domain_mute(domain: str, user: User = Depends(require_admin)):
    """Mute a domain."""
    redis_svc = get_redis_service()
    redis_svc.add_mute("domain", domain)
    redis_svc.add_log("INFO", "api", f"Muted domain: {domain}")
    return {"message": f"Muted {domain}"}


@router.delete("/mutes/domain/{domain}")
async def remove_domain_mute(domain: str, user: User = Depends(require_admin)):
    """Unmute a domain."""
    redis_svc = get_redis_service()
    redis_svc.remove_mute("domain", domain)
    redis_svc.add_log("INFO", "api", f"Unmuted domain: {domain}")
    return {"message": f"Unmuted {domain}"}
