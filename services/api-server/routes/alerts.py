"""
Alerts API - CRUD operations for alerts.
"""
# pyrefly: ignore [missing-import]
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List

from auth import User, get_current_user, require_admin, require_operator
from services.redis_service import get_redis_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/backfill-ai")
async def backfill_missing_ai(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_admin),
):
    """Queue missing/failed AI analyses without changing incidents or notifications."""
    redis_svc = get_redis_service()
    alert_ids = redis_svc.client.zrange("alerts:index", 0, -1)
    queued = 0

    for alert_id in alert_ids:
        if queued >= limit:
            break
        alert = redis_svc.get_alert(alert_id)
        if not alert or alert.get("ai_raw"):
            continue
        if alert.get("analysis_status") == "queued":
            continue

        event_data = {
            "from": alert.get("from_email", ""),
            "to": alert.get("to_email", ""),
            "subject": alert.get("subject", ""),
            "text": alert.get("body", ""),
            "html": alert.get("html", ""),
            "analysis_only_alert_id": alert_id,
        }
        # A separate low-priority queue prevents historical enrichment from
        # delaying newly arriving operational alerts.
        redis_svc.client.rpush("alert_backfill_queue", json.dumps(event_data))
        redis_svc.client.hset(
            f"alert:{alert_id}",
            mapping={"analysis_status": "queued"},
        )
        queued += 1

    redis_svc.add_log(
        "INFO", "api", f"AI backfill queued: {queued} alerts",
        {"requested_by": user.username, "limit": limit},
    )
    return {
        "queued": queued,
        "limit": limit,
        "queue": "low_priority_backfill",
        "notification_mode": "disabled",
    }


@router.get("", response_model=List[dict])
async def list_alerts(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List alerts with pagination and optional filtering."""
    redis_svc = get_redis_service()
    return redis_svc.list_alerts(limit=limit, offset=offset, status=status, severity=severity, q=q)


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


@router.get("/{alert_id}/timeline")
async def get_alert_timeline(alert_id: str, user: User = Depends(get_current_user)):
    """Return ordered incident, delivery, and operator events for one alert."""
    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    events = [{
        "type": "CREATED", "status": alert.get("status", "new"),
        "alert_id": alert_id, "occurred_at": alert.get("created_at"),
        "detail": alert.get("main_message") or alert.get("subject", ""),
    }]
    incident_key = alert.get("incident_key", "")
    if incident_key:
        for event_id, fields in redis_svc.client.xrange(f"incident:events:{incident_key}", count=1000):
            events.append({"id": event_id, "type": fields.get("action", "EVENT"), **fields})
    try:
        history = json.loads(alert.get("action_history", "[]") or "[]")
        for item in history:
            events.append({
                "type": "OPERATOR", "status": item.get("status", ""),
                "actor": item.get("user", ""), "occurred_at": item.get("timestamp"),
                "detail": f"Status changed to {item.get('status', '')}",
            })
    except (TypeError, json.JSONDecodeError):
        pass
    events.sort(key=lambda item: str(item.get("occurred_at", "")))
    return {"incident_key": incident_key, "events": events}


@router.get("/{alert_id}/operations")
async def get_alert_operations(alert_id: str, user: User = Depends(get_current_user)):
    """Explain notification decisions, impact, previews, and delivery state."""
    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    def json_list(value):
        try:
            parsed = json.loads(value or "[]")
            return [str(item) for item in parsed if item] if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    incident = {}
    if alert.get("incident_key"):
        raw = redis_svc.client.get(f"incident:{alert['incident_key']}")
        try:
            incident = json.loads(raw) if raw else {}
        except (TypeError, json.JSONDecodeError):
            incident = {}

    resources = set()
    def add_resources(values):
        for raw_value in values:
            # Older analyses occasionally returned one comma-delimited string
            # alongside its individual resources. Flatten it for impact counts.
            for value in str(raw_value).split(","):
                value = value.strip()
                if value and value.lower() not in {"unknown", "none", "n/a"}:
                    resources.add(value)

    add_resources(json_list(alert.get("target_resources")))
    if alert.get("target_resource"):
        add_resources([alert["target_resource"]])
    for value in incident.get("target_resources", []) or incident.get("resources", []) or []:
        if value:
            add_resources([value])
    if incident.get("target_resource"):
        add_resources([incident["target_resource"]])

    suppression = alert.get("notification_suppressed", "")
    reason_map = {
        "global_storm": "Global storm notification cap was exceeded",
        "storm_cooldown": "Incident update cooldown prevented another notification",
        "orphan_resolve": "Recovery had no matching open incident",
        "redundant_resolve": "Recovery was already represented by the incident state",
        "exact_duplicate": "Exact payload duplicate was recorded without re-notification",
    }
    correlation_action = alert.get("correlation_action", "NEW")
    if suppression:
        decision = "suppressed"
        decision_reason = reason_map.get(suppression, suppression.replace("_", " ").title())
    elif correlation_action == "MERGE":
        decision = "updated"
        decision_reason = "Merged into an open incident and existing destination messages were updated"
    else:
        decision = "sent"
        decision_reason = "Notification was eligible for configured routing targets"

    raw_delivery = redis_svc.client.hgetall(f"delivery:{alert_id}") or {}
    delivery = []
    for channel_id, raw in raw_delivery.items():
        try:
            item = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            item = {"status": "unknown", "detail": str(raw)}
        config = redis_svc.client.hgetall(f"notification_channel:{channel_id}") or {}
        delivery.append({
            "channel_id": channel_id,
            "channel_name": config.get("name") or channel_id,
            "channel_type": config.get("type") or "legacy",
            "status": item.get("status", "unknown"),
            "attempt": int(item.get("attempt", 1) or 1),
            "updated_at": item.get("updated_at", ""),
            "detail": item.get("detail", ""),
        })

    delivery_events = []
    if alert.get("incident_key"):
        delivery_events = [
            fields for _, fields in redis_svc.client.xrange(
                f"incident:events:{alert['incident_key']}", count=1000,
            ) if fields.get("action") == "DELIVERY"
        ]
    exhausted_total = sum(event.get("status") == "exhausted" for event in delivery_events)
    consecutive_failures = 0
    for event in reversed(delivery_events):
        state = event.get("status", "")
        if state == "delivered":
            break
        if state in {"failed", "exhausted"}:
            consecutive_failures += 1
    last_delivery_status = delivery_events[-1].get("status", "") if delivery_events else ""
    delivery_risk = {
        "degraded": bool(last_delivery_status == "exhausted" or consecutive_failures >= 2),
        "exhausted_total": exhausted_total,
        "consecutive_failures": consecutive_failures,
        "last_status": last_delivery_status,
        "reason": (
            "This incident has exhausted delivery retries"
            if last_delivery_status == "exhausted" else
            "This incident has repeated delivery failures"
            if consecutive_failures >= 2 else ""
        ),
    }

    occurrences = int(incident.get("occurrences", 1) or 1)
    resource_count = len(resources)
    if resource_count >= 5 or occurrences >= 10:
        radius = "wide"
    elif resource_count >= 2 or occurrences >= 3:
        radius = "moderate"
    else:
        radius = "contained"

    return {
        "decision": {
            "outcome": decision,
            "code": suppression or correlation_action.lower(),
            "reason": decision_reason,
            "storm_window_count": int(alert.get("storm_window_count", 0) or 0),
        },
        "impact": {
            "resources": sorted(resources),
            "resource_count": resource_count,
            "occurrences": occurrences,
            "system": alert.get("system_name", "") or incident.get("system_name", ""),
            "category": alert.get("category", ""),
            "source": alert.get("from_email", ""),
            "blast_radius": radius,
        },
        "analysis_quality": {
            "evidence_status": alert.get("evidence_status", "unknown"),
            "model_confidence": float(alert.get("model_confidence", alert.get("confidence", 0)) or 0),
            "evidence_confidence": float(alert.get("evidence_confidence", alert.get("confidence", 0)) or 0),
            "validation_warnings": json_list(alert.get("validation_warnings")),
            "taxonomy_overrides": json_list(alert.get("taxonomy_overrides")),
            "event_state": alert.get("event_state", ""),
            "incident_severity": alert.get("incident_severity", alert.get("severity", "")),
        },
        "previews": {
            "telegram": alert.get("notification_preview_telegram", ""),
            "matrix": alert.get("notification_preview_matrix", ""),
        },
        "delivery": delivery,
        "delivery_risk": delivery_risk,
    }


@router.patch("/{alert_id}/status")
async def update_alert_status(alert_id: str, status: str, user: User = Depends(require_operator)):
    """Update alert status (new, acknowledged, resolved)."""
    if status not in ["new", "acknowledged", "resolved"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    redis_svc = get_redis_service()
    alert = redis_svc.get_alert(alert_id)
    if not redis_svc.update_alert_status(alert_id, status):
        raise HTTPException(status_code=404, detail="Alert not found")

    redis_svc.add_log("INFO", "api", f"Alert {alert_id} status updated to {status}")
    if alert and alert.get("incident_key"):
        redis_svc.client.xadd(f"incident:events:{alert['incident_key']}", {
            "alert_id": alert_id, "action": "OPERATOR", "status": status,
            "actor": user.username, "detail": f"Status changed to {status}",
            "occurred_at": __import__("datetime").datetime.utcnow().isoformat(),
        }, maxlen=1000, approximate=True)

    # Notify processor to update telegram/matrix messages
    event_data = {
        "manual_status_update": True,
        "alert_id": alert_id,
        "new_status": status,
        "user": user.username if user else "UI User"
    }
    redis_svc.push_to_queue(event_data)

    return {"message": f"Alert status updated to {status}"}


@router.post("/{alert_id}/rerun-ai")
async def rerun_ai_analysis(alert_id: str, user: User = Depends(require_operator)):
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
async def resend_notification(alert_id: str, user: User = Depends(require_operator)):
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


@router.post("/force-summary")
async def force_daily_summary(user: User = Depends(require_operator)):
    """Force send the daily summary immediately."""
    redis_svc = get_redis_service()
    event_data = {
        "force_daily_summary": True,
        "user": user.username if user else "UI User"
    }
    trace_id = redis_svc.push_to_queue(event_data)
    redis_svc.add_log("INFO", "api", "Forced daily summary generation requested", {"trace_id": trace_id})

    return {"message": "Daily summary generation triggered", "trace_id": trace_id}
