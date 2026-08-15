"""
SSE (Server-Sent Events) API - Real-time dashboard updates.
"""
import asyncio
import json
import time
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from auth import User, get_current_user

from services.redis_service import get_redis_service
from routes.health import get_ai_chain_health

router = APIRouter(prefix="/sse", tags=["sse"])

async def _build_dashboard_event(redis_svc) -> str:
    """Build a single SSE data payload with status + metrics + recent alerts."""
    # Status
    ollama_status = get_ai_chain_health(redis_svc)["status"]
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
        "processed_count_24h": int(metrics_raw.get("processed_24h", 0)),
        "error_count_24h": int(metrics_raw.get("errors_24h", 0)),
        "muted_count": int(metrics_raw.get("muted", 0)),
        "retries_scheduled": int(metrics_raw.get("retries_scheduled", 0)),
        "retries_succeeded": int(metrics_raw.get("retries_succeeded", 0)),
        "storm_suppressed": int(metrics_raw.get("storm_suppressed", 0)),
    }

    # Incident-centric command center needs enough active signals to group reliably.
    alerts = redis_svc.list_alerts(limit=30, offset=0, status="open")

    payload = json.dumps({
        "status": status,
        "metrics": metrics,
        "alerts": alerts,
        "timestamp": time.time(),
    })

    return f"data: {payload}\n\n"


@router.get("/dashboard")
async def sse_dashboard(user: User = Depends(get_current_user)):
    """Cookie-authenticated SSE stream without credentials in URLs."""
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
