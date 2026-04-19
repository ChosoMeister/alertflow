"""
Logs API - Access to system logs.
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional, List

from auth import User, get_current_user
from services.redis_service import get_redis_service

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=List[dict])
async def get_logs(
    limit: int = Query(default=100, le=500),
    service: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """Get recent logs with optional service filter."""
    redis_svc = get_redis_service()
    return redis_svc.get_recent_logs(count=limit, service=service)


@router.get("/relay", response_model=List[dict])
async def get_relay_logs(
    limit: int = Query(default=100, le=500),
    user: User = Depends(get_current_user)
):
    """Get recent relay logs (notification dispatch history)."""
    redis_svc = get_redis_service()
    return redis_svc.get_relay_logs(limit=limit)
