"""
Health and Status API - System health checks.
"""
import time

from fastapi import APIRouter, Depends, Response

from auth import User, get_current_user, require_admin
from services.redis_service import get_redis_service
from models import SystemStatus, QueueMetrics

router = APIRouter(tags=["health"])

def get_ai_chain_health(redis_svc) -> dict:
    """Build health from the providers actually selected by routing/failover."""
    providers = redis_svc.get_ai_providers()
    providers.sort(key=lambda p: (not p.get("is_default"), not p.get("is_fallback"), p.get("name", "")))
    result = []
    for provider in providers:
        metrics = redis_svc.client.hgetall(f"metrics:ai:provider:{provider['id']}")
        attempts = int(metrics.get("attempts", 0) or 0)
        successes = int(metrics.get("success", 0) or 0)
        failures = int(metrics.get("failure", 0) or 0)
        last_success = float(metrics.get("last_success_at", 0) or 0)
        last_failure = float(metrics.get("last_failure_at", 0) or 0)
        if not attempts:
            provider_status = "unknown"
        elif last_success >= last_failure:
            provider_status = "online"
        else:
            provider_status = "offline"
        latency_total = float(metrics.get("latency_total_seconds", 0) or 0)
        result.append({
            "id": provider["id"],
            "name": provider.get("name", ""),
            "model": provider.get("model", ""),
            "role": "default" if provider.get("is_default") else "fallback" if provider.get("is_fallback") else "standby",
            "status": provider_status,
            "attempts": attempts,
            "success_rate": round(successes / attempts, 4) if attempts else None,
            "failures": failures,
            "fallback_uses": int(metrics.get("fallback_uses", 0) or 0),
            "average_latency_seconds": round(latency_total / attempts, 2) if attempts else None,
            "last_success_at": last_success or None,
            "last_failure_at": last_failure or None,
            "last_error": metrics.get("last_error", ""),
        })
    default_online = any(p["role"] == "default" and p["status"] == "online" for p in result)
    fallback_online = any(p["role"] == "fallback" and p["status"] == "online" for p in result)
    overall = "online" if default_online else "degraded" if fallback_online else "unknown" if all(p["status"] == "unknown" for p in result) else "offline"
    return {"status": overall, "providers": result}


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

    ai_health = get_ai_chain_health(redis_svc)

    return SystemStatus(
        smtp_ingestor=redis_svc.check_service_health("smtp-ingestor"),
        redis="online" if redis_svc.ping() else "offline",
        alert_processor=redis_svc.check_service_health("alert-processor"),
        ollama=ai_health["status"]
    )


@router.get("/ai-health")
async def get_ai_health(user: User = Depends(get_current_user)):
    return get_ai_chain_health(get_redis_service())


def get_observability_state(redis_svc) -> dict:
    metrics = redis_svc.client.hgetall("metrics:self_monitor") or {}
    updated_at = float(metrics.get("updated_at", 0) or 0)
    stale = not updated_at or time.time() - updated_at > 180
    state = {
        "disk": "unknown" if stale else metrics.get("disk_state", "unknown"),
        "disk_used_percent": float(metrics.get("disk_used_percent", 0) or 0),
        "disk_free_bytes": int(float(metrics.get("disk_free_bytes", 0) or 0)),
        "loki": "unknown" if stale else metrics.get("loki_status", "unknown"),
        "alloy": "unknown" if stale else metrics.get("alloy_status", "unknown"),
        "loki_volume_bytes": int(float(metrics.get("loki_volume_bytes", 0) or 0)),
        "loki_growth_mib_per_hour": float(metrics.get("loki_growth_mib_per_hour", 0) or 0),
        "loki_growth": "unknown" if stale else metrics.get("loki_growth_state", "unknown"),
        "canary": "unknown" if stale else metrics.get("canary_status", "unknown"),
        "ai_chain": "unknown" if stale else metrics.get("ai_chain_status", "unknown"),
        "ai_chain_detail": metrics.get("ai_chain_detail", ""),
        "fallback_canary": "unknown" if stale else metrics.get("fallback_canary_status", "unknown"),
        "fallback_canary_detail": metrics.get("fallback_canary_detail", ""),
        "fallback_canary_provider": metrics.get("fallback_canary_provider", ""),
        "fallback_canary_latency_seconds": float(metrics.get("fallback_canary_latency_seconds", 0) or 0),
        "fallback_canary_last_result_at": float(metrics.get("fallback_canary_last_result_at", 0) or 0) or None,
        "canary_last_result_at": float(metrics.get("canary_last_result_at", 0) or 0) or None,
        "updated_at": updated_at or None,
        "stale": stale,
    }
    component_states = [state["disk"], state["loki"], state["alloy"], state["loki_growth"], state["canary"], state["ai_chain"]]
    if stale or any(value in {"critical", "offline"} for value in component_states):
        state["status"] = "critical"
    elif any(value in {"warning", "checking", "unknown"} for value in component_states):
        state["status"] = "warning"
    else:
        state["status"] = "healthy"
    return state


@router.get("/observability-health")
async def get_observability_health(user: User = Depends(get_current_user)):
    return get_observability_state(get_redis_service())


@router.get("/metrics")
async def get_queue_metrics(user: User = Depends(get_current_user)):
    """Get queue depth and processing metrics."""
    redis_svc = get_redis_service()
    metrics = redis_svc.get_metrics()
    quality = redis_svc.client.hgetall("metrics:analysis_quality") or {}

    dlq_lifecycle = redis_svc.get_dlq_lifecycle_counts()
    return {
        "queue_depth": redis_svc.get_queue_depth(),
        "dlq_depth": redis_svc.get_dlq_depth(),
        "dlq_active_depth": dlq_lifecycle.get("active", 0),
        "dlq_superseded_depth": dlq_lifecycle.get("superseded", 0) + dlq_lifecycle.get("historical", 0),
        "retry_queue_depth": redis_svc.get_retry_queue_depth(),
        "processed_count": int(metrics.get("processed", 0)),
        "error_count": int(metrics.get("errors", 0)),
        "muted_count": int(metrics.get("muted", 0)),
        "retries_scheduled": int(metrics.get("retries_scheduled", 0)),
        "retries_succeeded": int(metrics.get("retries_succeeded", 0)),
        "stream_pending": redis_svc.get_stream_pending(),
        "backfill_queue_depth": redis_svc.client.llen("alert_backfill_queue"),
        "delivery_failures": int(metrics.get("delivery_failures", 0)),
        "analysis_quality": {key: int(value or 0) for key, value in quality.items()},
    }


def _prom_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


@router.get("/metrics/prometheus", response_class=Response)
async def get_prometheus_metrics(user: User = Depends(get_current_user)):
    """Prometheus text exposition for queue, processor, source, rule, and provider metrics."""
    redis_svc = get_redis_service()
    processor = redis_svc.get_metrics()
    dlq_lifecycle = redis_svc.get_dlq_lifecycle_counts()
    ingestion = redis_svc.client.hgetall("metrics:ingestion") or {}
    quality = redis_svc.client.hgetall("metrics:analysis_quality") or {}
    values = {
        "alertflow_queue_depth": redis_svc.get_queue_depth(),
        "alertflow_stream_pending": redis_svc.get_stream_pending(),
        "alertflow_dlq_depth": redis_svc.get_dlq_depth(),
        "alertflow_dlq_active_depth": dlq_lifecycle.get("active", 0),
        "alertflow_dlq_superseded_depth": dlq_lifecycle.get("superseded", 0) + dlq_lifecycle.get("historical", 0),
        "alertflow_backfill_queue_depth": redis_svc.client.llen("alert_backfill_queue"),
        "alertflow_alerts_processed_total": int(processor.get("processed", 0)),
        "alertflow_processing_errors_total": int(processor.get("errors", 0)),
        "alertflow_delivery_failures_total": int(processor.get("delivery_failures", 0)),
        "alertflow_smtp_accepted_total": int(ingestion.get("smtp_accepted", 0) or 0),
        "alertflow_smtp_processed_total": int(ingestion.get("processor_received_smtp", 0) or 0),
        "alertflow_retries_superseded_total": int(processor.get("retries_superseded", 0) or 0),
    }
    self_monitor = get_observability_state(redis_svc)
    values.update({
        "alertflow_disk_used_percent": self_monitor["disk_used_percent"],
        "alertflow_loki_volume_bytes": self_monitor["loki_volume_bytes"],
        "alertflow_loki_growth_mib_per_hour": self_monitor["loki_growth_mib_per_hour"],
        "alertflow_observability_canary_ok": 1 if self_monitor["canary"] == "healthy" else 0,
        "alertflow_loki_up": 1 if self_monitor["loki"] == "healthy" else 0,
        "alertflow_alloy_up": 1 if self_monitor["alloy"] == "healthy" else 0,
        "alertflow_ai_fallback_canary_ok": 1 if self_monitor["fallback_canary"] == "healthy" else 0,
    })
    lines = ["# AlertFlow operational metrics"]
    lines.extend(f"{name} {value}" for name, value in values.items())
    for source, count in redis_svc.client.hgetall("metrics:source:received").items():
        lines.append(f'alertflow_source_alerts_total{{source="{_prom_label(source)}"}} {int(count)}')
    for quality_type, count in quality.items():
        lines.append(f'alertflow_analysis_quality_total{{type="{_prom_label(quality_type)}"}} {int(count)}')
    for rule_id, count in redis_svc.client.hgetall("metrics:routing:matched").items():
        lines.append(f'alertflow_routing_matches_total{{rule_id="{_prom_label(rule_id)}"}} {int(count)}')
    for provider in get_ai_chain_health(redis_svc)["providers"]:
        labels = f'provider_id="{_prom_label(provider["id"])}",role="{provider["role"]}"'
        lines.append(f'alertflow_ai_provider_attempts_total{{{labels}}} {provider["attempts"]}')
        lines.append(f'alertflow_ai_provider_failures_total{{{labels}}} {provider["failures"]}')
        if provider["average_latency_seconds"] is not None:
            lines.append(f'alertflow_ai_provider_average_latency_seconds{{{labels}}} {provider["average_latency_seconds"]}')
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


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
async def flush_dlq(user: User = Depends(require_admin)):
    """Flush all DLQ items."""
    redis_svc = get_redis_service()
    count = redis_svc.flush_dlq()
    redis_svc.add_log("WARNING", "api", f"DLQ flushed: {count} items removed")
    return {"message": f"DLQ flushed: {count} items removed", "count": count}


@router.post("/queue/dlq/{index}/requeue")
async def requeue_dlq_item(index: int, user: User = Depends(require_admin)):
    """Move a DLQ item back to the main queue for reprocessing."""
    redis_svc = get_redis_service()
    success = redis_svc.requeue_dlq_item(index)
    if success:
        redis_svc.add_log("INFO", "api", f"DLQ item {index} requeued for reprocessing")
        return {"message": f"Item {index} requeued successfully"}
    return {"message": f"Item {index} not found or requeue failed"}
