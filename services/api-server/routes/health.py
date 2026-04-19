"""
Health and Status API - System health checks.
"""
import os
import requests
from fastapi import APIRouter, Depends

from auth import User, get_current_user
from services.redis_service import get_redis_service
from models import SystemStatus, QueueMetrics

router = APIRouter(tags=["health"])

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/chat/completions")


def check_ollama_health() -> str:
    """Check if Ollama API is reachable (lightweight ping)."""
    try:
        response = requests.post(
            OLLAMA_BASE_URL,
            json={
                "model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1
            },
            headers={"Content-Type": "application/json"},
            timeout=120
        )
        return "online" if response.status_code == 200 else "offline"
    except:
        return "offline"



@router.get("/health")
async def health_check():
    """Basic health check (no auth required)."""
    redis_svc = get_redis_service()
    redis_ok = redis_svc.ping()
    
    return {
        "status": "healthy" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected"
    }


@router.get("/status", response_model=SystemStatus)
async def get_system_status(user: User = Depends(get_current_user)):
    """Get status of all system components."""
    redis_svc = get_redis_service()
    
    return SystemStatus(
        smtp_ingestor=redis_svc.check_service_health("smtp-ingestor"),
        redis="online" if redis_svc.ping() else "offline",
        alert_processor=redis_svc.check_service_health("alert-processor"),
        ollama=check_ollama_health()
    )


@router.get("/metrics")
async def get_queue_metrics(user: User = Depends(get_current_user)):
    """Get queue depth and processing metrics."""
    redis_svc = get_redis_service()
    metrics = redis_svc.get_metrics()
    
    return {
        "queue_depth": redis_svc.get_queue_depth(),
        "dlq_depth": redis_svc.get_dlq_depth(),
        "retry_queue_depth": redis_svc.get_retry_queue_depth(),
        "processed_count": int(metrics.get("processed", 0)),
        "error_count": int(metrics.get("errors", 0)),
        "muted_count": int(metrics.get("muted", 0)),
        "retries_scheduled": int(metrics.get("retries_scheduled", 0)),
        "retries_succeeded": int(metrics.get("retries_succeeded", 0)),
    }


@router.get("/queue/dlq")
async def get_dlq_items(limit: int = 50, user: User = Depends(get_current_user)):
    """Get items from the Dead Letter Queue."""
    redis_svc = get_redis_service()
    return redis_svc.get_dlq_items(limit)


@router.get("/queue/retry")
async def get_retry_items(limit: int = 50, user: User = Depends(get_current_user)):
    """Get items from the retry queue."""
    redis_svc = get_redis_service()
    return redis_svc.get_retry_queue_items(limit)


@router.post("/queue/dlq/flush")
async def flush_dlq(user: User = Depends(get_current_user)):
    """Flush all DLQ items."""
    redis_svc = get_redis_service()
    count = redis_svc.flush_dlq()
    redis_svc.add_log("WARNING", "api", f"DLQ flushed: {count} items removed")
    return {"message": f"DLQ flushed: {count} items removed", "count": count}


@router.post("/queue/dlq/{index}/requeue")
async def requeue_dlq_item(index: int, user: User = Depends(get_current_user)):
    """Move a DLQ item back to the main queue for reprocessing."""
    redis_svc = get_redis_service()
    success = redis_svc.requeue_dlq_item(index)
    if success:
        redis_svc.add_log("INFO", "api", f"DLQ item {index} requeued for reprocessing")
        return {"message": f"Item {index} requeued successfully"}
    return {"message": f"Item {index} not found or requeue failed"}
