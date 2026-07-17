"""
SSE (Server-Sent Events) API - Real-time dashboard updates.
"""
import asyncio
import json
import time
import os
import httpx
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from jose import jwt, JWTError

from config import get_settings
from services.redis_service import get_redis_service

router = APIRouter(prefix="/sse", tags=["sse"])

settings = get_settings()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1/chat/completions")

# Ollama health cache (shared with health.py pattern)
_ollama_cache = {"status": "unknown", "checked_at": 0}
_OLLAMA_TTL = 60


async def _check_ollama() -> str:
    """Check Ollama health (cached)."""
    now = time.time()
    if now - _ollama_cache["checked_at"] < _OLLAMA_TTL:
        return _ollama_cache["status"]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                OLLAMA_BASE_URL,
                json={"model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
                      "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                headers={"Content-Type": "application/json"},
            )
            status = "online" if resp.status_code == 200 else "offline"
    except Exception:
        status = "offline"
    _ollama_cache["status"] = status
    _ollama_cache["checked_at"] = now
    return status


def _verify_token(token: str) -> bool:
    """Verify JWT token for SSE (can't use header-based auth with EventSource)."""
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return True
    except JWTError:
        return False


async def _build_dashboard_event(redis_svc) -> str:
    """Build a single SSE data payload with status + metrics + recent alerts."""
    # Status
    ollama_status = await _check_ollama()
    status = {
        "smtp_ingestor": redis_svc.check_service_health("smtp-ingestor"),
        "redis": "online" if redis_svc.ping() else "offline",
        "alert_processor": redis_svc.check_service_health("alert-processor"),
        "ollama": ollama_status,
    }

    # Metrics
    metrics_raw = redis_svc.get_metrics()
    metrics = {
        "queue_depth": redis_svc.get_queue_depth(),
        "dlq_depth": redis_svc.get_dlq_depth(),
        "retry_queue_depth": redis_svc.get_retry_queue_depth(),
        "processed_count": int(metrics_raw.get("processed", 0)),
        "error_count": int(metrics_raw.get("errors", 0)),
        "muted_count": int(metrics_raw.get("muted", 0)),
        "retries_scheduled": int(metrics_raw.get("retries_scheduled", 0)),
        "retries_succeeded": int(metrics_raw.get("retries_succeeded", 0)),
    }

    # Recent alerts (last 5)
    alerts = redis_svc.list_alerts(limit=5, offset=0)

    payload = json.dumps({
        "status": status,
        "metrics": metrics,
        "alerts": alerts,
        "timestamp": time.time(),
    })

    return f"data: {payload}\n\n"


@router.get("/dashboard")
async def sse_dashboard(token: str = Query(..., description="JWT token for authentication")):
    """SSE stream for real-time dashboard updates (every 3 seconds)."""
    if not _verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    redis_svc = get_redis_service()

    async def event_generator():
        try:
            while True:
                try:
                    event = await _build_dashboard_event(redis_svc)
                    yield event
                except Exception:
                    # If Redis disconnects, send error event
                    yield f"data: {json.dumps({'error': 'data_fetch_failed'})}\n\n"
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )
