"""
Alerts API - CRUD operations for alerts.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List

from auth import User, get_current_user
from services.redis_service import get_redis_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=List[dict])
async def list_alerts(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List alerts with pagination and optional filtering."""
    redis_svc = get_redis_service()
    return redis_svc.list_alerts(limit=limit, offset=offset, status=status, severity=severity)


@router.get("/count")
async def count_alerts(user: User = Depends(get_current_user)):
    """Get total alert count."""
    redis_svc = get_redis_service()
    return {"count": redis_svc.count_alerts()}


@router.get("/{alert_id}", response_model=dict)
async def get_alert(alert_id: str, user: User = Depends(get_current_user)):
    """Get a specific alert by ID."""
    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.patch("/{alert_id}/status")
async def update_alert_status(alert_id: str, status: str, user: User = Depends(get_current_user)):
    """Update alert status (new, acknowledged, resolved)."""
    if status not in ["new", "acknowledged", "resolved"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    redis_svc = get_redis_service()
    if not redis_svc.update_alert_status(alert_id, status):
        raise HTTPException(status_code=404, detail="Alert not found")
    
    redis_svc.add_log("INFO", "api", f"Alert {alert_id} status updated to {status}")
    return {"message": f"Alert status updated to {status}"}


@router.post("/{alert_id}/rerun-ai")
async def rerun_ai_analysis(alert_id: str, user: User = Depends(get_current_user)):
    """Re-run AI analysis for an alert (queues for reprocessing)."""
    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Re-queue the alert for processing
    email_data = {
        "from": alert.get("from_email", ""),
        "to": alert.get("to_email", ""),
        "subject": alert.get("subject", ""),
        "text": alert.get("body", ""),
        "html": alert.get("html", ""),
        "reprocess_alert_id": alert_id,
    }
    
    trace_id = redis_svc.push_to_queue(email_data)
    redis_svc.add_log("INFO", "api", f"Alert {alert_id} queued for re-analysis", {"trace_id": trace_id})
    
    return {"message": "Alert queued for re-analysis", "trace_id": trace_id}


@router.post("/{alert_id}/resend")
async def resend_notification(alert_id: str, user: User = Depends(get_current_user)):
    """Re-send notification for an alert."""
    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    # Queue for resend (processor will detect and resend)
    email_data = {
        "from": alert.get("from_email", ""),
        "to": alert.get("to_email", ""),
        "subject": alert.get("subject", ""),
        "text": alert.get("body", ""),
        "html": alert.get("html", ""),
        "resend_alert_id": alert_id,
        "ai_raw": alert.get("ai_raw", ""),
    }
    
    trace_id = redis_svc.push_to_queue(email_data)
    redis_svc.add_log("INFO", "api", f"Alert {alert_id} queued for resend", {"trace_id": trace_id})
    
    return {"message": "Alert queued for resend", "trace_id": trace_id}
