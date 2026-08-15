"""
AlertFlow Alert Processor

Consumes emails from Redis queue, analyzes with Ollama AI, and dispatches notifications.
Uses routing rules to determine notification targets.
"""
import os
import json
import redis
import logging
import time
import uuid
import hashlib
import threading
import socket
import shutil
import requests
import pytz
from datetime import datetime

from ai_service import analyze_email, format_alert, format_for_matrix, probe_fallback_provider
from routing import get_routing_targets
from utils import (html_to_text, send_telegram, send_telegram_auto, send_matrix_message,
                   send_webhook, send_sms, delete_telegram_message, redact_matrix_message)
from correlation import IncidentTracker
from resolution import build_resolution_cards, extract_source_timestamp
from source_adapters import build_correlation_identity, normalize_alert, split_grafana_mixed_payload

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Alert-Processor")

# Config
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_QUEUE = "alert_queue"
REDIS_STREAM = "alerts:stream"
REDIS_STREAM_GROUP = "alert-processors"
REDIS_CONSUMER = f"{socket.gethostname()}-{os.getpid()}"
REDIS_BACKFILL_QUEUE = "alert_backfill_queue"
REDIS_DLQ = "alert_dead_letter_queue"

# Default destinations
TELEGRAM_DEFAULT_CHAT_ID = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
TELEGRAM_DEFAULT_THREAD_ID = os.getenv("TELEGRAM_DEFAULT_THREAD_ID", "0")
MATRIX_DEFAULT_ROOM_ID = os.getenv("MATRIX_DEFAULT_ROOM_ID", "")
DEFAULT_NOTIFICATION_CHANNEL = os.getenv("DEFAULT_NOTIFICATION_CHANNEL", "both").lower()
FAILOVER_ENABLED = os.getenv("FAILOVER_ENABLED", "true").lower() == "true"
DAILY_SUMMARY_TIME = os.getenv("DAILY_SUMMARY_TIME", "08:00")
DAILY_SUMMARY_TIMEZONE = os.getenv("DAILY_SUMMARY_TIMEZONE", "Asia/Tehran")
STALE_INCIDENT_HOURS = int(os.getenv("STALE_INCIDENT_HOURS", "72"))
DISK_WARNING_PERCENT = float(os.getenv("DISK_WARNING_PERCENT", "70"))
DISK_CRITICAL_PERCENT = float(os.getenv("DISK_CRITICAL_PERCENT", "85"))
LOKI_GROWTH_WARNING_MB_PER_HOUR = float(os.getenv("LOKI_GROWTH_WARNING_MB_PER_HOUR", "250"))
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100").rstrip("/")
ALLOY_URL = os.getenv("ALLOY_URL", "http://alloy:12345").rstrip("/")
LOKI_DATA_PATH = os.getenv("LOKI_DATA_PATH", "/observability/loki")
ALERT_STORM_WINDOW_SECONDS = int(os.getenv("ALERT_STORM_WINDOW_SECONDS", "300"))
ALERT_STORM_THRESHOLD = int(os.getenv("ALERT_STORM_THRESHOLD", "5"))
ALERT_STORM_COOLDOWN_SECONDS = int(os.getenv("ALERT_STORM_COOLDOWN_SECONDS", "300"))
GLOBAL_STORM_MAX_NOTIFICATIONS = int(os.getenv("GLOBAL_STORM_MAX_NOTIFICATIONS", "20"))
GLOBAL_STORM_WINDOW_SECONDS = int(os.getenv("GLOBAL_STORM_WINDOW_SECONDS", "300"))
STORM_SUMMARY_INTERVAL_SECONDS = int(os.getenv("STORM_SUMMARY_INTERVAL_SECONDS", "300"))
INCIDENT_SLA_MINUTES = int(os.getenv("INCIDENT_SLA_MINUTES", "60"))
INCIDENT_RETENTION_DAYS = int(os.getenv("INCIDENT_RETENTION_DAYS", "7"))
DLQ_RETENTION_DAYS = int(os.getenv("DLQ_RETENTION_DAYS", "7"))
DLQ_MAX_ITEMS = int(os.getenv("DLQ_MAX_ITEMS", "1000"))
DISK_MONITOR_PATH = os.getenv("DISK_MONITOR_PATH", LOKI_DATA_PATH)

# Redis client (global)
redis_client = None


def add_log(level: str, message: str, data: dict = None):
    """Add structured log to Redis stream."""
    global redis_client
    try:
        if redis_client:
            entry = {
                "level": level,
                "service": "alert-processor",
                "message": message,
                "data": json.dumps(data or {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
            redis_client.xadd("stream:logs", entry, maxlen=2000)
    except Exception:
        pass


class RedisUIHandler(logging.Handler):
    """Pipes standard Python ERROR logs directly to the Web UI Dashboard."""
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            try:
                # Prevent infinite loop if Redis itself fails
                if getattr(self, '_handling', False):
                    return
                self._handling = True
                msg = self.format(record)
                add_log("ERROR", f"[{record.name}] {msg}")
                self._handling = False
            except Exception:
                pass

ui_handler = RedisUIHandler()
ui_handler.setLevel(logging.ERROR)
ui_handler.setFormatter(logging.Formatter('%(message)s'))
logging.getLogger().addHandler(ui_handler)


def add_relay_log(sender: str, subject: str, channel: str, destination: str, success: bool):
    """Add relay log entry."""
    global redis_client
    try:
        log_data = {
            "id": str(uuid.uuid4())[:8],
            "sender": sender,
            "subject": subject[:100],
            "channel": channel,
            "destination": destination,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        }
        redis_client.zadd("relay_logs", {json.dumps(log_data): time.time()})
    except Exception:
        pass


def record_delivery(alert_id: str, channel_id: str, status: str, detail: str = "", attempt: int = 1):
    """Persist per-channel delivery state without credentials."""
    if not alert_id or not channel_id:
        return
    try:
        key = f"delivery:{alert_id}"
        updated_at = datetime.utcnow().isoformat()
        redis_client.hset(key, channel_id, json.dumps({
            "status": status,
            "detail": detail[:500],
            "attempt": attempt,
            "updated_at": updated_at,
        }))
        incident_key = redis_client.hget(f"alert:{alert_id}", "incident_key")
        if incident_key:
            redis_client.xadd(f"incident:events:{incident_key}", {
                "alert_id": alert_id, "action": "DELIVERY", "status": status,
                "channel_id": channel_id, "detail": detail[:300],
                "attempt": str(attempt), "occurred_at": updated_at,
            }, maxlen=1000, approximate=True)
        redis_client.expire(key, 86400 * 7)
        if status in {"failed", "exhausted"}:
            increment_metric("delivery_failures")
        elif status == "delivered":
            increment_metric("delivery_successes")
    except Exception as exc:
        logger.warning("Could not persist delivery state for %s/%s: %s", alert_id, channel_id, exc)


def set_heartbeat():
    """Set heartbeat in Redis."""
    global redis_client
    try:
        if redis_client:
            data = json.dumps({"timestamp": time.time(), "status": "ok"})
            redis_client.setex("heartbeat:alert-processor", 15, data)
    except:
        pass


def heartbeat_loop():
    """Background thread for heartbeat."""
    while True:
        set_heartbeat()
        time.sleep(5)


def cleanup_old_data():
    """Periodically clean up old alerts, DLQ, and logs based on retention settings."""
    global redis_client
    while True:
        try:
            if redis_client:
                # Get retention period from settings:general or env
                settings = redis_client.hgetall("settings:general")
                retention_days = int(settings.get(b"alert_retention_days", settings.get("alert_retention_days", os.environ.get("ALERT_RETENTION_DAYS", "14"))))

                if retention_days > 0:
                    cutoff_time = time.time() - (retention_days * 24 * 3600)

                    # 1. Clean up alerts:index and hashes
                    old_alert_ids = redis_client.zrangebyscore("alerts:index", 0, cutoff_time)
                    if old_alert_ids:
                        # Convert bytes to str if needed
                        old_ids_str = [aid.decode('utf-8') if isinstance(aid, bytes) else aid for aid in old_alert_ids]

                        # Delete hashes
                        read_pipe = redis_client.pipeline(transaction=False)
                        for aid in old_ids_str:
                            read_pipe.hmget(f"alert:{aid}", "status", "severity", "category")
                        old_metadata = read_pipe.execute()
                        pipe = redis_client.pipeline(transaction=False)
                        for aid, metadata in zip(old_ids_str, old_metadata):
                            pipe.delete(f"alert:{aid}")
                            pipe.delete(f"delivery:{aid}")
                            status, severity, category = metadata
                            pipe.zrem(f"alerts:status:{(status or 'new').lower()}", aid)
                            pipe.zrem(f"alerts:severity:{(severity or 'unclassified').lower()}", aid)
                            pipe.zrem(f"alerts:category:{(category or 'unclassified').lower()}", aid)
                        pipe.execute()

                        # Remove from index
                        redis_client.zremrangebyscore("alerts:index", 0, cutoff_time)
                        logger.info(f"Cleaned up {len(old_ids_str)} old alerts")

                    # 2. Clean up relay_logs
                    redis_client.zremrangebyscore("relay_logs", 0, cutoff_time)

                    # 3. Retire legacy closed incidents that predate TTL-based lifecycle.
                    incident_cutoff = time.time() - (INCIDENT_RETENTION_DAYS * 86400)
                    removed_incidents = 0
                    for incident_redis_key in redis_client.scan_iter(match="incident:*"):
                        if incident_redis_key.startswith("incident:events:") or redis_client.type(incident_redis_key) != "string":
                            continue
                        raw = redis_client.get(incident_redis_key)
                        try:
                            state = json.loads(raw or "{}")
                        except json.JSONDecodeError:
                            continue
                        if state.get("status") == "OPEN":
                            continue
                        closed_at = float(state.get("resolved_at") or state.get("last_updated") or state.get("first_seen") or 0)
                        if closed_at and closed_at <= incident_cutoff:
                            incident_id = incident_redis_key.split(":", 1)[1]
                            domain = state.get("correlation_domain", "")
                            correlation_key = state.get("correlation_key", "")
                            pipe = redis_client.pipeline(transaction=False)
                            pipe.delete(incident_redis_key, f"incident:events:{incident_id}")
                            if domain:
                                pipe.srem(f"open_incidents:{domain}", incident_id)
                            if domain and correlation_key:
                                registry_key = f"incident_identity:{domain}:{correlation_key}"
                                if redis_client.get(registry_key) == incident_id:
                                    pipe.delete(registry_key)
                            pipe.execute()
                            removed_incidents += 1
                    if removed_incidents:
                        logger.info("Cleaned up %s expired closed incidents", removed_incidents)

                    # 4. Bound DLQ storage even during prolonged delivery failures.
                    redis_client.ltrim(REDIS_DLQ, -DLQ_MAX_ITEMS, -1)
                    if redis_client.exists(REDIS_DLQ) and redis_client.ttl(REDIS_DLQ) < 0:
                        redis_client.expire(REDIS_DLQ, DLQ_RETENTION_DAYS * 86400)

                    cleanup_idle_stream_consumers()

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        # Run cleanup every hour
        time.sleep(3600)


def increment_metric(metric: str, amount: int = 1):
    """Increment a metric counter."""
    global redis_client
    try:
        if redis_client:
            day = datetime.utcnow().strftime("%Y-%m-%d")
            pipe = redis_client.pipeline(transaction=False)
            pipe.hincrby("metrics:processor", metric, amount)
            pipe.hincrby(f"metrics:processor:daily:{day}", metric, amount)
            pipe.expire(f"metrics:processor:daily:{day}", 86400 * 8)
            pipe.execute()
    except Exception:
        pass


def should_suppress_incident_notification(incident_key: str, action: str) -> tuple:
    """Rate-limit repeated updates while retaining every alert and timeline event."""
    if not incident_key or action not in {"MERGE", "UPDATE"}:
        return False, 0
    now = time.time()
    window_key = f"storm:window:{incident_key}"
    cooldown_key = f"storm:cooldown:{incident_key}"
    pipe = redis_client.pipeline(transaction=True)
    pipe.zadd(window_key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
    pipe.zremrangebyscore(window_key, 0, now - ALERT_STORM_WINDOW_SECONDS)
    pipe.zcard(window_key)
    pipe.expire(window_key, ALERT_STORM_WINDOW_SECONDS * 2)
    count = int(pipe.execute()[2])
    if count <= ALERT_STORM_THRESHOLD:
        return False, count
    if redis_client.set(cooldown_key, str(now), nx=True, ex=ALERT_STORM_COOLDOWN_SECONDS):
        redis_client.hincrby("metrics:processor", "storm_groups_started", 1)
        return False, count
    redis_client.hincrby("metrics:processor", "storm_suppressed", 1)
    return True, count


def get_runtime_summary_settings() -> dict:
    raw = redis_client.hgetall("settings:general") or {}
    def number(name, default, minimum=1):
        try:
            return max(minimum, int(raw.get(name, default)))
        except (TypeError, ValueError):
            return default
    return {
        "global_max": number("global_storm_max_notifications", GLOBAL_STORM_MAX_NOTIFICATIONS),
        "window": number("global_storm_window_seconds", GLOBAL_STORM_WINDOW_SECONDS),
        "summary_interval": number("storm_summary_interval_seconds", STORM_SUMMARY_INTERVAL_SECONDS, 30),
        "sla_minutes": number("incident_sla_minutes", INCIDENT_SLA_MINUTES),
    }


def should_suppress_global_storm(alert_id: str, incident_key: str, action: str, severity: str, data: dict, analysis: dict) -> tuple:
    """Apply a global disaster cap while exempting critical/new, recovery and AlertFlow health."""
    settings = get_runtime_summary_settings()
    now = time.time()
    window_key = "storm:global:window"
    pipe = redis_client.pipeline(transaction=True)
    pipe.zadd(window_key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
    pipe.zremrangebyscore(window_key, 0, now - settings["window"])
    pipe.zcard(window_key)
    pipe.expire(window_key, settings["window"] * 2)
    count = int(pipe.execute()[2])
    exempt = action == "RESOLVE" or data.get("self_monitor_event") or (severity.lower() == "critical" and action == "NEW")
    if count <= settings["global_max"] or exempt:
        return False, count

    active = redis_client.hgetall("storm:global:active") or {}
    mapping = {
        "started_at": active.get("started_at", str(now)), "last_event_at": str(now),
        "window_count": str(count), "suppressed": str(int(active.get("suppressed", 0) or 0) + 1),
    }
    redis_client.hset("storm:global:active", mapping=mapping)
    redis_client.hincrby("storm:global:severity", severity or "Unknown", 1)
    resource_values = analysis.get("target_resources", []) or [analysis.get("target_resource", "")]
    resource_values = [str(item) for item in resource_values if item]
    existing = redis_client.hget("storm:global:incidents", incident_key) if incident_key else None
    item = json.loads(existing) if existing else {"count": 0}
    item.update({
        "incident_key": incident_key, "subject": data.get("subject", "")[:120],
        "system": analysis.get("system_name", "Unknown"), "severity": severity or "Unknown",
        "resources": resource_values[:10], "last_seen": now, "count": int(item.get("count", 0)) + 1,
    })
    if incident_key:
        redis_client.hset("storm:global:incidents", incident_key, json.dumps(item))
    redis_client.hset(f"alert:{alert_id}", mapping={"notification_suppressed": "global_storm", "storm_window_count": str(count)})
    if incident_key:
        redis_client.xadd(f"incident:events:{incident_key}", {
            "alert_id": alert_id, "action": "SUPPRESSED", "status": "global_storm",
            "detail": f"Global cap exceeded: {count}/{settings['window']}s",
            "occurred_at": datetime.utcnow().isoformat(),
        }, maxlen=1000, approximate=True)
    redis_client.hincrby("metrics:processor", "storm_suppressed", 1)
    return True, count


def _directory_size(path: str) -> int:
    total = 0
    try:
        for root, _, files in os.walk(path):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename))
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _publish_self_monitor_transition(component: str, state: str, details: str):
    """Publish only state transitions, avoiding self-generated alert storms."""
    previous = redis_client.hget("self_monitor:states", component)
    redis_client.hset("self_monitor:states", component, state)
    if previous == state or (previous is None and state == "healthy"):
        return

    resolved = state == "healthy" and previous not in {None, "healthy"}
    event_state = "RESOLVED" if resolved else "FIRING"
    trace_id = str(uuid.uuid4())[:8]
    payload = {
        "from": "alertflow-self-monitor@localhost",
        "to": "operations@localhost",
        "rcpt_tos": ["operations@localhost"],
        "subject": f"[{event_state}:1] AlertFlow self-monitor: {component} {state}",
        "text": (
            f"AlertFlow self-monitor component: {component}\n"
            f"Previous state: {previous or 'unknown'}\nCurrent state: {state}\n{details}"
        ),
        "trace_id": trace_id,
        "self_monitor_event": True,
    }
    redis_client.xadd(
        REDIS_STREAM,
        {"payload": json.dumps(payload), "trace_id": trace_id},
        maxlen=100000,
        approximate=True,
    )
    add_log("WARNING" if not resolved else "INFO", f"Self-monitor transition: {component} {previous} → {state}", {
        "component": component, "previous": previous, "state": state, "trace_id": trace_id,
    })


def _run_observability_canary() -> bool:
    marker = f"ALERTFLOW_CANARY_{uuid.uuid4().hex[:12]}"
    logger.info("%s", marker)
    redis_client.hset("metrics:self_monitor", mapping={
        "canary_marker": marker,
        "canary_last_run_at": str(time.time()),
        "canary_status": "checking",
    })
    time.sleep(10)
    try:
        response = requests.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={
                "query": f'{{container="alertflow-processor"}} |= "{marker}"',
                "start": str(time.time_ns() - 120 * 1_000_000_000),
                "end": str(time.time_ns()),
                "limit": "1",
            },
            timeout=5,
        )
        response.raise_for_status()
        ok = bool(response.json().get("data", {}).get("result"))
    except (requests.RequestException, ValueError):
        ok = False
    redis_client.hset("metrics:self_monitor", mapping={
        "canary_status": "healthy" if ok else "critical",
        "canary_last_result_at": str(time.time()),
    })
    _publish_self_monitor_transition(
        "log_pipeline_canary", "healthy" if ok else "critical",
        f"Docker → Alloy → Loki canary marker found: {ok}",
    )
    return ok


def get_ai_chain_monitor_state() -> tuple:
    """Derive primary/fallback health from real provider attempts."""
    provider_ids = list(redis_client.smembers("ai_providers:index") or set())
    if not provider_ids:
        return "unknown", "No configured AI providers"
    pipe = redis_client.pipeline(transaction=False)
    for provider_id in provider_ids:
        pipe.hgetall(f"ai_provider:{provider_id}")
        pipe.hgetall(f"metrics:ai:provider:{provider_id}")
    values = pipe.execute()
    states = []
    for index, provider_id in enumerate(provider_ids):
        provider, metrics = values[index * 2], values[index * 2 + 1]
        if not provider:
            continue
        last_success = float(metrics.get("last_success_at", 0) or 0)
        last_failure = float(metrics.get("last_failure_at", 0) or 0)
        state = "unknown" if not (last_success or last_failure) else "healthy" if last_success >= last_failure else "critical"
        role = "primary" if str(provider.get("is_default", "false")).lower() == "true" else "fallback" if str(provider.get("is_fallback", "false")).lower() == "true" else "standby"
        states.append((role, state, provider.get("name", provider_id), metrics.get("last_error", "")))
    primary = next((item for item in states if item[0] == "primary"), None)
    fallback = next((item for item in states if item[0] == "fallback"), None)
    if primary and primary[1] == "healthy":
        return "healthy", f"Primary provider {primary[2]} is healthy"
    if fallback and fallback[1] == "healthy":
        return "warning", f"Primary unavailable; fallback {fallback[2]} is active"
    if any(item[1] == "healthy" for item in states):
        return "warning", "Primary unavailable; a standby provider remains healthy"
    if any(item[1] == "critical" for item in states):
        errors = "; ".join(f"{item[2]}: {item[3][:120]}" for item in states if item[1] == "critical")
        return "critical", f"No healthy AI provider. {errors}"
    return "unknown", "AI providers have not been exercised yet"


def self_monitor_loop():
    """Monitor disk, Loki/Alloy readiness, local Loki growth, and end-to-end log flow."""
    time.sleep(20)
    last_canary = 0.0
    last_fallback_canary = 0.0
    last_size = None
    last_size_at = None
    while True:
        try:
            now = time.time()
            usage = shutil.disk_usage(DISK_MONITOR_PATH)
            disk_percent = round(usage.used / usage.total * 100, 2)
            disk_state = "critical" if disk_percent >= DISK_CRITICAL_PERCENT else "warning" if disk_percent >= DISK_WARNING_PERCENT else "healthy"

            def ready(url: str) -> bool:
                try:
                    return requests.get(url, timeout=3).status_code == 200
                except requests.RequestException:
                    return False

            loki_ok = ready(f"{LOKI_URL}/ready")
            alloy_ok = ready(f"{ALLOY_URL}/-/ready")
            loki_size = _directory_size(LOKI_DATA_PATH)
            growth_mib_per_hour = 0.0
            if last_size is not None and last_size_at and now > last_size_at:
                growth_mib_per_hour = max(0.0, (loki_size - last_size) / 1024 / 1024 * 3600 / (now - last_size_at))
            growth_state = "warning" if growth_mib_per_hour >= LOKI_GROWTH_WARNING_MB_PER_HOUR else "healthy"

            redis_client.hset("metrics:self_monitor", mapping={
                "updated_at": str(now),
                "disk_used_percent": str(disk_percent),
                "disk_total_bytes": str(usage.total),
                "disk_free_bytes": str(usage.free),
                "disk_state": disk_state,
                "disk_monitor_path": DISK_MONITOR_PATH,
                "loki_status": "healthy" if loki_ok else "critical",
                "alloy_status": "healthy" if alloy_ok else "critical",
                "loki_volume_bytes": str(loki_size),
                "loki_growth_mib_per_hour": str(round(growth_mib_per_hour, 3)),
                "loki_growth_state": growth_state,
            })
            healthy_components = sum((disk_state == "healthy", loki_ok, alloy_ok, growth_state == "healthy"))
            redis_client.hincrby("metrics:slo", "component_checks", 4)
            redis_client.hincrby("metrics:slo", "healthy_component_checks", healthy_components)
            _publish_self_monitor_transition("disk", disk_state, f"Disk usage: {disk_percent}% (warning={DISK_WARNING_PERCENT}%, critical={DISK_CRITICAL_PERCENT}%)")
            _publish_self_monitor_transition("loki", "healthy" if loki_ok else "critical", f"Readiness endpoint: {LOKI_URL}/ready")
            _publish_self_monitor_transition("alloy", "healthy" if alloy_ok else "critical", f"Readiness endpoint: {ALLOY_URL}/-/ready")
            _publish_self_monitor_transition("loki_growth", growth_state, f"Loki growth: {growth_mib_per_hour:.2f} MiB/hour; threshold: {LOKI_GROWTH_WARNING_MB_PER_HOUR} MiB/hour")
            ai_state, ai_detail = get_ai_chain_monitor_state()
            redis_client.hset("metrics:self_monitor", mapping={"ai_chain_status": ai_state, "ai_chain_detail": ai_detail})
            if ai_state != "unknown":
                _publish_self_monitor_transition("ai_chain", ai_state, ai_detail)

            last_size, last_size_at = loki_size, now
            if now - last_canary >= 300:
                last_canary = now
                _run_observability_canary()
            if now - last_fallback_canary >= int(os.getenv("FALLBACK_CANARY_INTERVAL_SECONDS", "21600")):
                last_fallback_canary = now
                probe = probe_fallback_provider()
                redis_client.hset("metrics:self_monitor", mapping={
                    "fallback_canary_status": probe.get("status", "unknown"),
                    "fallback_canary_detail": probe.get("detail", ""),
                    "fallback_canary_provider": probe.get("provider", ""),
                    "fallback_canary_latency_seconds": str(probe.get("latency", 0)),
                    "fallback_canary_last_result_at": str(now),
                })
                logger.info("Fallback provider canary: %s (%s)", probe.get("status"), probe.get("provider"))
        except Exception as exc:
            logger.error("Self-monitor loop failed: %s", exc)
            add_log("ERROR", "Self-monitor loop failed", {"error": str(exc)[:300]})
        time.sleep(60)


def read_stream_message(client, reclaim_abandoned: bool = False):
    """Read one message, optionally reclaiming a delivery abandoned for 60s."""
    if reclaim_abandoned:
        claimed = client.xautoclaim(
            REDIS_STREAM, REDIS_STREAM_GROUP, REDIS_CONSUMER,
            min_idle_time=60000, start_id="0-0", count=1,
        )
        claimed_messages = claimed[1] if len(claimed) > 1 else []
        if claimed_messages:
            stream_id, fields = claimed_messages[0]
            return stream_id, fields.get("payload", "")

    messages = client.xreadgroup(
        REDIS_STREAM_GROUP, REDIS_CONSUMER,
        {REDIS_STREAM: ">"}, count=1, block=1000,
    )
    if messages and messages[0][1]:
        stream_id, fields = messages[0][1][0]
        return stream_id, fields.get("payload", "")
    return None, None


def cleanup_idle_stream_consumers(min_idle_ms: int = 3600000) -> int:
    """Remove dead consumer metadata only when it owns no pending messages."""
    removed = 0
    try:
        for consumer in redis_client.xinfo_consumers(REDIS_STREAM, REDIS_STREAM_GROUP):
            name = consumer.get("name", "")
            if name != REDIS_CONSUMER and int(consumer.get("pending", 0)) == 0 and int(consumer.get("idle", 0)) >= min_idle_ms:
                redis_client.xgroup_delconsumer(REDIS_STREAM, REDIS_STREAM_GROUP, name)
                removed += 1
        if removed:
            logger.info("Removed %s idle Redis stream consumers", removed)
    except redis.ResponseError as exc:
        logger.warning("Could not clean stream consumers: %s", exc)
    return removed


def push_to_dlq(payload: str):
    """Append a failed payload while enforcing a bounded, expiring DLQ."""
    pipe = redis_client.pipeline(transaction=False)
    pipe.rpush(REDIS_DLQ, payload)
    pipe.ltrim(REDIS_DLQ, -DLQ_MAX_ITEMS, -1)
    pipe.expire(REDIS_DLQ, DLQ_RETENTION_DAYS * 86400)
    pipe.execute()


# ============================================
# Retry Mechanism for Failed Dispatches
# ============================================
# Backoff schedule: 30s → 5min → 30min → 2h
# After 4 retries, message goes to DLQ permanently.
# Only dispatch is retried — AI analysis is NOT re-run.
# ============================================

RETRY_MAX = 4
RETRY_BACKOFF_SECONDS = [30, 300, 1800, 7200]  # 30s, 5min, 30min, 2h
RETRY_QUEUE = "retry_queue"  # Redis sorted set, score = next_retry_timestamp


def _latest_incident_delivery(incident_key: str) -> dict:
    """Return the newest delivery event for each channel in an incident."""
    latest = {}
    if not incident_key:
        return latest
    try:
        for _, fields in redis_client.xrevrange(f"incident:events:{incident_key}", count=200):
            channel_id = fields.get("channel_id", "")
            if fields.get("action") == "DELIVERY" and channel_id and channel_id not in latest:
                latest[channel_id] = fields
    except Exception as exc:
        logger.warning("Could not inspect incident delivery history: %s", exc)
    return latest


def retry_is_superseded(retry_data: dict) -> bool:
    """Prevent an old retry from overwriting a newer successfully delivered revision."""
    if retry_data.get("resolution_archive"):
        return False
    incident_key = retry_data.get("incident_key", "")
    if not incident_key:
        return False
    raw = redis_client.get(f"incident:{incident_key}")
    if not raw:
        return True
    state = json.loads(raw)
    queued_revision = int(retry_data.get("incident_revision", 0) or 0)
    current_revision = int(state.get("revision", 1) or 1)
    if queued_revision and current_revision <= queued_revision:
        return False
    required = list(retry_data.get("destination_ids", []) or retry_data.get("notification_channel_ids", []) or [])
    latest = _latest_incident_delivery(incident_key)
    if required:
        return all(latest.get(channel_id, {}).get("status") == "delivered" for channel_id in required)
    scheduled_at = str(retry_data.get("scheduled_at", ""))
    delivered = [event for event in latest.values() if event.get("status") == "delivered"]
    return bool(delivered and (queued_revision or any(event.get("occurred_at", "") > scheduled_at for event in delivered)))


def cleanup_superseded_dlq() -> int:
    """Remove historical DLQ entries only after a newer delivery proves recovery."""
    removed = 0
    for raw in list(redis_client.lrange(REDIS_DLQ, 0, -1)):
        try:
            data = json.loads(raw)
            if not retry_is_superseded(data):
                continue
            removed += redis_client.lrem(REDIS_DLQ, 1, raw)
            if data.get("dlq_dedupe_key"):
                redis_client.delete(data["dlq_dedupe_key"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    if removed:
        increment_metric("dlq_superseded_cleaned", removed)
        logger.info("Removed %s superseded DLQ item(s) after newer successful delivery", removed)
    return removed


def schedule_retry(retry_data: dict) -> bool:
    """Schedule a failed dispatch for retry.

    retry_data must contain:
        - telegram_msg, matrix_msg: pre-formatted text
        - channel, notification_channel_ids, channel_overrides
        - chat_id, thread_id, room_id (legacy)
        - sender, subject, retry_count
    """
    global redis_client
    try:
        retry_count = retry_data.get("retry_count", 0)

        if retry_count >= RETRY_MAX:
            # Max retries exhausted → DLQ
            logger.error(f"💀 Max retries ({RETRY_MAX}) exhausted for: {retry_data.get('subject', '?')[:50]}")
            add_log("ERROR", f"Max retries exhausted, moved to DLQ", {
                "subject": retry_data.get("subject", "")[:50],
                "retry_count": retry_count
            })
            dedupe_source = "|".join([
                retry_data.get("incident_key", "") or retry_data.get("subject", ""),
                retry_data.get("action", ""),
                ",".join(sorted(retry_data.get("destination_ids", []) or retry_data.get("notification_channel_ids", []) or [retry_data.get("channel", "")])),
            ])
            dedupe_hash = hashlib.sha256(dedupe_source.encode()).hexdigest()[:24]
            dedupe_key = f"dlq:dedupe:{dedupe_hash}"
            retry_data["dlq_dedupe_key"] = dedupe_key
            retry_data["failed_at"] = datetime.utcnow().isoformat()
            retry_data["failure_reason"] = retry_data.get("failure_reason") or "maximum_retries_exhausted"
            if redis_client.set(dedupe_key, retry_data.get("alert_id", ""), nx=True, ex=DLQ_RETENTION_DAYS * 86400):
                push_to_dlq(json.dumps(retry_data))
                increment_metric("dlq")
            else:
                redis_client.hincrby("metrics:processor", "dlq_duplicates_suppressed", 1)
                logger.warning("Duplicate DLQ group suppressed for incident %s", retry_data.get("incident_key", ""))
            for channel_id in retry_data.get("destination_ids", []) or retry_data.get("notification_channel_ids", []):
                record_delivery(
                    retry_data.get("alert_id", ""), channel_id, "exhausted",
                    f"maximum retries ({RETRY_MAX}) exhausted", retry_count,
                )
            return False

        delay = RETRY_BACKOFF_SECONDS[retry_count]
        next_retry_at = time.time() + delay
        retry_data["retry_count"] = retry_count + 1
        retry_data["next_retry_at"] = next_retry_at
        retry_data["scheduled_at"] = datetime.utcnow().isoformat()

        redis_client.zadd(RETRY_QUEUE, {json.dumps(retry_data): next_retry_at})
        for channel_id in retry_data.get("destination_ids", []) or retry_data.get("notification_channel_ids", []):
            record_delivery(
                retry_data.get("alert_id", ""), channel_id, "retrying",
                f"next retry in {delay}s", retry_data["retry_count"],
            )

        delay_label = format_delay(delay)
        logger.warning(f"🔄 Retry {retry_data['retry_count']}/{RETRY_MAX} scheduled in {delay_label} for: {retry_data.get('subject', '?')[:50]}")
        add_log("WARNING", f"Retry {retry_data['retry_count']}/{RETRY_MAX} scheduled in {delay_label}", {
            "subject": retry_data.get("subject", "")[:50],
            "next_retry_at": datetime.utcfromtimestamp(next_retry_at).isoformat()
        })
        increment_metric("retries_scheduled")
        return True

    except Exception as e:
        logger.error(f"Failed to schedule retry: {e}")
        return False


def format_delay(seconds: int) -> str:
    """Human-readable delay label."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}min"
    else:
        return f"{seconds // 3600}h"


def retry_dispatch(retry_data: dict) -> bool:
    """Re-dispatch a previously failed alert (no AI re-analysis)."""
    try:
        if retry_is_superseded(retry_data):
            incident_key = retry_data.get("incident_key", "")
            logger.info("Retry superseded by a newer delivered incident revision: %s", incident_key)
            increment_metric("retries_superseded")
            if incident_key:
                redis_client.xadd(f"incident:events:{incident_key}", {
                    "alert_id": retry_data.get("alert_id", ""), "action": "RETRY",
                    "status": "superseded", "occurred_at": datetime.utcnow().isoformat(),
                }, maxlen=1000, approximate=True)
            return True
        telegram_msg = retry_data.get("telegram_msg", "")
        matrix_msg = retry_data.get("matrix_msg", "")
        channel = retry_data.get("channel", "")
        sender = retry_data.get("sender", "")
        subject = retry_data.get("subject", "")
        retry_num = retry_data.get("retry_count", 1)

        logger.info(f"🔄 Retry {retry_num}/{RETRY_MAX} dispatching: {subject[:50]}")

        success = False
        destination = "None"

        action = retry_data.get("action", "NEW")
        incident_key = retry_data.get("incident_key", "")
        known_message_ids = retry_data.get("known_message_ids", {})

        if channel == "destinations":
            destination_ids = retry_data.get("destination_ids", [])
            success, destination, new_msg_ids, failed_destination_ids = dispatch_destinations(
                telegram_msg, matrix_msg, destination_ids, action=action, incident_key=incident_key,
                known_message_ids=known_message_ids, delivery_alert_id=retry_data.get("alert_id", ""),
                delivery_attempt=retry_num,
            )
            retry_data["destination_ids"] = failed_destination_ids
            if new_msg_ids and incident_key:
                if retry_data.get("resolution_archive"):
                    _save_resolution_archive(incident_key, new_msg_ids)
                else:
                    IncidentTracker(redis_client).save_message_ids(incident_key, new_msg_ids, telegram_text=telegram_msg)
        elif channel == "dynamic":
            nc_ids = retry_data.get("notification_channel_ids", [])
            overrides = retry_data.get("channel_overrides", {})
            if nc_ids:
                success, destination, new_msg_ids, failed_channel_ids = dispatch_dynamic_alert(
                    telegram_msg, matrix_msg, nc_ids, overrides,
                    action=action, incident_key=incident_key, known_message_ids=known_message_ids,
                    delivery_alert_id=retry_data.get("alert_id", ""), delivery_attempt=retry_num,
                )
                retry_data["notification_channel_ids"] = failed_channel_ids
                if retry_data.get("resolution_archive") and new_msg_ids:
                    _save_resolution_archive(incident_key, new_msg_ids)
        else:
            # Legacy path
            from utils import send_telegram_auto, send_matrix_message, edit_telegram_message, edit_matrix_message
            chat_id = retry_data.get("chat_id", "")
            thread_id = retry_data.get("thread_id", "0")
            room_id = retry_data.get("room_id", "")
            legacy_statuses = []
            new_msg_ids = {}
            required = 0
            succeeded = 0

            if channel in ["telegram", "both"]:
                channel_key = f"telegram_{chat_id}"
                existing_msg_id = known_message_ids.get(channel_key)

                telegram_config_id, telegram_config = find_channel_for_legacy_target("telegram", chat_id)
                telegram_secret = parse_channel_config_data(telegram_config.get("config", "{}"))
                telegram_token = telegram_secret.get("bot_token")
                telegram_proxy = telegram_secret.get("proxy_base_url", "") or None
                if action in ["RESOLVE", "MERGE", "UPDATE"] and not existing_msg_id:
                    legacy_statuses.append("TelegramEdit:SKIPPED_NO_MESSAGE")
                elif action in ["RESOLVE", "MERGE", "UPDATE"]:
                    required += 1
                    if edit_telegram_message(chat_id, existing_msg_id, telegram_msg, bot_token=telegram_token, proxy_base_url=telegram_proxy):
                        legacy_statuses.append("TelegramEdit:OK")
                        succeeded += 1
                    else:
                        legacy_statuses.append("TelegramEdit:FAILED")
                else:
                    required += 1
                    send_ok, msg_id = send_telegram_auto(chat_id, int(thread_id), telegram_msg, bot_token=telegram_token, proxy_base_url=telegram_proxy)
                    if send_ok:
                        legacy_statuses.append("Telegram:OK")
                        succeeded += 1
                        if msg_id:
                            new_msg_ids[channel_key] = msg_id
                    else:
                        legacy_statuses.append("Telegram:FAILED")

            if channel in ["matrix", "both"]:
                channel_key = f"matrix_{room_id}"
                existing_msg_id = known_message_ids.get(channel_key)

                matrix_config_id, matrix_config = find_channel_for_legacy_target("matrix", room_id)
                matrix_secret = parse_channel_config_data(matrix_config.get("config", "{}"))
                matrix_hs = matrix_secret.get("homeserver_url")
                matrix_token = matrix_secret.get("access_token")
                if action in ["RESOLVE", "MERGE", "UPDATE"] and not existing_msg_id:
                    legacy_statuses.append("MatrixEdit:SKIPPED_NO_MESSAGE")
                elif action in ["RESOLVE", "MERGE", "UPDATE"]:
                    required += 1
                    if edit_matrix_message(matrix_msg, existing_msg_id, room_id, homeserver_url=matrix_hs, access_token=matrix_token):
                        legacy_statuses.append("MatrixEdit:OK")
                        succeeded += 1
                    else:
                        legacy_statuses.append("MatrixEdit:FAILED")
                else:
                    required += 1
                    send_ok, msg_id = send_matrix_message(matrix_msg, room_id, homeserver_url=matrix_hs, access_token=matrix_token)
                    if send_ok:
                        legacy_statuses.append("Matrix:OK")
                        succeeded += 1
                        if msg_id:
                            new_msg_ids[channel_key] = msg_id
                    else:
                        legacy_statuses.append("Matrix:FAILED")

            destination = ", ".join(legacy_statuses) if legacy_statuses else "Legacy:NONE"
            success = required > 0 and succeeded == required
            if new_msg_ids and incident_key:
                IncidentTracker(redis_client).save_message_ids(incident_key, new_msg_ids, telegram_text=telegram_msg)
            alert_id = retry_data.get("alert_id", "")
            if channel in ["telegram", "both"] and "TelegramEdit:SKIPPED_NO_MESSAGE" not in legacy_statuses:
                record_delivery(alert_id, telegram_config_id or f"legacy:telegram:{chat_id}", "delivered" if "Telegram:OK" in legacy_statuses or "TelegramEdit:OK" in legacy_statuses else "failed", destination, retry_num)
            if channel in ["matrix", "both"] and "MatrixEdit:SKIPPED_NO_MESSAGE" not in legacy_statuses:
                record_delivery(alert_id, matrix_config_id or f"legacy:matrix:{room_id}", "delivered" if "Matrix:OK" in legacy_statuses or "MatrixEdit:OK" in legacy_statuses else "failed", destination, retry_num)

        # Log result
        add_relay_log(sender, subject, channel, f"RETRY-{retry_num}:{destination}", success)

        if success:
            if retry_data.get("resolution_archive") and retry_data.get("cleanup_after_archive"):
                cleanup_active_incident_messages(incident_key, retry_data.get("active_route_snapshot", {}))
            logger.info(f"✅ Retry {retry_num} succeeded: {destination}")
            add_log("INFO", f"Retry {retry_num}/{RETRY_MAX} succeeded: {destination}", {
                "subject": subject[:50]
            })
            increment_metric("retries_succeeded")
            return True
        else:
            logger.warning(f"❌ Retry {retry_num} failed: {destination}")
            add_log("WARNING", f"Retry {retry_num}/{RETRY_MAX} failed: {destination}", {
                "subject": subject[:50]
            })
            return False

    except Exception as e:
        logger.error(f"Retry dispatch error: {e}")
        return False


def retry_worker_loop():
    """Background thread: polls retry queue and re-dispatches due items."""
    global redis_client
    logger.info("🔄 Retry worker started (checking every 10s)")

    last_dlq_cleanup = 0.0
    while True:
        try:
            now = time.time()
            if now - last_dlq_cleanup >= 60:
                cleanup_superseded_dlq()
                last_dlq_cleanup = now
            # Get items whose scheduled time has passed
            due_items = redis_client.zrangebyscore(RETRY_QUEUE, 0, now, start=0, num=5)

            for item_json in due_items:
                # Remove from queue first (atomic pop)
                removed = redis_client.zrem(RETRY_QUEUE, item_json)
                if not removed:
                    continue  # Another worker already took it

                try:
                    retry_data = json.loads(item_json)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in retry queue, discarding")
                    continue

                success = retry_dispatch(retry_data)

                if not success:
                    # Schedule next retry or move to DLQ
                    schedule_retry(retry_data)

        except redis.ConnectionError:
            logger.error("Retry worker: Redis connection lost")
        except Exception as e:
            logger.error(f"Retry worker error: {e}")

        time.sleep(10)


def is_muted(sender: str) -> bool:
    """Check if sender is muted."""
    global redis_client
    try:
        sender_lower = sender.lower()
        if redis_client.sismember("mute:from", sender_lower):
            return True
        if "@" in sender_lower:
            domain = sender_lower.split("@")[1]
            if redis_client.sismember("mute:domain", domain):
                return True
        return False
    except Exception:
        return False



def get_routing_rules():
    """Get all routing rules from Redis (pipelined)."""
    global redis_client
    try:
        rule_ids = list(redis_client.smembers("routing_rules:index") or set())
        if not rule_ids:
            return []
        pipe = redis_client.pipeline(transaction=False)
        for rid in rule_ids:
            pipe.hgetall(f"routing_rule:{rid}")
        results = pipe.execute()
        return [r for r in results if r]
    except Exception:
        return []


def get_default_notification_channel_ids() -> list:
    """Return configured default channels without exposing their secrets."""
    try:
        channel_ids = list(redis_client.smembers("notification_channels:index") or set())
        if not channel_ids:
            return []
        pipe = redis_client.pipeline(transaction=False)
        for channel_id in channel_ids:
            pipe.hgetall(f"notification_channel:{channel_id}")
        channels = pipe.execute()
        return [
            channel_id for channel_id, channel in zip(channel_ids, channels)
            if channel and str(channel.get("is_default", "false")).lower() == "true"
        ]
    except Exception:
        return []


def save_alert(alert_data: dict, ai_result: dict, channel: str, incident_key: str = "", action: str = "NEW",
               analysis_provider: str = "", analysis_duration: float = 0) -> str:
    """Save alert to Redis for dashboard."""
    global redis_client
    try:
        alert_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()

        analysis = ai_result.get("analysis", {}) if ai_result else {}

        alert = {
            "id": alert_id,
            "from_email": alert_data.get("from", ""),
            "to_email": alert_data.get("to", alert_data.get("rcpt_tos", [""])[0] if alert_data.get("rcpt_tos") else ""),
            "subject": alert_data.get("subject", ""),
            "trace_id": alert_data.get("trace_id", ""),
            "body": alert_data.get("text", "") or alert_data.get("body", ""),
            "html": alert_data.get("html", ""),
            "channel": channel,
            "status": "new",
            "severity": str(analysis.get("severity", "")),
            "category": str(analysis.get("category", "")),
            "confidence": str(analysis.get("confidence", "")),
            "model_confidence": str(analysis.get("model_confidence", analysis.get("confidence", ""))),
            "evidence_confidence": str(analysis.get("evidence_confidence", analysis.get("confidence", ""))),
            "evidence_status": str(analysis.get("evidence_status", "unknown")),
            "validation_warnings": json.dumps(analysis.get("validation_warnings", [])),
            "taxonomy_overrides": json.dumps(analysis.get("taxonomy_overrides", [])),
            "event_state": str(analysis.get("event_state", "")),
            "incident_severity": str(analysis.get("incident_severity", analysis.get("severity", ""))),
            "system_name": str(analysis.get("system_name", "")),
            "main_message": str(analysis.get("main_message", "")),
            "details": str(analysis.get("details", "")),
            "recommended_actions": json.dumps(analysis.get("recommended_actions", [])),
            "target_resource": str(analysis.get("target_resource", "")),
            "target_resources": json.dumps(analysis.get("target_resources", []) or []),
            "correlation_key": str(analysis.get("correlation_key", "")),
            "correlation_identity": str(analysis.get("correlation_identity", "")),
            "model_action": str(analysis.get("model_action", analysis.get("action", ""))),
            "ai_raw": json.dumps(ai_result) if ai_result else "",
            "analysis_status": "complete" if ai_result else "failed",
            "analysis_provider": analysis_provider or "",
            "analysis_duration": str(analysis_duration or 0),
            "ai_duration": str(analysis_duration or 0),
            "incident_key": incident_key,
            "correlation_action": action,
            "created_at": now,
            "updated_at": now,
        }

        # If it's a merge or redundant resolve, mark status accordingly
        if action == "MERGE":
            alert["status"] = "duplicate"
        elif action == "IGNORE":
            alert["status"] = "redundant"
        elif action == "RESOLVE":
            alert["status"] = "resolved"
            alert["resolved_at"] = now
            alert["system_resolved"] = "true"
            # Also mark all related open alerts as resolved
            _resolve_related_alerts(incident_key)
        else:
            # For NEW or UPDATE actions, check if the AI determined it is informational or already resolved.
            ai_status = str(analysis.get("status", "")).upper()
            ai_severity = str(analysis.get("severity", "")).upper()
            if ai_status in ["RESOLVED", "INFO"] or ai_severity == "INFO":
                alert["status"] = "resolved"
                alert["resolved_at"] = now
                alert["system_resolved"] = "true"

        if not ai_result:
            alert["analysis_status"] = "failed"

        redis_client.hset(f"alert:{alert_id}", mapping=alert)
        score = time.time()
        redis_client.zadd("alerts:index", {alert_id: score})
        redis_client.zadd(f"alerts:status:{alert['status'].lower()}", {alert_id: score})
        redis_client.zadd(f"alerts:severity:{(alert['severity'] or 'unclassified').lower()}", {alert_id: score})
        redis_client.zadd(f"alerts:category:{(alert['category'] or 'unclassified').lower()}", {alert_id: score})
        if incident_key:
            event_key = f"incident:events:{incident_key}"
            redis_client.xadd(event_key, {
                "alert_id": alert_id,
                "action": action,
                "status": alert["status"],
                "occurred_at": now,
            }, maxlen=1000, approximate=True)
            redis_client.expire(event_key, 86400 * 7)

        logger.info(f"Alert saved: {alert_id} [status={alert['status']}, action={action}]")
        return alert_id
    except Exception as e:
        logger.error(f"Failed to save alert: {e}")
        return ""


def _resolve_related_alerts(incident_key: str):
    """Mark all open alerts with the same incident_key as resolved."""
    global redis_client
    try:
        all_ids = redis_client.zrange("alerts:index", 0, -1)
        if not all_ids:
            return

        # Batch read incident_key + status for all alerts
        pipe = redis_client.pipeline(transaction=False)
        for aid in all_ids:
            aid_str = aid.decode("utf-8") if isinstance(aid, bytes) else aid
            pipe.hmget(f"alert:{aid_str}", "incident_key", "status")
        results = pipe.execute()

        # Find matching alerts to resolve
        now = datetime.utcnow().isoformat()
        resolve_pipe = redis_client.pipeline(transaction=False)
        count = 0
        for aid, fields in zip(all_ids, results):
            aid_str = aid.decode("utf-8") if isinstance(aid, bytes) else aid
            ik = fields[0].decode("utf-8") if isinstance(fields[0], bytes) else fields[0]
            st = fields[1].decode("utf-8") if isinstance(fields[1], bytes) else fields[1]

            if ik == incident_key and st in ("new", "acknowledged"):
                resolve_pipe.hset(f"alert:{aid_str}", mapping={
                    "status": "resolved",
                    "resolved_at": now,
                    "updated_at": now,
                    "system_resolved": "true"
                })
                score = redis_client.zscore("alerts:index", aid_str) or time.time()
                resolve_pipe.zrem(f"alerts:status:{st}", aid_str)
                resolve_pipe.zadd("alerts:status:resolved", {aid_str: score})
                count += 1

        if count:
            resolve_pipe.execute()
            logger.info(f"✅ Auto-resolved {count} related alerts for incident: {incident_key}")
            add_log("INFO", f"Auto-resolved {count} related alerts", {"incident_key": incident_key})
    except Exception as e:
        logger.error(f"Failed to resolve related alerts: {e}")

def get_channel_config(channel_id: str) -> dict:
    """Get channel configuration from Redis."""
    global redis_client
    try:
        return redis_client.hgetall(f"notification_channel:{channel_id}")
    except Exception:
        return {}


def get_destination(destination_id: str) -> dict:
    item = redis_client.hgetall(f"notification_destination:{destination_id}") or {}
    if not item or str(item.get("enabled", "false")).lower() != "true":
        return {}
    item["target"] = parse_channel_config_data(item.get("target", "{}"))
    return item


def destination_snapshot(destination_ids: list) -> list:
    return [item for item in (get_destination(x) for x in destination_ids or []) if item]

def parse_channel_config_data(raw_config) -> dict:
    """Safely parse channel config JSON."""
    if isinstance(raw_config, str):
        try:
            return json.loads(raw_config)
        except Exception:
            return {}
    elif isinstance(raw_config, dict):
        return raw_config
    return {}


def get_resolution_profile(profile_id: str) -> dict:
    if not profile_id:
        return {}
    profile = redis_client.hgetall(f"resolution_profile:{profile_id}") or {}
    if not profile or str(profile.get("enabled", "false")).lower() != "true":
        return {}
    try:
        profile["notification_channel_ids"] = json.loads(profile.get("notification_channel_ids", "[]"))
    except (TypeError, json.JSONDecodeError):
        profile["notification_channel_ids"] = []
    profile["channel_overrides"] = parse_channel_config_data(profile.get("channel_overrides", "{}"))
    return profile if profile.get("notification_channel_ids") else {}


def snapshot_incident_resolution(incident_key: str, routing: dict, active_route: dict,
                                 analysis: dict, data: dict) -> bool:
    """Freeze routing at incident creation so later rule edits cannot move an open incident."""
    profile = get_resolution_profile(routing.get("resolution_profile_id", ""))
    resolved_destinations = destination_snapshot(routing.get("resolved_destination_ids", []))
    destination_mode = routing.get("resolution_mode", "legacy")
    if not resolved_destinations and (not profile or routing.get("resolution_behavior", "legacy") == "legacy"):
        return False
    raw = redis_client.get(f"incident:{incident_key}")
    if not raw:
        return False
    state = json.loads(raw)
    state.update({
        "initial_main_message": analysis.get("main_message", ""),
        "initial_details": analysis.get("details", []),
        "initial_severity": analysis.get("severity", ""),
        "system_name": analysis.get("system_name", ""),
        "category": analysis.get("category", ""),
        "source_first_observed": extract_source_timestamp(data.get("text"), data.get("html"), analysis.get("details")),
        "active_route_snapshot": active_route,
        "resolution_destination_snapshot": {
            "destinations": resolved_destinations,
            "destination_ids": [x.get("id") for x in resolved_destinations],
            "mode": destination_mode if resolved_destinations else "legacy",
        },
        "resolution_profile_snapshot": {
            "id": profile.get("id", routing.get("resolution_profile_id", "")),
            "name": profile.get("name", ""),
            "notification_channel_ids": profile.get("notification_channel_ids", []),
            "channel_overrides": profile.get("channel_overrides", {}),
            "behavior": routing.get("resolution_behavior", "archive"),
            "delete_active_after_resolve": bool(routing.get("delete_active_after_resolve", False)),
        },
    })
    redis_client.set(f"incident:{incident_key}", json.dumps(state), ex=86400 * INCIDENT_RETENTION_DAYS)
    return True


def _incident_events(incident_key: str) -> list:
    return [fields for _, fields in redis_client.xrange(f"incident:events:{incident_key}", count=1000)]


def _save_resolution_archive(incident_key: str, message_ids: dict):
    raw = redis_client.get(f"incident:{incident_key}")
    if not raw:
        return
    state = json.loads(raw)
    archived = state.get("resolution_archive_channels", {})
    archived.update(message_ids or {})
    state["resolution_archive_channels"] = archived
    state["resolution_archived_at"] = datetime.utcnow().isoformat()
    redis_client.set(f"incident:{incident_key}", json.dumps(state), ex=86400 * INCIDENT_RETENTION_DAYS)


def cleanup_active_incident_messages(incident_key: str, active_snapshot: dict) -> bool:
    """Remove active cards, falling back to an explicit tombstone when deletion is unavailable."""
    raw = redis_client.get(f"incident:{incident_key}")
    if not raw:
        return False
    state = json.loads(raw)
    tombstone_tg = "🟢 *RESOLVED*\nArchived in the configured resolved destination\\."
    tombstone_mx = "🟢 RESOLVED\nArchived in the configured resolved destination."
    results = []
    configs = []
    for channel_id in active_snapshot.get("notification_channel_ids", []) or []:
        config = get_channel_config(channel_id)
        if config:
            configs.append((channel_id, config, parse_channel_config_data(config.get("config", "{}"))))
    overrides = active_snapshot.get("channel_overrides", {}) or {}
    for channel_key, message_id in (state.get("channels") or {}).items():
        if channel_key.startswith("destination:"):
            destination_id = channel_key.split(":", 1)[1]
            item = next((x for x in active_snapshot.get("destinations", []) if x.get("id") == destination_id), {})
            config = get_channel_config(item.get("channel_id", ""))
            secret = parse_channel_config_data(config.get("config", "{}"))
            target = item.get("target", {})
            if item.get("type") == "telegram":
                deleted = delete_telegram_message(target.get("chat_id"), message_id, secret.get("bot_token"), secret.get("proxy_base_url") or None)
                results.append(deleted or edit_telegram_message(target.get("chat_id"), message_id, tombstone_tg, secret.get("bot_token"), secret.get("proxy_base_url") or None))
            elif item.get("type") == "matrix":
                deleted = redact_matrix_message(message_id, target.get("room_id"), secret.get("homeserver_url"), secret.get("access_token"))
                results.append(deleted or edit_matrix_message(tombstone_mx, message_id, target.get("room_id"), secret.get("homeserver_url"), secret.get("access_token")))
            continue
        if channel_key.startswith("telegram_"):
            chat_id = channel_key[len("telegram_"):]
            secret = {}
            for config_id, config, candidate in configs:
                target = (overrides.get(config_id, {}) or {}).get("chat_id") or candidate.get("chat_id") or candidate.get("default_chat_id")
                if config.get("type") == "telegram" and str(target) == str(chat_id):
                    secret = candidate
                    break
            if not secret:
                _, config = find_channel_for_legacy_target("telegram", chat_id)
                secret = parse_channel_config_data(config.get("config", "{}"))
            deleted = delete_telegram_message(chat_id, message_id, secret.get("bot_token"), secret.get("proxy_base_url") or None)
            ok = deleted or edit_telegram_message(chat_id, message_id, tombstone_tg, secret.get("bot_token"), secret.get("proxy_base_url") or None)
            results.append(ok)
        elif channel_key.startswith("matrix_"):
            room_id = channel_key[len("matrix_"):]
            secret = {}
            for config_id, config, candidate in configs:
                target = (overrides.get(config_id, {}) or {}).get("room_id") or candidate.get("default_room_id") or candidate.get("room_id")
                if config.get("type") == "matrix" and str(target) == str(room_id):
                    secret = candidate
                    break
            if not secret:
                _, config = find_channel_for_legacy_target("matrix", room_id)
                secret = parse_channel_config_data(config.get("config", "{}"))
            deleted = redact_matrix_message(message_id, room_id, secret.get("homeserver_url"), secret.get("access_token"))
            ok = deleted or edit_matrix_message(tombstone_mx, message_id, room_id, secret.get("homeserver_url"), secret.get("access_token"))
            results.append(ok)
    state["active_cleanup_status"] = "complete" if results and all(results) else "partial_or_failed"
    state["active_cleanup_at"] = datetime.utcnow().isoformat()
    redis_client.set(f"incident:{incident_key}", json.dumps(state), ex=86400 * INCIDENT_RETENTION_DAYS)
    redis_client.hincrby("metrics:processor", "resolution_active_cleanup_success" if results and all(results) else "resolution_active_cleanup_failure", 1)
    return bool(results and all(results))


def find_channel_for_legacy_target(channel_type: str, target_id: str) -> tuple:
    """Resolve an old chat/room target to its current write-only channel config."""
    if not target_id:
        return "", {}
    try:
        channel_ids = list(redis_client.smembers("notification_channels:index") or set())
        if not channel_ids:
            return "", {}
        pipe = redis_client.pipeline(transaction=False)
        for channel_id in channel_ids:
            pipe.hgetall(f"notification_channel:{channel_id}")
        for channel_id, config in zip(channel_ids, pipe.execute()):
            if not config or config.get("type") != channel_type:
                continue
            secret = parse_channel_config_data(config.get("config", "{}"))
            configured_target = (
                secret.get("chat_id") or secret.get("default_chat_id")
                if channel_type == "telegram"
                else secret.get("default_room_id") or secret.get("room_id")
            )
            if str(configured_target or "") == str(target_id):
                return channel_id, config
    except Exception as exc:
        logger.warning("Could not resolve legacy %s target: %s", channel_type, exc)
    return "", {}


from utils import edit_telegram_message, edit_matrix_message

def dispatch_dynamic_alert(telegram_text: str, matrix_text: str,
                         channel_ids: list, overrides: dict = None,
                         action: str = "NEW", incident_key: str = "",
                         known_message_ids: dict = None,
                         delivery_alert_id: str = "", delivery_attempt: int = 1) -> tuple:
    """
    Dispatch alert to multiple dynamic channels.
    Returns (all_succeeded, destination_string, new_message_ids, failed_channel_ids)
    """
    if overrides is None:
        overrides = {}
    if known_message_ids is None:
        known_message_ids = {}

    success = False
    status_parts = []
    new_message_ids = {}
    failed_channel_ids = []

    if not channel_ids:
        return False, "No dynamic channels configured", {}, []

    for channel_id in channel_ids:
        channel_succeeded = False
        config = get_channel_config(channel_id)
        if not config:
            status_parts.append(f"MissingConfig({channel_id})")
            failed_channel_ids.append(channel_id)
            continue

        c_type = config.get("type")
        c_name = config.get("name", channel_id)

        # Apply override if exists
        override = overrides.get(channel_id, {})

        # Telegram Dispatch
        if c_type == "telegram":
            try:
                token_data = parse_channel_config_data(config.get("config", "{}"))
                bot_token = token_data.get("bot_token")
                chat_id = token_data.get("chat_id") or token_data.get("default_chat_id")
                proxy_url = token_data.get("proxy_base_url", "") or None

                # Use override if available, else channel default
                target_chat_id = override.get("chat_id") or chat_id
                target_thread_id = override.get("thread_id") or token_data.get("default_thread_id") or "0"

                if target_chat_id:
                    # Check if we should edit instead of send
                    channel_key = f"telegram_{target_chat_id}"
                    existing_msg_id = known_message_ids.get(channel_key)

                    if (action in ["RESOLVE", "MERGE", "UPDATE"]) and existing_msg_id:
                        if edit_telegram_message(target_chat_id, existing_msg_id, telegram_text, bot_token=bot_token, proxy_base_url=proxy_url):
                            success = True
                            channel_succeeded = True
                            status_parts.append(f"TelegramEdit:{c_name}:OK")
                        else:
                            status_parts.append(f"TelegramEdit:{c_name}:FAILED")
                    else:
                        # Standard send
                        send_ok, msg_id = send_telegram_auto(target_chat_id, int(target_thread_id), telegram_text, bot_token=bot_token, proxy_base_url=proxy_url)
                        if send_ok:
                            success = True
                            channel_succeeded = True
                            status_parts.append(f"Telegram:{c_name}:OK")
                            if msg_id:
                                new_message_ids[channel_key] = msg_id
                        else:
                            status_parts.append(f"Telegram:{c_name}:FAILED")
                else:
                    status_parts.append(f"Telegram:{c_name}:NO_ID")

            except Exception as e:
                status_parts.append(f"Telegram:{c_name}:ERR")
                logger.error(f"Telegram dispatch error: {e}")

        # Matrix Dispatch
        elif c_type == "matrix":
            try:
                conf = parse_channel_config_data(config.get("config", "{}"))
                homeserver_url = conf.get("homeserver_url")
                access_token = conf.get("access_token")
                default_room_id = conf.get("default_room_id")

                target_room_id = override.get("room_id") or default_room_id

                if target_room_id:
                    channel_key = f"matrix_{target_room_id}"
                    existing_msg_id = known_message_ids.get(channel_key)
                    if (action in ["RESOLVE", "MERGE", "UPDATE"]) and existing_msg_id:
                        if edit_matrix_message(matrix_text, existing_msg_id, target_room_id, homeserver_url, access_token):
                             success = True
                             channel_succeeded = True
                             status_parts.append(f"MatrixEdit:{c_name}:OK")
                        else:
                             status_parts.append(f"MatrixEdit:{c_name}:FAILED")
                    else:
                        send_ok, msg_id = send_matrix_message(matrix_text, room_id=target_room_id, homeserver_url=homeserver_url, access_token=access_token)
                        if send_ok:
                             success = True
                             channel_succeeded = True
                             status_parts.append(f"Matrix:{c_name}:OK")
                             if msg_id:
                                 new_message_ids[channel_key] = msg_id
                        else:
                             status_parts.append(f"Matrix:{c_name}:FAILED")
                else:
                    status_parts.append(f"Matrix:{c_name}:NO_ID")
            except Exception as e:
                status_parts.append(f"Matrix:{c_name}:ERR")
                logger.error(f"Matrix dispatch error: {e}")

        # Webhook Dispatch
        elif c_type == "webhook":
            try:
                raw_config = config.get("config", "{}")
                conf = {}
                if isinstance(raw_config, str):
                    try:
                        conf = json.loads(raw_config)
                    except:
                        pass
                elif isinstance(raw_config, dict):
                    conf = raw_config

                # Default URL from config
                url = conf.get("url")

                # Override URL if provided
                target_url = override.get("url") or url

                payload = {
                    "text": telegram_text, # Use formatted text
                    "matrix_text": matrix_text,
                    "channel_name": c_name
                }

                if send_webhook(target_url, payload):
                    success = True
                    channel_succeeded = True
                    status_parts.append(f"Webhook:{c_name}:OK")
                else:
                    status_parts.append(f"Webhook:{c_name}:FAILED")
            except Exception as e:
                status_parts.append(f"Webhook:{c_name}:ERR")
                logger.error(f"Webhook dispatch error: {e}")

        # SMS Dispatch (Kavenegar)
        elif c_type == "sms":
            try:
                raw_config = config.get("config", "{}")
                conf = {}
                if isinstance(raw_config, str):
                    try:
                        conf = json.loads(raw_config)
                    except:
                        pass
                elif isinstance(raw_config, dict):
                    conf = raw_config

                api_key = conf.get("api_key")
                default_receptor = conf.get("receptor")
                sender = conf.get("sender")

                # Override receptor (phone number) if provided
                target_receptor = override.get("receptor") or default_receptor

                # SMS usually needs shorter text, but we'll use telegram_text for now
                if send_sms(target_receptor, telegram_text, api_key, sender=sender):
                    success = True
                    channel_succeeded = True
                    status_parts.append(f"SMS:{c_name}:OK")
                else:
                    status_parts.append(f"SMS:{c_name}:FAILED")
            except Exception as e:
                status_parts.append(f"SMS:{c_name}:ERR")
                logger.error(f"SMS dispatch error: {e}")

        if not channel_succeeded:
            failed_channel_ids.append(channel_id)
        record_delivery(
            delivery_alert_id,
            channel_id,
            "delivered" if channel_succeeded else "failed",
            status_parts[-1] if status_parts else "no delivery result",
            delivery_attempt,
        )

    destination = ", ".join(status_parts) if status_parts else "No successful dispatch"
    all_succeeded = bool(channel_ids) and not failed_channel_ids
    return all_succeeded, destination, new_message_ids, failed_channel_ids


def dispatch_destinations(telegram_text: str, matrix_text: str, destination_ids: list,
                          action: str = "NEW", incident_key: str = "", known_message_ids: dict = None,
                          delivery_alert_id: str = "", delivery_attempt: int = 1) -> tuple:
    """Dispatch independent endpoint records, including multiple threads on one connector."""
    known_message_ids = known_message_ids or {}
    failed, status, saved = [], [], {}
    for destination_id in destination_ids or []:
        item = get_destination(destination_id)
        if not item:
            failed.append(destination_id)
            status.append(f"MissingDestination({destination_id})")
            record_delivery(delivery_alert_id, destination_id, "failed", "missing destination", delivery_attempt)
            continue
        target = item.get("target", {})
        ctype = item.get("type")
        target_key = ""
        if ctype == "telegram":
            target_key = f"telegram_{target.get('chat_id')}"
        elif ctype == "matrix":
            target_key = f"matrix_{target.get('room_id')}"
        known = {}
        # During migration, already-open incidents still carry the legacy
        # target-scoped key. Reuse it instead of creating a duplicate message.
        existing = known_message_ids.get(f"destination:{destination_id}") or known_message_ids.get(target_key)
        if existing and target_key:
            known[target_key] = existing
        ok, detail, message_ids, _ = dispatch_dynamic_alert(
            telegram_text, matrix_text, [item.get("channel_id")], {item.get("channel_id"): target},
            action=action, incident_key=incident_key, known_message_ids=known,
            delivery_alert_id="", delivery_attempt=delivery_attempt,
        )
        status.append(f"{item.get('name', destination_id)}:{detail}")
        if not ok:
            failed.append(destination_id)
        else:
            if target_key and message_ids.get(target_key):
                saved[f"destination:{destination_id}"] = message_ids[target_key]
            record_delivery(delivery_alert_id, destination_id, "delivered", detail, delivery_attempt)
        if not ok:
            record_delivery(delivery_alert_id, destination_id, "failed", detail, delivery_attempt)
    return bool(destination_ids) and not failed, ", ".join(status), saved, failed


def process_message(payload_str: str) -> tuple:
    """Process a single message from the queue."""
    global redis_client

    try:
        data = json.loads(payload_str)

        # Check if this is a force summary request
        if data.get("force_daily_summary"):
            user = data.get("user", "UI User")
            logger.info(f"Processing manual force daily summary request by {user}")
            generate_daily_summary()
            return True, payload_str

        # Check if this is a manual status update from the UI
        if data.get("manual_status_update"):
            alert_id = data.get("alert_id")
            new_status = data.get("new_status")
            user = data.get("user", "User")

            logger.info(f"Processing manual status update: {alert_id} -> {new_status} by {user}")

            alert = redis_client.hgetall(f"alert:{alert_id}")
            if not alert:
                return True, payload_str

            incident_key = alert.get("incident_key", "")
            if not incident_key:
                return True, payload_str

            state_json = redis_client.get(f"incident:{incident_key}")
            if not state_json:
                return True, payload_str

            state = json.loads(state_json)
            incident_message_ids = state.get("channels", {})
            original_text = state.get("original_telegram_text", "")

            if not incident_message_ids or not original_text:
                return True, payload_str

            # Maintain action history
            action_history_str = alert.get("action_history", "[]")
            try:
                action_history = json.loads(action_history_str)
            except:
                action_history = []

            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            action_history.append({
                "user": user,
                "status": new_status,
                "timestamp": now_str
            })

            # Save history to alert hash
            redis_client.hset(f"alert:{alert_id}", "action_history", json.dumps(action_history))

            # Rebuild suffix based on history
            suffix = "\n\n📋 *User Action History:*"

            def escape_mdv2(text):
                # Characters that need escaping in MarkdownV2
                escape_chars = r"_*[]()~`>#+-=|{}.!"
                for char in escape_chars:
                    text = str(text).replace(char, f"\\{char}")
                return text

            for act in action_history[-5:]: # Keep last 5 actions
                status_icon = "👀" if act["status"] == "acknowledged" else "✅" if act["status"] == "resolved" else "🔄"
                action_text = "Acknowledged by" if act["status"] == "acknowledged" else "Resolved via Panel by" if act["status"] == "resolved" else "Reverted to New by"

                safe_user = escape_mdv2(act['user'])
                safe_ts = escape_mdv2(act['timestamp'])
                suffix += f"\n{status_icon} {action_text} {safe_user} \\({safe_ts}\\)"

            if new_status == "resolved":
                suffix += "\n_\\(Resolved manually; awaiting source-system confirmation\\)_"
            else:
                suffix += "\n_\\(Monitoring source may still report this condition\\)_"

            updated_text = original_text + suffix

            from utils import edit_telegram_message, edit_matrix_message

            # Pre-fetch all channel configs to prevent N+1 queries
            channel_keys = redis_client.keys("notification_channel:*")
            all_configs = []
            if channel_keys:
                pipe = redis_client.pipeline(transaction=False)
                for ck in channel_keys:
                    pipe.hgetall(ck)
                all_configs = list(zip([str(key).split(":", 1)[-1] for key in channel_keys], pipe.execute()))

            telegram_configs = []
            matrix_configs = []
            for config_id, cfg in all_configs:
                try:
                    conf = parse_channel_config_data(cfg.get("config", "{}"))
                    c_type = cfg.get("type")
                    if c_type == "telegram":
                        telegram_configs.append((config_id, conf))
                    elif c_type == "matrix":
                        matrix_configs.append((config_id, conf))
                except Exception as e:
                    logger.debug(f"Failed to parse channel config json: {e}")

            failed_channel_ids = []
            retry_overrides = {}
            edit_results = []
            for channel_key, msg_id in incident_message_ids.items():
                if channel_key.startswith("telegram_"):
                    chat_id = channel_key.replace("telegram_", "")

                    bot_token, proxy_url = None, None
                    fb_bot_token, fb_proxy_url = None, None

                    matched_config_id = ""
                    for config_id, conf in telegram_configs:
                        if not fb_bot_token and conf.get("bot_token"):
                            fb_bot_token = conf.get("bot_token")
                            fb_proxy_url = conf.get("proxy_base_url", "") or None
                        if str(conf.get("chat_id")) == str(chat_id):
                            bot_token = conf.get("bot_token")
                            proxy_url = conf.get("proxy_base_url", "") or None
                            matched_config_id = config_id
                            break

                    bot_token = bot_token or fb_bot_token
                    proxy_url = proxy_url or fb_proxy_url
                    edit_ok = edit_telegram_message(chat_id, msg_id, updated_text, bot_token=bot_token, proxy_base_url=proxy_url)
                    edit_results.append(edit_ok)
                    record_delivery(alert_id, matched_config_id or f"manual:telegram:{chat_id}", "delivered" if edit_ok else "failed", "manual status edit", 1)
                    if not edit_ok and matched_config_id:
                        failed_channel_ids.append(matched_config_id)
                        retry_overrides[matched_config_id] = {"chat_id": chat_id}

                elif channel_key.startswith("matrix_"):
                    room_id = channel_key.replace("matrix_", "")

                    hs_url, access_token = None, None
                    fb_hs_url, fb_access_token = None, None

                    matched_config_id = ""
                    for config_id, conf in matrix_configs:
                        if not fb_hs_url and conf.get("homeserver_url") and conf.get("access_token"):
                            fb_hs_url = conf.get("homeserver_url")
                            fb_access_token = conf.get("access_token")
                        if str(conf.get("default_room_id")) == str(room_id):
                            hs_url = conf.get("homeserver_url")
                            access_token = conf.get("access_token")
                            matched_config_id = config_id
                            break

                    hs_url = hs_url or fb_hs_url
                    access_token = access_token or fb_access_token
                    edit_ok = edit_matrix_message(updated_text, msg_id, room_id, homeserver_url=hs_url, access_token=access_token)
                    edit_results.append(edit_ok)
                    record_delivery(alert_id, matched_config_id or f"manual:matrix:{room_id}", "delivered" if edit_ok else "failed", "manual status edit", 1)
                    if not edit_ok and matched_config_id:
                        failed_channel_ids.append(matched_config_id)
                        retry_overrides[matched_config_id] = {"room_id": room_id}

            if failed_channel_ids:
                schedule_retry({
                    "sender": "manual_status_update", "subject": alert.get("subject", "Manual status update"),
                    "retry_count": 0, "telegram_msg": updated_text, "matrix_msg": updated_text.replace("\\", ""),
                    "channel": "dynamic", "notification_channel_ids": failed_channel_ids,
                    "channel_overrides": retry_overrides, "action": "UPDATE", "incident_key": incident_key,
                    "known_message_ids": incident_message_ids, "alert_id": alert_id,
                })
            if edit_results and all(edit_results):
                tracker = IncidentTracker(redis_client)
                tracker.save_message_ids(incident_key, {}, telegram_text=updated_text)

            return True, payload_str

        sender = data.get("from", "")
        subject = data.get("subject", "")
        is_analysis_only = bool(data.get("analysis_only_alert_id"))

        # Check mute list
        if not is_analysis_only and is_muted(sender):
            logger.info(f"Muted sender: {sender}")
            add_log("INFO", f"Skipped muted sender: {sender}")
            increment_metric("muted")
            return True, payload_str

        # Get body
        body = data.get("text", "")
        if not body:
            html_body = data.get("html", "")
            body = html_to_text(html_body) if html_body else ""

        # Grafana may group active and recovered instances in one email. Treat
        # them as ordered events so correlation cannot collapse opposite states.
        split_payloads = split_grafana_mixed_payload(data, body)
        if split_payloads:
            for split_payload in split_payloads:
                redis_client.xadd(
                    REDIS_STREAM,
                    {"payload": json.dumps(split_payload), "trace_id": split_payload.get("trace_id", "")},
                    maxlen=100000,
                    approximate=True,
                )
            add_log("INFO", "Grafana mixed-state alert split", {
                "subject": subject[:120],
                "events": len(split_payloads),
            })
            return True, payload_str

        logger.info(f"📩 Processing: From={sender}, Subject={subject[:50]}")
        ingestion_day = datetime.utcnow().strftime("%Y-%m-%d")
        ingestion_transport = str(data.get("ingestion_transport", "other")).lower()
        redis_client.hincrby("metrics:ingestion", f"processor_received_{ingestion_transport}", 1)
        redis_client.hincrby(f"metrics:ingestion:daily:{ingestion_day}", f"processor_received_{ingestion_transport}", 1)
        redis_client.expire(f"metrics:ingestion:daily:{ingestion_day}", 86400 * 14)
        normalized_alert = normalize_alert(sender, subject, body)
        source_type = normalized_alert.get("source_type", "generic")
        redis_client.hincrby("metrics:source:received", source_type, 1)

        # Extract recipient emails for TO-based routing
        recipient_emails = data.get("rcpt_tos", [])
        if not recipient_emails:
            to_email = data.get("to", "")
            if to_email:
                recipient_emails = [to_email]

        tracker = IncidentTracker(redis_client)

        # ── Hook 1: Exact Dedup Check ──
        is_reprocess = (
            "reprocess_alert_id" in data
            or "resend_alert_id" in data
            or is_analysis_only
        )
        exact_hash = ""
        if not is_reprocess:
            exact_hash = tracker.generate_exact_hash(data)
            exact_key = f"dedup:exact:{exact_hash}"
            audit_key = f"dedup:audit:{exact_hash}"
            body_digest = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
            audit_mapping = {
                "hash": exact_hash,
                "sender_domain": sender.rsplit("@", 1)[-1].lower() if "@" in sender else "unknown",
                "subject": subject[:300],
                "body_sha256": body_digest,
                "last_seen": datetime.utcnow().isoformat(),
            }
            if redis_client.exists(exact_key):
                logger.info(f"🚫 Exact Drop: Duplicate of {exact_hash}")
                redis_client.incr(exact_key)
                # Update expiry
                redis_client.expire(exact_key, 1800) # 30 min rolling window
                redis_client.hset(audit_key, mapping=audit_mapping)
                redis_client.hincrby(audit_key, "suppressed_occurrences", 1)
                redis_client.expire(audit_key, 86400)
                incident_key = redis_client.get(f"dedup:exact:incident:{exact_hash}") or ""
                if tracker.record_suppressed_occurrence(incident_key):
                    redis_client.expire(f"dedup:exact:incident:{exact_hash}", 1800)
                    redis_client.hincrby("metrics:processor", "exact_occurrences_recorded", 1)
                increment_metric("muted")
                add_log("INFO", f"Exact duplicate suppressed", {"hash": exact_hash, "incident_key": incident_key})
                return True, payload_str
            else:
                redis_client.setex(exact_key, 1800, 1)
                audit_mapping["first_seen"] = audit_mapping["last_seen"]
                audit_mapping["suppressed_occurrences"] = "0"
                redis_client.hset(audit_key, mapping=audit_mapping)
                redis_client.expire(audit_key, 86400)

        # ── Phase 1: Routing ──
        route_start = time.time()
        rules = get_routing_rules()
        routing = get_routing_targets(
            sender,
            rules,
            TELEGRAM_DEFAULT_CHAT_ID,
            TELEGRAM_DEFAULT_THREAD_ID,
            MATRIX_DEFAULT_ROOM_ID,
            DEFAULT_NOTIFICATION_CHANNEL,
            recipient_emails=recipient_emails
        )

        matched_rule = routing["matched_rule"]
        redis_client.hincrby("metrics:routing:matched", routing.get("matched_rule_id", "default"), 1)
        channel = routing["channel"]  # "telegram", "matrix", "both", "dynamic"

        # Legacy single-channel vars
        chat_id = routing.get("telegram_chat_id")
        thread_id = routing.get("telegram_thread_id")
        room_id = routing.get("matrix_room_id")

        # New dynamic vars
        notification_channel_ids = routing.get("notification_channel_ids", [])
        channel_overrides = routing.get("channel_overrides", {})
        alert_destination_ids = routing.get("alert_destination_ids", [])
        resolved_destination_ids = routing.get("resolved_destination_ids", [])
        resolution_mode = routing.get("resolution_mode", "legacy")
        if data.get("self_monitor_event") and not matched_rule:
            default_channel_ids = get_default_notification_channel_ids()
            if default_channel_ids:
                channel = "dynamic"
                notification_channel_ids = default_channel_ids
        route_duration = round(time.time() - route_start, 2)

        if matched_rule:
            logger.info(f"🔀 Routing matched: \"{matched_rule}\" → {channel} ({route_duration}s)")
            add_log("INFO", f"Routing matched: {matched_rule} → {channel}", {"duration": f"{route_duration}s"})
        else:
            logger.info(f"🔀 No routing rule matched, using defaults ({route_duration}s)")
            add_log("INFO", f"No routing rule, using defaults", {"duration": f"{route_duration}s"})


        # ── Phase 2: AI Analysis (with Context) ──
        active_candidates = tracker.get_similar_open_incidents(sender, subject, body=body, limit=10)
        active_context = ""
        if active_candidates:
            lines = []
            for c in active_candidates:
                lines.append(
                    f"- ID: {c['id']} | Subject: {c['subject']} | Target: {c['target']} "
                    f"| Resources: {json.dumps(c.get('resources', []))} "
                    f"| Latest: {c.get('main_message', '')} | Occurrences: {c['occurrences']}"
                )
            active_context = "\n".join(lines)

        ai_provider_id = routing.get("ai_provider_id")
        ai_result, ai_provider_name, ai_duration = analyze_email(
            sender, subject, body,
            provider_id=ai_provider_id,
            active_incidents_context=active_context
        )

        if ai_result:
            add_log("INFO", f"AI analysis complete ({ai_duration}s)", {
                "provider": ai_provider_name,
                "severity": ai_result.get("analysis", {}).get("severity", ""),
                "category": ai_result.get("analysis", {}).get("category", ""),
                "system": ai_result.get("analysis", {}).get("system_name", ""),
                "duration": f"{ai_duration}s"
            })

        # Analysis-only jobs enrich an existing alert in place. They must never
        # mutate incident state, occurrence counters, or notification messages.
        analysis_only_alert_id = data.get("analysis_only_alert_id")
        if analysis_only_alert_id:
            alert_key = f"alert:{analysis_only_alert_id}"
            if not redis_client.exists(alert_key):
                logger.warning("AI backfill target no longer exists: %s", analysis_only_alert_id)
                return True, payload_str

            now = datetime.utcnow().isoformat()
            if ai_result:
                analysis = ai_result.get("analysis", {})
                redis_client.hset(alert_key, mapping={
                    "severity": str(analysis.get("severity", "")),
                    "category": str(analysis.get("category", "")),
                    "confidence": str(analysis.get("confidence", "")),
                    "system_name": str(analysis.get("system_name", "")),
                    "main_message": str(analysis.get("main_message", "")),
                    "details": str(analysis.get("details", "")),
                    "recommended_actions": json.dumps(analysis.get("recommended_actions", [])),
                    "ai_raw": json.dumps(ai_result),
                    "analysis_status": "complete",
                    "analysis_provider": ai_provider_name,
                    "analysis_duration": str(ai_duration),
                    "analysis_updated_at": now,
                    "updated_at": now,
                })
                score = redis_client.zscore("alerts:index", analysis_only_alert_id) or time.time()
                redis_client.zrem("alerts:severity:unclassified", analysis_only_alert_id)
                redis_client.zrem("alerts:category:unclassified", analysis_only_alert_id)
                redis_client.zadd(
                    f"alerts:severity:{str(analysis.get('severity') or 'unclassified').lower()}",
                    {analysis_only_alert_id: score},
                )
                redis_client.zadd(
                    f"alerts:category:{str(analysis.get('category') or 'unclassified').lower()}",
                    {analysis_only_alert_id: score},
                )
                increment_metric("ai_backfill_succeeded")
                add_log("INFO", f"AI backfill complete: {analysis_only_alert_id}", {
                    "provider": ai_provider_name,
                    "duration": f"{ai_duration}s",
                })
            else:
                redis_client.hset(alert_key, mapping={
                    "analysis_status": "failed",
                    "analysis_updated_at": now,
                    "updated_at": now,
                })
                increment_metric("ai_backfill_failed")
                add_log("ERROR", f"AI backfill failed: {analysis_only_alert_id}")
            return True, payload_str


        # ── Phase 2.5: Severity-Based Routing (New) ──
        # If the matched rule has specific actions for this severity, override targets
        severity_matrix = routing.get("severity_destination_ids", {})

        # Parse severity_matrix from JSON string if needed
        if isinstance(severity_matrix, str):
            try:
                severity_matrix = json.loads(severity_matrix)
            except:
                severity_matrix = {}

        detected_severity = ""
        if ai_result:
             detected_severity = (ai_result.get("analysis", {}).get("severity", "") or "").lower()

        if detected_severity and severity_matrix:
            # Case-insensitive lookup
            sev_entry = None
            for s_key, s_val in severity_matrix.items():
                if s_key.lower() == detected_severity:
                    sev_entry = s_val
                    break

            if isinstance(sev_entry, list) and sev_entry:
                alert_destination_ids = sev_entry
                logger.info(f"🚨 Severity destination policy applied: {detected_severity} → {len(alert_destination_ids)} destinations")
                add_log("INFO", f"Severity destination policy: {detected_severity}", {"destinations": len(alert_destination_ids)})
        # ── Hook 2: Semantic Correlation (True AI) ──
        correlation_result = {}
        is_resend = "resend_alert_id" in data

        if is_resend:
            # Resend: always force a fresh NEW dispatch — bypass all dedup and correlation.
            # User explicitly requested re-notification; do not edit existing messages.
            logger.info(f"📤 Resend requested for alert {data['resend_alert_id']} — forcing NEW dispatch")
            correlation_result = tracker.process_incident_state_ai(
                sender, subject, "NEW", target_resource="resend"
            )
        elif is_reprocess and "reprocess_alert_id" in data:
            old_alert = redis_client.hgetall(f"alert:{data['reprocess_alert_id']}")
            if old_alert:
                incident_key = old_alert.get("incident_key", "")
                state_json = redis_client.get(f"incident:{incident_key}")
                if state_json:
                    state = json.loads(state_json)
                    correlation_result = {
                        "action": "UPDATE",
                        "incident_key": incident_key,
                        "message_ids": state.get("channels", {}),
                        "occurrences": state.get("occurrences", 1),
                        "original_text": state.get("original_text", ""),
                        "revision": int(state.get("revision", 1) or 1),
                    }

        if not correlation_result:
            if ai_result and "analysis" in ai_result:
                ai_analysis = ai_result["analysis"]
                ai_action = ai_analysis.get("action", "NEW").upper()
                ai_analysis.setdefault("model_action", ai_action)
                ai_analysis.setdefault("model_target_incident_id", ai_analysis.get("target_incident_id", ""))
                if str(ai_analysis.get("status", "")).upper() == "RESOLVED" and ai_action == "NEW":
                    logger.warning("Resolved analysis attempted NEW; converting to standalone resolve")
                    ai_action = "RESOLVE"
                    ai_analysis["action"] = "RESOLVE"
                    ai_analysis["target_incident_id"] = ""
                target_id = ai_analysis.get("target_incident_id", "")
                target_resource = ai_analysis.get("target_resource", "unknown")
                target_resources = ai_analysis.get("target_resources", [])
                source_fingerprint = ai_analysis.get("source_fingerprint", "")
                identity = build_correlation_identity(sender, subject, body, ai_analysis)
                correlation_key = identity.get("correlation_key", "")
                correlation_identity = identity.get("correlation_identity", "")
                if correlation_key:
                    ai_analysis["correlation_key"] = correlation_key
                    ai_analysis["correlation_identity"] = correlation_identity
                    deterministic_target = tracker.find_open_by_correlation_key(sender, correlation_key)
                    ai_status = str(ai_analysis.get("status", "")).upper()
                    if deterministic_target:
                        ai_action = "RESOLVE" if ai_status == "RESOLVED" else "UPDATE"
                        target_id = deterministic_target
                        logger.info("Deterministic correlation matched %s -> %s", correlation_key, deterministic_target)
                        redis_client.hincrby("metrics:processor", "deterministic_correlations", 1)
                    elif ai_status == "RESOLVED":
                        ai_action = "RESOLVE"
                        target_id = ""
                    elif target_id:
                        target_raw = redis_client.get(f"incident:{target_id}")
                        target_state = json.loads(target_raw) if target_raw else {}
                        target_key = target_state.get("correlation_key", "")
                        if target_key and target_key != correlation_key:
                            logger.warning("AI target rejected by deterministic identity: %s != %s", target_key, correlation_key)
                            ai_action, target_id = "NEW", ""
                            redis_client.hincrby("metrics:processor", "identity_target_rejections", 1)
                else:
                    correlation_key = correlation_identity = ""
                ai_analysis["action"] = ai_action
                ai_analysis["target_incident_id"] = target_id

                # AI makes the decision
                correlation_result = tracker.process_incident_state_ai(
                    sender, subject, ai_action, target_incident_id=target_id,
                    target_resource=target_resource,
                    target_resources=target_resources,
                    main_message=ai_analysis.get("main_message", ""),
                    details=ai_analysis.get("details", []),
                    source_fingerprint=source_fingerprint,
                    correlation_key=correlation_key,
                    correlation_identity=correlation_identity,
                )
            else:
                # Keep raw fallbacks visible, but do not pollute semantic correlation.
                correlation_result = tracker.process_incident_state_ai(
                    sender, subject, "NEW", target_resource="analysis_failed",
                    track_open=False
                )

        action = correlation_result.get("action", "NEW")
        incident_key = correlation_result.get("incident_key", "")
        incident_message_ids = correlation_result.get("message_ids", {})
        if action == "NEW" and ai_result:
            snapshot_incident_resolution(
                incident_key, routing,
                {
                    "channel": channel,
                    "notification_channel_ids": notification_channel_ids,
                    "channel_overrides": channel_overrides,
                    "telegram_chat_id": chat_id,
                    "telegram_thread_id": thread_id,
                    "matrix_room_id": room_id,
                    "destinations": destination_snapshot(alert_destination_ids),
                    "destination_ids": alert_destination_ids,
                },
                ai_result.get("analysis", {}), data,
            )
        if exact_hash and incident_key:
            redis_client.setex(f"dedup:exact:incident:{exact_hash}", 1800, incident_key)

        # Save alert to Redis with Correlation Data
        alert_id = save_alert(
            data, ai_result, channel, incident_key, action,
            analysis_provider=ai_provider_name,
            analysis_duration=ai_duration,
        )
        if action == "ORPHAN_RESOLVE":
            redis_client.hset(f"alert:{alert_id}", mapping={
                "notification_suppressed": "orphan_resolve",
                "status": "resolved",
                "system_resolved": "true",
            })
            redis_client.hincrby("metrics:processor", "orphan_resolves", 1)
            logger.info("Standalone recovery stored without notification: %s", alert_id)
            return True, payload_str
        current_analysis = ai_result.get("analysis", {}) if ai_result else {}
        # Persist the exact rendered payloads shown to operators. Secrets and
        # destination identifiers are deliberately excluded.
        telegram_msg = format_alert(ai_result, sender, subject, body)
        matrix_msg = format_for_matrix(ai_result, sender, subject, body)
        redis_client.hset(f"alert:{alert_id}", mapping={
            "notification_preview_telegram": telegram_msg,
            "notification_preview_matrix": matrix_msg,
        })
        global_suppressed, global_count = should_suppress_global_storm(
            alert_id, incident_key, action, str(current_analysis.get("severity", "")), data, current_analysis,
        )
        if global_suppressed:
            logger.warning("🌊 Global storm suppressed notification %s (%s events/window)", alert_id, global_count)
            return True, payload_str

        if action == "IGNORE":
            redis_client.hset(f"alert:{alert_id}", "notification_suppressed", "redundant_resolve")
            logger.info(f"🔇 Redundant Resolve Dropped: {incident_key}")
            return True, payload_str
        elif action == "MERGE":
            logger.info(f"🔄 Updating incident: {incident_key} with latest analysis")
            occurrences = correlation_result.get("occurrences", 2)
            first_seen = correlation_result.get("first_seen")
            first_seen_text = datetime.fromtimestamp(first_seen).strftime("%Y-%m-%d %H:%M:%S") if first_seen else "unknown"
            telegram_msg = (
                f"{telegram_msg}\n\n📌 *Incident occurrences:* `{occurrences}`"
                f"\n🕐 *First seen:* `{escape_md_v2(first_seen_text)}`"
            )
            matrix_msg = (
                f"{matrix_msg}\n\n📌 Incident occurrences: {occurrences}"
                f"\n🕐 First seen: {first_seen_text}"
            )
            redis_client.hset(f"alert:{alert_id}", mapping={
                "notification_preview_telegram": telegram_msg,
                "notification_preview_matrix": matrix_msg,
            })

            storm_suppressed, storm_count = should_suppress_incident_notification(incident_key, action)
            if storm_suppressed:
                redis_client.hset(f"alert:{alert_id}", mapping={
                    "notification_suppressed": "storm_cooldown",
                    "storm_window_count": str(storm_count),
                })
                redis_client.xadd(f"incident:events:{incident_key}", {
                    "alert_id": alert_id, "action": "SUPPRESSED", "status": "storm_cooldown",
                    "detail": f"{storm_count} occurrences in {ALERT_STORM_WINDOW_SECONDS}s",
                    "occurred_at": datetime.utcnow().isoformat(),
                }, maxlen=1000, approximate=True)
                logger.warning("🌊 Storm cooldown suppressed %s (%s occurrences)", incident_key, storm_count)
                return True, payload_str

            if alert_destination_ids:
                success, destination, new_msg_ids, failed_channel_ids = dispatch_destinations(
                    telegram_msg, matrix_msg, alert_destination_ids,
                    action="MERGE", incident_key=incident_key, known_message_ids=incident_message_ids,
                    delivery_alert_id=alert_id,
                )
            elif channel == "dynamic":
                success, destination, new_msg_ids, failed_channel_ids = dispatch_dynamic_alert(
                    telegram_text=telegram_msg, matrix_text=matrix_msg,
                    channel_ids=notification_channel_ids, overrides=channel_overrides,
                    action="MERGE", incident_key=incident_key,
                    known_message_ids=incident_message_ids,
                    delivery_alert_id=alert_id,
                )
            else:
                resolved_channel_ids = []
                for channel_key in incident_message_ids:
                    if channel_key.startswith("telegram_"):
                        config_id, _ = find_channel_for_legacy_target("telegram", channel_key.replace("telegram_", ""))
                    elif channel_key.startswith("matrix_"):
                        config_id, _ = find_channel_for_legacy_target("matrix", channel_key.replace("matrix_", ""))
                    else:
                        config_id = ""
                    if config_id and config_id not in resolved_channel_ids:
                        resolved_channel_ids.append(config_id)
                if resolved_channel_ids:
                    success, destination, new_msg_ids, failed_channel_ids = dispatch_dynamic_alert(
                        telegram_msg, matrix_msg, resolved_channel_ids, {},
                        action="MERGE", incident_key=incident_key,
                        known_message_ids=incident_message_ids,
                        delivery_alert_id=alert_id,
                    )
                else:
                    success, destination, new_msg_ids, failed_channel_ids = False, "Legacy targets have no matching channel config", {}, []

            tracker.save_message_ids(incident_key, new_msg_ids or {}, telegram_text=telegram_msg)
            add_relay_log(sender, subject, channel, destination, success)
            if success:
                increment_metric("processed")
                logger.info("✅ Incident updated: %s", destination)
            else:
                increment_metric("errors")
                logger.error("❌ Incident update failed: %s", destination)
                schedule_retry({
                    "sender": sender,
                    "subject": subject,
                    "original_payload": payload_str,
                    "retry_count": 0,
                    "telegram_msg": telegram_msg,
                    "matrix_msg": matrix_msg,
                    "channel": "destinations" if alert_destination_ids else ("dynamic" if failed_channel_ids else channel),
                    "chat_id": chat_id,
                    "thread_id": thread_id,
                    "room_id": room_id,
                    "notification_channel_ids": failed_channel_ids,
                    "destination_ids": failed_channel_ids if alert_destination_ids else [],
                    "channel_overrides": channel_overrides,
                    "action": "MERGE",
                    "incident_key": incident_key,
                    "known_message_ids": incident_message_ids,
                    "alert_id": alert_id,
                })
            return True, payload_str

        # ── Phase 3: Format & Dispatch ──
        dispatch_start = time.time()
        if action == "RESOLVE":
            state_raw = redis_client.get(f"incident:{incident_key}")
            state = json.loads(state_raw) if state_raw else {}
            destination_route = state.get("resolution_destination_snapshot") or {}
            resolved_ids = destination_route.get("destination_ids", [])
            if resolved_ids and destination_route.get("mode") in {"copy", "move"}:
                telegram_msg, matrix_msg, _ = build_resolution_cards(
                    incident_key, state, current_analysis, data, _incident_events(incident_key)
                )
                redis_client.hset(f"alert:{alert_id}", mapping={
                    "notification_preview_telegram": telegram_msg,
                    "notification_preview_matrix": matrix_msg,
                    "resolution_routing": destination_route.get("mode"),
                })
                success, destination, archive_ids, failed_destination_ids = dispatch_destinations(
                    telegram_msg, matrix_msg, resolved_ids, action="NEW", incident_key=incident_key,
                    known_message_ids={}, delivery_alert_id=alert_id,
                )
                _save_resolution_archive(incident_key, archive_ids)
                cleanup_requested = destination_route.get("mode") == "move"
                if success:
                    if cleanup_requested:
                        cleanup_active_incident_messages(incident_key, state.get("active_route_snapshot", {}))
                    increment_metric("processed")
                else:
                    schedule_retry({
                        "sender": sender, "subject": subject, "original_payload": payload_str,
                        "retry_count": 0, "telegram_msg": telegram_msg, "matrix_msg": matrix_msg,
                        "channel": "destinations", "destination_ids": failed_destination_ids,
                        "action": "NEW", "incident_key": incident_key, "known_message_ids": {},
                        "alert_id": alert_id, "incident_revision": correlation_result.get("revision", 0),
                        "resolution_archive": True, "cleanup_after_archive": cleanup_requested,
                        "active_route_snapshot": state.get("active_route_snapshot", {}),
                    })
                add_relay_log(sender, subject, "resolution_destinations", destination, success)
                return True, payload_str
            profile = state.get("resolution_profile_snapshot") or {}
            if profile and profile.get("notification_channel_ids"):
                telegram_msg, matrix_msg, _ = build_resolution_cards(
                    incident_key, state, current_analysis, data, _incident_events(incident_key)
                )
                redis_client.hset(f"alert:{alert_id}", mapping={
                    "notification_preview_telegram": telegram_msg,
                    "notification_preview_matrix": matrix_msg,
                    "resolution_profile_id": profile.get("id", ""),
                    "resolution_routing": "archive",
                })
                success, destination, archive_ids, failed_channel_ids = dispatch_dynamic_alert(
                    telegram_msg, matrix_msg,
                    profile.get("notification_channel_ids", []), profile.get("channel_overrides", {}),
                    action="NEW", incident_key=incident_key, known_message_ids={},
                    delivery_alert_id=alert_id,
                )
                _save_resolution_archive(incident_key, archive_ids)
                cleanup_requested = (
                    profile.get("behavior") == "archive_and_remove"
                    or bool(profile.get("delete_active_after_resolve"))
                )
                if success:
                    if cleanup_requested:
                        cleanup_active_incident_messages(incident_key, state.get("active_route_snapshot", {}))
                    increment_metric("processed")
                    redis_client.hincrby("metrics:processor", "resolution_archives_delivered", 1)
                else:
                    redis_client.hincrby("metrics:processor", "resolution_archives_failed", 1)
                    schedule_retry({
                        "sender": sender, "subject": subject, "original_payload": payload_str,
                        "retry_count": 0, "telegram_msg": telegram_msg, "matrix_msg": matrix_msg,
                        "channel": "dynamic", "notification_channel_ids": failed_channel_ids,
                        "channel_overrides": profile.get("channel_overrides", {}), "action": "NEW",
                        "incident_key": incident_key, "known_message_ids": {}, "alert_id": alert_id,
                        "incident_revision": correlation_result.get("revision", 0),
                        "resolution_archive": True, "cleanup_after_archive": cleanup_requested,
                        "active_route_snapshot": state.get("active_route_snapshot", {}),
                    })
                add_relay_log(sender, subject, "resolution_archive", destination, success)
                logger.info("Resolution archive %s for incident %s: %s", "delivered" if success else "queued", incident_key, destination)
                return True, payload_str
        # UX Improvement: For RESOLVED action, append the resolution to the ORIGINAL text instead of overwriting it
        if action == "RESOLVE":
            original_text = correlation_result.get("original_text", "")
            if original_text:
                resolve_summary = ai_result.get("analysis", {}).get("main_message", "Issue has been resolved")
                resolve_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                from ai_service import escape_markdown_v2

                safe_time = escape_markdown_v2(resolve_time)
                safe_summary = escape_markdown_v2(resolve_summary)

                # Try to visually green-ify the original severity icon if possible using robust regex
                import re
                green_text = re.sub(r'(🔴|🟠|🟡|🔵|⚪|ℹ️)\s*\*?(Critical|High|Medium|Low|Info)\*?', r'🟢 *RESOLVED*', original_text, flags=re.IGNORECASE)

                telegram_msg = f"{green_text}\n\n✅ *RESOLUTION CONFIRMED* \\({safe_time}\\)\n📝 {safe_summary}"
                matrix_msg = f"{green_text}\n\n✅ *RESOLUTION CONFIRMED* ({resolve_time})\n📝 {resolve_summary}"

        logger.info(f"🟢 Proceeding with dispatch: {incident_key} [{action}]")

        success = False
        destination = "None"

        if alert_destination_ids:
             success, destination, new_msg_ids, failed_channel_ids = dispatch_destinations(
                 telegram_msg, matrix_msg, alert_destination_ids,
                 action=action, incident_key=incident_key, known_message_ids=incident_message_ids,
                 delivery_alert_id=alert_id,
             )
             if new_msg_ids:
                 tracker.save_message_ids(incident_key, new_msg_ids, telegram_text=telegram_msg)
        elif channel == "dynamic":
             logger.info(f"📤 Dispatching to {len(notification_channel_ids)} dynamic channel(s)...")
             success, destination, new_msg_ids, failed_channel_ids = dispatch_dynamic_alert(
                 telegram_msg, matrix_msg,
                 notification_channel_ids, channel_overrides,
                 action=action, incident_key=incident_key, known_message_ids=incident_message_ids,
                 delivery_alert_id=alert_id,
             )
             if new_msg_ids:
                 tracker.save_message_ids(incident_key, new_msg_ids, telegram_text=telegram_msg)
        else:
             logger.info(f"📤 Dispatching via legacy channel: {channel}...")
             legacy_statuses = []
             new_msg_ids = {}

             try:
                 # Telegram Legacy
                 if channel in ["telegram", "both"]:
                     channel_key = f"telegram_{chat_id}"
                     existing_msg_id = incident_message_ids.get(channel_key)

                     if action in ["RESOLVE", "MERGE", "UPDATE"] and existing_msg_id:
                         # Use edit logic
                         from utils import edit_telegram_message
                         if edit_telegram_message(chat_id, existing_msg_id, telegram_msg):
                             legacy_statuses.append("TelegramEdit:OK")
                             success = True
                         else:
                             legacy_statuses.append("TelegramEdit:FAILED")
                     else:
                         # Standard send
                         send_ok, msg_id = send_telegram_auto(chat_id, int(thread_id), telegram_msg)
                         if send_ok:
                             legacy_statuses.append("Telegram:OK")
                             success = True
                             if msg_id:
                                 new_msg_ids[channel_key] = msg_id
                         else:
                             legacy_statuses.append("Telegram:FAILED")

                 # Matrix Legacy
                 if channel in ["matrix", "both"]:
                     channel_key = f"matrix_{room_id}"
                     existing_msg_id = incident_message_ids.get(channel_key)

                     if action in ["RESOLVE", "MERGE", "UPDATE"] and existing_msg_id:
                         from utils import edit_matrix_message
                         if edit_matrix_message(matrix_msg, existing_msg_id, room_id):
                             legacy_statuses.append("MatrixEdit:OK")
                             success = True
                         else:
                             legacy_statuses.append("MatrixEdit:FAILED")
                     else:
                         send_ok, msg_id = send_matrix_message(matrix_msg, room_id)
                         if send_ok:
                             legacy_statuses.append("Matrix:OK")
                             success = True
                             if msg_id:
                                 new_msg_ids[channel_key] = msg_id
                         else:
                             legacy_statuses.append("Matrix:FAILED")

                 destination = ", ".join(legacy_statuses)
                 if new_msg_ids:
                     tracker.save_message_ids(incident_key, new_msg_ids, telegram_text=telegram_msg)
             except Exception as e:
                 logger.error(f"Legacy dispatch error: {e}")
                 destination = "Legacy:ERR"

        dispatch_duration = round(time.time() - dispatch_start, 2)

        # Log relay
        add_relay_log(sender, subject, channel, destination, success)

        total_duration = round(ai_duration + dispatch_duration + route_duration, 1)

        if success:
            logger.info(f"✅ Alert relayed: {destination} ({dispatch_duration}s dispatch, {total_duration}s total)")
            increment_metric("processed")
            add_log("INFO", f"Alert relayed: {destination}", {
                "channel": "destinations" if alert_destination_ids else channel,
                "dispatch_time": f"{dispatch_duration}s",
                "total_time": f"{total_duration}s",
                "ai_provider": ai_provider_name
            })
            if not ai_result:
                logger.warning(f"⚠️ AI failed for Alert ID: {alert_id}, but raw dispatch succeeded.")
                # We do not return False here, because the raw dispatch succeeded and retrying won't run AI anyway.
            return True, payload_str
        else:
            logger.error(f"❌ Failed to relay: {destination} ({dispatch_duration}s)")
            increment_metric("errors")
            add_log("ERROR", f"Relay failed: {destination}", {"dispatch_time": f"{dispatch_duration}s"})

            # Schedule retry with the formatted messages (preserving AI formatting if present)
            retry_data = {
                "sender": sender,
                "subject": subject,
                "original_payload": payload_str,
                "retry_count": 0,
                "telegram_msg": telegram_msg,
                "matrix_msg": matrix_msg,
                "channel": "destinations" if alert_destination_ids else channel,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "room_id": room_id,
                "notification_channel_ids": failed_channel_ids if channel == "dynamic" else notification_channel_ids,
                "destination_ids": failed_channel_ids if alert_destination_ids else [],
                "channel_overrides": channel_overrides,
                "action": action,
                "incident_key": incident_key,
                "known_message_ids": incident_message_ids,
                "alert_id": alert_id,
                "incident_revision": int(correlation_result.get("revision", 1) or 1),
                "failure_reason": destination,
            }
            schedule_retry(retry_data)
            return True, payload_str

    except json.JSONDecodeError:
        logger.error("Failed to decode JSON payload")
        add_log("ERROR", "Invalid JSON payload")
        increment_metric("errors")
        return False, payload_str
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        add_log("ERROR", f"Processing error: {str(e)}")
        increment_metric("errors")
        return False, payload_str


def escape_md_v2(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    # Characters that need escaping in MarkdownV2
    reserved = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in reserved:
        text = text.replace(char, f"\\{char}")
    return text


def join_markdown_lines(lines: list, limit: int = 3900) -> str:
    """Truncate at complete line boundaries so Markdown entities stay balanced."""
    kept = []
    size = 0
    omitted = False
    for line in lines:
        addition = len(line) + (1 if kept else 0)
        if size + addition > limit - 56:
            omitted = True
            break
        kept.append(line)
        size += addition
    if omitted:
        kept.extend(["", "_Additional incidents omitted due to message size\\._"])
    return "\n".join(kept)

def generate_daily_summary():
    global redis_client
    try:
        if not redis_client:
            return

        logger.info("Generating daily summary...")

        all_ids = redis_client.zrange("alerts:index", 0, -1)
        open_alerts = []
        now = time.time()

        if all_ids:
            pipe = redis_client.pipeline(transaction=False)
            for aid in all_ids:
                aid_str = aid.decode("utf-8") if isinstance(aid, bytes) else aid
                pipe.hmget(f"alert:{aid_str}", "status", "subject", "system_name", "created_at", "main_message")
            results = pipe.execute()

            for aid, fields in zip(all_ids, results):
                if not fields or len(fields) < 4:
                    continue
                aid_str = aid.decode("utf-8") if isinstance(aid, bytes) else aid
                st = fields[0]
                if isinstance(st, bytes): st = st.decode("utf-8")

                if st in ("new", "acknowledged"):
                    subj = fields[1]
                    if isinstance(subj, bytes): subj = subj.decode("utf-8")
                    sys_name = fields[2]
                    if isinstance(sys_name, bytes): sys_name = sys_name.decode("utf-8")
                    created_at_str = fields[3]
                    if isinstance(created_at_str, bytes): created_at_str = created_at_str.decode("utf-8")

                    main_msg = fields[4] if len(fields) > 4 and fields[4] else None
                    if isinstance(main_msg, bytes): main_msg = main_msg.decode("utf-8")
                    if main_msg and main_msg.strip():
                        subj = main_msg

                    try:
                        dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        age_days = (datetime.utcnow().replace(tzinfo=pytz.UTC) - dt.replace(tzinfo=pytz.UTC)).days
                    except:
                        age_days = "?"

                    open_alerts.append({"id": aid_str, "subject": subj, "system_name": sys_name, "age": age_days})

        # Format message
        tz = pytz.timezone(DAILY_SUMMARY_TIMEZONE)
        local_time = datetime.now(tz).strftime("%Y-%m-%d")

        local_time_safe = local_time.replace("-", "\\-")
        header = f"📊 *Daily AlertFlow Summary* \\({local_time_safe}\\)\n\n"

        metrics = redis_client.hgetall("metrics:processor")
        processed = int(metrics.get(b"processed", metrics.get("processed", 0)))
        errors = int(metrics.get(b"errors", metrics.get("errors", 0)))

        header += f"✅ *Total Processed \\(All Time\\):* {processed}\n"
        header += f"❌ *Total Errors \\(All Time\\):* {errors}\n"
        header += f"⚠️ *Pending Unresolved Alerts:* {len(open_alerts)}\n\n"

        messages_to_send = []

        if not open_alerts:
            msg = header + "🎉 _No pending alerts! Great job!_"
            messages_to_send.append(msg)
        else:
            header += "🚨 *Action Required \\(Grouped by System\\):*\n\n"
            msg = header

            from collections import defaultdict
            grouped = defaultdict(lambda: defaultdict(int))
            for a in open_alerts:
                sys_str = a.get('system_name') or "Unknown"
                subj_str = a.get('subject') or "No Subject"
                if len(subj_str) > 60:
                    subj_str = subj_str[:57] + "..."
                grouped[sys_str][subj_str] += 1

            for sys_name, subjects in sorted(grouped.items(), key=lambda x: sum(x[1].values()), reverse=True):
                total_sys_alerts = sum(subjects.values())
                safe_sys = escape_md_v2(sys_name)
                sys_block = f"🏢 *{safe_sys}* \\({total_sys_alerts} alerts\\)\n"

                for subj, count in sorted(subjects.items(), key=lambda x: x[1], reverse=True)[:5]:
                    safe_subj = escape_md_v2(subj)
                    sys_block += f"  • {safe_subj} \\({count}x\\)\n"

                if len(subjects) > 5:
                    sys_block += f"  • _\\+ {len(subjects) - 5} other issues_\n"

                sys_block += "\n"

                if len(msg) + len(sys_block) > 3800:
                    messages_to_send.append(msg)
                    msg = escape_md_v2("📊 Daily AlertFlow Summary (Continued)") + "\n\n" + sys_block
                else:
                    msg += sys_block

            if msg and msg not in messages_to_send:
                messages_to_send.append(msg)

        # Route daily summary using the global routing engine
        # Treat the sender as "system_summary" so users can create rules matching "system_summary"
        from routing import get_routing_targets

        rules = get_routing_rules()
        routing = get_routing_targets(
            sender_email="system_summary",
            rules=rules,
            default_tg_chat=TELEGRAM_DEFAULT_CHAT_ID,
            default_tg_thread=TELEGRAM_DEFAULT_THREAD_ID,
            default_mx_room=MATRIX_DEFAULT_ROOM_ID,
            default_channel=DEFAULT_NOTIFICATION_CHANNEL,
            recipient_emails=[]
        )

        channel_ids = routing.get("notification_channel_ids", [])
        channel_overrides = routing.get("channel_overrides", {})

        if not channel_ids:
            # Fallback to defaults if no channels configured globally
            logger.warning("No notification channels configured for summary. It will be skipped.")
        else:
            for i, msg in enumerate(messages_to_send):
                success, dest_str, _, _ = dispatch_dynamic_alert(
                    telegram_text=msg,
                    matrix_text=msg,
                    channel_ids=channel_ids,
                    overrides=channel_overrides,
                    action="SUMMARY"
                )
                if success:
                    logger.info(f"Daily summary part {i+1}/{len(messages_to_send)} sent to: {dest_str}")
                else:
                    logger.error(f"Failed to send daily summary part {i+1}.")

                if i < len(messages_to_send) - 1:
                    time.sleep(2)

    except Exception as e:
        logger.error(f"Error generating daily summary: {e}")

def _open_incident_snapshot() -> list:
    incidents = []
    for index_key in redis_client.scan_iter(match="open_incidents:*"):
        for incident_key in redis_client.smembers(index_key) or set():
            raw = redis_client.get(f"incident:{incident_key}")
            if not raw:
                continue
            state = json.loads(raw)
            if state.get("status") != "OPEN":
                continue
            state["incident_key"] = incident_key
            incidents.append(state)
    latest = {}
    alert_ids = redis_client.zrevrange("alerts:index", 0, 9999)
    if alert_ids:
        pipe = redis_client.pipeline(transaction=False)
        for alert_id in alert_ids:
            pipe.hmget(f"alert:{alert_id}", "incident_key", "severity", "status", "system_name", "created_at")
        for fields in pipe.execute():
            if fields and fields[0] and fields[0] not in latest:
                latest[fields[0]] = {"severity": fields[1], "alert_status": fields[2], "system_name": fields[3], "created_at": fields[4]}
    for incident in incidents:
        incident.update(latest.get(incident["incident_key"], {}))
    return incidents


def get_summary_delivery_targets(sender: str = "system_summary") -> tuple:
    routing = get_routing_targets(
        sender, get_routing_rules(), TELEGRAM_DEFAULT_CHAT_ID, TELEGRAM_DEFAULT_THREAD_ID,
        MATRIX_DEFAULT_ROOM_ID, DEFAULT_NOTIFICATION_CHANNEL, recipient_emails=[],
    )
    channel_ids = routing.get("notification_channel_ids", []) or get_default_notification_channel_ids()
    overrides = dict(routing.get("channel_overrides", {}) or {})
    settings = redis_client.hgetall("settings:general") or {}
    summary_chat = settings.get("summary_telegram_chat_id", "")
    summary_thread = settings.get("summary_telegram_thread_id", "0")
    if summary_chat:
        for channel_id in channel_ids:
            if get_channel_config(channel_id).get("type") == "telegram":
                overrides[channel_id] = {
                    **overrides.get(channel_id, {}),
                    "chat_id": summary_chat,
                    "thread_id": summary_thread,
                }
    return channel_ids, overrides


def generate_daily_summary():
    """Send an incident-centric operational report instead of an alert counter dump."""
    try:
        settings = get_runtime_summary_settings()
        now = time.time()
        incidents = _open_incident_snapshot()
        priority = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        incidents.sort(key=lambda item: (priority.get(str(item.get("severity", "")).lower(), 5), item.get("first_seen", now)))
        stale = [item for item in incidents if now - float(item.get("first_seen", now)) >= settings["sla_minutes"] * 60]
        recent_cutoff = now - 86400
        new_incidents_24h = set()
        resolved_incidents_24h = set()
        for alert_id in redis_client.zrangebyscore("alerts:index", recent_cutoff, now):
            action, incident_key = redis_client.hmget(f"alert:{alert_id}", "correlation_action", "incident_key")
            if action == "NEW" and incident_key:
                new_incidents_24h.add(incident_key)
            if action in {"RESOLVE", "ORPHAN_RESOLVE"} and incident_key:
                resolved_incidents_24h.add(incident_key)
        new_24h = len(new_incidents_24h)
        resolved_24h = len(resolved_incidents_24h)
        partial_delivery_24h = 0
        not_delivered_24h = 0
        for alert_id in redis_client.zrangebyscore("alerts:index", recent_cutoff, now):
            statuses = []
            for raw in (redis_client.hgetall(f"delivery:{alert_id}") or {}).values():
                try:
                    statuses.append(json.loads(raw).get("status", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
            if statuses and "delivered" in statuses and any(value != "delivered" for value in statuses):
                partial_delivery_24h += 1
            elif statuses and all(value != "delivered" for value in statuses):
                not_delivered_24h += 1
        dlq_items = []
        for raw in redis_client.lrange(REDIS_DLQ, 0, -1):
            try:
                dlq_items.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        active_dlq = sum(not retry_is_superseded(item) for item in dlq_items)
        superseded_dlq = len(dlq_items) - active_dlq
        metrics = redis_client.hgetall("metrics:processor") or {}
        metrics_24h = get_rolling_processor_metrics(1)
        ingestion_24h = redis_client.hgetall(f"metrics:ingestion:daily:{datetime.utcnow().strftime('%Y-%m-%d')}") or {}
        smtp_accepted = int(ingestion_24h.get("smtp_accepted", 0) or 0)
        smtp_processed = int(ingestion_24h.get("processor_received_smtp", 0) or 0)
        self_health = redis_client.hgetall("metrics:self_monitor") or {}
        date_text = datetime.now(pytz.timezone(DAILY_SUMMARY_TIMEZONE)).strftime("%Y-%m-%d")
        lines = [
            f"📊 *Daily AlertFlow Operational Summary* \\({escape_md_v2(date_text)}\\)", "",
            f"🔥 *Active incidents:* {len(incidents)}",
            f"🆕 *New \\(24h\\):* {new_24h}", f"✅ *Resolved \\(24h\\):* {resolved_24h}",
            f"⏱ *Outside SLA \\({settings['sla_minutes']}m\\):* {len(stale)}",
            f"🌊 *Storm messages suppressed \\(24h\\):* {metrics_24h.get('storm_suppressed', 0)}", "",
        ]
        if incidents:
            lines.append("🚨 *Highest priority incidents:*")
            for index, item in enumerate(incidents[:5], 1):
                age_minutes = max(0, int((now - float(item.get("first_seen", now))) / 60))
                resources = item.get("target_resources", []) or [item.get("target_resource", "unknown")]
                resource_text = ", ".join(str(value) for value in resources[:4])
                omitted = int(item.get("omitted_resource_count", 0) or 0) + max(0, len(resources) - 4)
                if omitted:
                    resource_text += f" (+{omitted} more)"
                summary = item.get("latest_main_message") or item.get("subject", "Unknown incident")
                lines.extend([
                    f"{index}\\. *{escape_md_v2(str(item.get('severity', 'Unknown')).upper())}* — {escape_md_v2(str(summary)[:180])}",
                    f"   Resources: {escape_md_v2(resource_text)}",
                    f"   Open: {age_minutes}m · Occurrences: {int(item.get('occurrences', 1))} · Status: {escape_md_v2(item.get('alert_status', 'new'))}",
                ])
        else:
            lines.append("🎉 _No active incidents\\._")
        noisy = sorted(incidents, key=lambda item: int(item.get("occurrences", 1)), reverse=True)[:3]
        if noisy:
            lines.extend(["", "📣 *Noisiest active incidents:*"])
            for item in noisy:
                lines.append(
                    f"• {escape_md_v2(str(item.get('subject', 'Unknown'))[:100])} "
                    f"\\({int(item.get('occurrences', 1))}x\\)"
                )
        lines.extend(["", "🩺 *AlertFlow health:*",
            f"• AI chain: {escape_md_v2(self_health.get('ai_chain_status', 'unknown'))}",
            f"• Fallback canary: {escape_md_v2(self_health.get('fallback_canary_status', 'unknown'))} "
            f"\\({escape_md_v2(self_health.get('fallback_canary_provider', 'not configured') or 'not configured')}\\)",
            f"• Loki / Alloy: {escape_md_v2(self_health.get('loki_status', 'unknown'))} / {escape_md_v2(self_health.get('alloy_status', 'unknown'))}",
            f"• Delivery failures \\(24h / lifetime\\): {metrics_24h.get('delivery_failures', 0)} / {int(metrics.get('delivery_failures', 0) or 0)}",
            f"• Partial / missed delivery \\(24h\\): {partial_delivery_24h} / {not_delivered_24h}",
            f"• Active / superseded DLQ: {active_dlq} / {superseded_dlq}",
            f"• Superseded retries \\(24h\\): {metrics_24h.get('retries_superseded', 0)}",
            f"• SMTP accepted / processed today: {smtp_accepted} / {smtp_processed}",
        ])
        if stale or active_dlq or not_delivered_24h or smtp_processed < smtp_accepted:
            actions = []
            if stale:
                actions.append(f"Review {len(stale)} incident\\(s\\) outside SLA")
            if active_dlq:
                actions.append(f"Review {active_dlq} active DLQ item\\(s\\)")
            if not_delivered_24h:
                actions.append(f"Investigate {not_delivered_24h} alert\\(s\\) with no successful delivery")
            if smtp_processed < smtp_accepted:
                actions.append(f"Reconcile {smtp_accepted - smtp_processed} accepted SMTP item\\(s\\) not yet processed")
            lines.extend(["", "👉 *Action required:*"] + [f"• {item}\\." for item in actions])
        message = join_markdown_lines(lines)
        channel_ids, overrides = get_summary_delivery_targets()
        success, destination, _, _ = dispatch_dynamic_alert(message, message.replace("\\", ""), channel_ids, overrides, action="SUMMARY")
        logger.info("Daily incident summary sent: %s (%s)", success, destination)
        return bool(success)
    except Exception as exc:
        logger.error("Incident summary generation failed: %s", exc, exc_info=True)
        return False


def get_rolling_processor_metrics(days: int = 1) -> dict:
    totals = {}
    for offset in range(days):
        day = datetime.utcfromtimestamp(time.time() - offset * 86400).strftime("%Y-%m-%d")
        for name, value in (redis_client.hgetall(f"metrics:processor:daily:{day}") or {}).items():
            totals[name] = totals.get(name, 0) + int(value or 0)
    return totals


def _format_storm_summary(final: bool = False) -> str:
    active = redis_client.hgetall("storm:global:active") or {}
    severities = redis_client.hgetall("storm:global:severity") or {}
    incidents = []
    for raw in (redis_client.hgetall("storm:global:incidents") or {}).values():
        try:
            incidents.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    incidents.sort(key=lambda item: (item.get("severity", "") != "Critical", -int(item.get("count", 0))))
    title = "✅ *Alert Storm Ended*" if final else "🚨 *Alert Storm Active*"
    lines = [title, "", f"Window events: {active.get('window_count', '0')}", f"Suppressed notifications: {active.get('suppressed', '0')}", f"Affected incidents: {len(incidents)}"]
    if severities:
        lines.append("Severity: " + " · ".join(f"{escape_md_v2(key)} {value}" for key, value in sorted(severities.items())))
    if incidents:
        lines.extend(["", "*Top affected incidents:*"])
        for item in incidents[:5]:
            resources = ", ".join(item.get("resources", [])[:3]) or "unknown"
            lines.append(f"• {escape_md_v2(item.get('severity', 'Unknown'))}: {escape_md_v2(item.get('subject', '')[:100])} \\({item.get('count', 0)}x\\)\n  `{escape_md_v2(resources)}`")
    lines.extend(["", "Critical new incidents and RESOLVED notifications continue to be delivered\\."])
    return join_markdown_lines(lines)


def storm_summary_loop():
    while True:
        try:
            active = redis_client.hgetall("storm:global:active") or {}
            if active:
                settings = get_runtime_summary_settings()
                now = time.time()
                last_event = float(active.get("last_event_at", now))
                last_summary = float(active.get("last_summary_at", 0) or 0)
                final = now - last_event > settings["window"]
                if final or now - last_summary >= settings["summary_interval"]:
                    message = _format_storm_summary(final)
                    channel_ids, overrides = get_summary_delivery_targets("storm_summary")
                    known = json.loads(active.get("message_ids", "{}") or "{}")
                    success, destination, new_ids, _ = dispatch_dynamic_alert(
                        message, message.replace("\\", ""), channel_ids, overrides,
                        action="UPDATE" if known else "NEW", known_message_ids=known,
                    )
                    if success:
                        known.update(new_ids)
                        redis_client.hset("storm:global:active", mapping={"last_summary_at": str(now), "message_ids": json.dumps(known)})
                        logger.info("Storm summary sent/updated: %s", destination)
                    if final and success:
                        redis_client.hincrby("metrics:processor", "storm_summaries_completed", 1)
                        redis_client.delete("storm:global:active", "storm:global:severity", "storm:global:incidents")
        except Exception as exc:
            logger.error("Storm summary loop failed: %s", exc)
        time.sleep(30)


def daily_summary_loop():
    logger.info(f"Starting daily summary scheduler for {DAILY_SUMMARY_TIME} {DAILY_SUMMARY_TIMEZONE}")
    while True:
        try:
            tz = pytz.timezone(DAILY_SUMMARY_TIMEZONE)
            now = datetime.now(tz)

            date_key = now.strftime("%Y-%m-%d")
            due = datetime.strptime(f"{date_key} {DAILY_SUMMARY_TIME}", "%Y-%m-%d %H:%M")
            due = tz.localize(due)
            sent_key = f"summary:daily:sent:{date_key}"
            lock_key = f"summary:daily:lock:{date_key}"
            if now >= due and not redis_client.exists(sent_key) and redis_client.set(lock_key, REDIS_CONSUMER, nx=True, ex=300):
                if generate_daily_summary():
                    redis_client.set(sent_key, str(time.time()), ex=86400 * 8)
            time.sleep(30)
        except Exception as e:
            logger.error(f"Summary loop error: {e}")
            time.sleep(60)


def stale_incident_loop():
    """Periodically retire stale correlation candidates without resolving them."""
    time.sleep(60)
    while True:
        try:
            marked = IncidentTracker(redis_client).mark_stale_open_incidents(
                max_age_seconds=STALE_INCIDENT_HOURS * 3600
            )
            if marked:
                logger.info("Marked %s inactive incidents as STALE", marked)
                add_log("INFO", "Stale incident reconciliation complete", {"marked": marked})
        except Exception as exc:
            logger.error("Stale incident reconciliation failed: %s", exc)
        time.sleep(3600)

def main():
    global redis_client

    # Connect to Redis
    try:
        logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)
        redis_client.ping()
        try:
            redis_client.xgroup_create(
                REDIS_STREAM, REDIS_STREAM_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return

    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()

    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_data, daemon=True)
    cleanup_thread.start()

    # Start retry worker
    retry_thread = threading.Thread(target=retry_worker_loop, daemon=True)
    retry_thread.start()

    # Start daily summary worker
    summary_thread = threading.Thread(target=daily_summary_loop, daemon=True)
    summary_thread.start()

    storm_thread = threading.Thread(target=storm_summary_loop, daemon=True)
    storm_thread.start()

    stale_thread = threading.Thread(target=stale_incident_loop, daemon=True)
    stale_thread.start()

    self_monitor_thread = threading.Thread(target=self_monitor_loop, daemon=True)
    self_monitor_thread.start()

    logger.info("Starting Alert Processor...")
    logger.info(f"Default channel: {DEFAULT_NOTIFICATION_CHANNEL}")
    logger.info(f"Default Telegram: {TELEGRAM_DEFAULT_CHAT_ID or 'Not Set'}")
    logger.info(f"Default Matrix: {MATRIX_DEFAULT_ROOM_ID or 'Not Set'}")
    logger.info(f"Failover enabled: {FAILOVER_ENABLED}")

    add_log("INFO", "Alert Processor started")

    last_claim_check = 0.0
    while True:
        try:
            item = None
            stream_id = None

            # Reclaim a message abandoned by a dead consumer after 60 seconds.
            now = time.time()
            reclaim_abandoned = now - last_claim_check >= 30
            if reclaim_abandoned:
                last_claim_check = now
            stream_id, stream_payload = read_stream_message(redis_client, reclaim_abandoned)
            if stream_id:
                item = (REDIS_STREAM, stream_payload)

            # Drain legacy list messages created before the migration.
            if not item:
                item = redis_client.blpop(REDIS_QUEUE, timeout=1)

            # Operational alerts always have priority over historical backfill.
            if not item:
                backfill_payload = redis_client.lpop(REDIS_BACKFILL_QUEUE)
                if backfill_payload:
                    item = (REDIS_BACKFILL_QUEUE, backfill_payload)
            if item:
                queue_name, payload = item
                success, payload = process_message(payload)
                if not success:
                    # If process_message completely failed (exception), send to DLQ
                    logger.error(f"Message processing failed critically, moving to DLQ")
                    push_to_dlq(payload)
                    add_log("WARNING", "Message moved to DLQ (critical processing failure)")
                if stream_id:
                    redis_client.xack(REDIS_STREAM, REDIS_STREAM_GROUP, stream_id)
                    redis_client.xdel(REDIS_STREAM, stream_id)

        except redis.ConnectionError:
            logger.error("Redis connection lost, retrying in 5s...")
            add_log("ERROR", "Redis connection lost")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
