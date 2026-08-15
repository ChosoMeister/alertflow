"""
Redis Service - Data persistence and queue operations.
"""
import redis
import json
import time
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from config import get_settings

settings = get_settings()


class RedisService:
    def __init__(self):
        pool = redis.ConnectionPool(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            decode_responses=True,
            max_connections=20,
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        self.client = redis.Redis(connection_pool=pool)

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except:
            return False

    # ========================
    # Queue Operations
    # ========================

    def push_to_queue(self, data: Dict[str, Any]) -> str:
        """Publish a durable stream message and return its trace ID."""
        trace_id = str(uuid.uuid4())[:8]
        data["trace_id"] = trace_id
        data["queued_at"] = datetime.utcnow().isoformat()
        self.client.xadd(
            "alerts:stream",
            {"payload": json.dumps(data), "trace_id": trace_id},
            maxlen=100000,
            approximate=True,
        )
        return trace_id

    def get_queue_depth(self) -> int:
        return self.client.xlen("alerts:stream") + self.client.llen("alert_queue")

    def get_dlq_depth(self) -> int:
        return self.client.llen("alert_dead_letter_queue")

    def get_retry_queue_depth(self) -> int:
        return self.client.zcard("retry_queue")

    def get_stream_pending(self) -> int:
        try:
            return sum(int(group.get("pending", 0)) for group in self.client.xinfo_groups("alerts:stream"))
        except redis.ResponseError:
            return 0

    def get_dlq_items(self, limit: int = 50) -> list:
        """Get items from the Dead Letter Queue."""
        items = self.client.lrange("alert_dead_letter_queue", 0, limit - 1)
        result = []
        for i, item in enumerate(items):
            try:
                data = json.loads(item)
                incident_key = data.get("incident_key", "")
                lifecycle = self._classify_dlq_item(data)
                result.append({
                    "index": i,
                    "sender": data.get("from", data.get("sender", "")),
                    "subject": data.get("subject", ""),
                    "retry_count": data.get("retry_count", 0),
                    "scheduled_at": data.get("scheduled_at", ""),
                    "queued_at": data.get("queued_at", ""),
                    "failed_at": data.get("failed_at", ""),
                    "failure_reason": data.get("failure_reason", "maximum_retries_exhausted"),
                    "incident_key": incident_key,
                    "incident_revision": int(data.get("incident_revision", 0) or 0),
                    "channel_ids": data.get("notification_channel_ids", []),
                    **lifecycle,
                })
            except:
                result.append({"index": i, "sender": "parse_error", "subject": str(item)[:100]})
        return result

    def _classify_dlq_item(self, data: dict) -> dict:
        """Distinguish actionable failures from entries superseded by newer delivery."""
        incident_key = data.get("incident_key", "")
        if not incident_key:
            return {"lifecycle": "active", "incident_status": "unknown"}
        raw = self.client.get(f"incident:{incident_key}")
        if not raw:
            return {"lifecycle": "historical", "incident_status": "expired"}
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            return {"lifecycle": "active", "incident_status": "unknown"}
        required = list(data.get("notification_channel_ids", []) or [])
        latest = {}
        for _, fields in self.client.xrevrange(f"incident:events:{incident_key}", count=200):
            channel_id = fields.get("channel_id", "")
            if fields.get("action") == "DELIVERY" and channel_id and channel_id not in latest:
                latest[channel_id] = fields
        queued_revision = int(data.get("incident_revision", 0) or 0)
        current_revision = int(state.get("revision", 1) or 1)
        if required:
            recovered = all(latest.get(channel_id, {}).get("status") == "delivered" for channel_id in required)
        else:
            scheduled_at = str(data.get("scheduled_at", ""))
            recovered = any(
                event.get("status") == "delivered" and event.get("occurred_at", "") > scheduled_at
                for event in latest.values()
            )
        superseded = recovered and (not queued_revision or current_revision > queued_revision)
        return {
            "lifecycle": "superseded" if superseded else "active",
            "incident_status": str(state.get("status", "unknown")).lower(),
            "current_incident_revision": current_revision,
        }

    def get_dlq_lifecycle_counts(self) -> Dict[str, int]:
        counts = {"active": 0, "superseded": 0, "historical": 0}
        for item in self.get_dlq_items(limit=1000):
            lifecycle = item.get("lifecycle", "active")
            counts[lifecycle] = counts.get(lifecycle, 0) + 1
        return counts

    def get_retry_queue_items(self, limit: int = 50) -> list:
        """Get items from the retry queue with their scores (next retry timestamp)."""
        items = self.client.zrange("retry_queue", 0, limit - 1, withscores=True)
        result = []
        for item_json, score in items:
            try:
                data = json.loads(item_json)
                result.append({
                    "sender": data.get("sender", ""),
                    "subject": data.get("subject", ""),
                    "retry_count": data.get("retry_count", 0),
                    "next_retry_at": datetime.utcfromtimestamp(score).isoformat(),
                    "channel": data.get("channel", ""),
                })
            except:
                result.append({"sender": "parse_error", "subject": str(item_json)[:100]})
        return result

    def flush_dlq(self) -> int:
        """Remove all items from DLQ. Returns count of removed items."""
        count = self.client.llen("alert_dead_letter_queue")
        self.client.delete("alert_dead_letter_queue")
        return count

    def requeue_dlq_item(self, index: int) -> bool:
        """Move a DLQ item back to the main queue for reprocessing."""
        items = self.client.lrange("alert_dead_letter_queue", index, index)
        if not items:
            return False
        try:
            data = json.loads(items[0])
            if self._classify_dlq_item(data).get("lifecycle") != "active":
                return False
            # Get original payload if available, otherwise use the data itself
            original = data.get("original_payload")
            if original:
                self.client.xadd("alerts:stream", {"payload": original}, maxlen=100000, approximate=True)
            else:
                self.client.xadd("alerts:stream", {"payload": items[0]}, maxlen=100000, approximate=True)
            # Remove from DLQ (mark and clean approach)
            self.client.lset("alert_dead_letter_queue", index, "__REMOVED__")
            self.client.lrem("alert_dead_letter_queue", 1, "__REMOVED__")
            if data.get("dlq_dedupe_key"):
                self.client.delete(data["dlq_dedupe_key"])
            return True
        except:
            return False
    # ========================
    # Routing Rules
    # ========================


    def add_routing_rule(self, rule_data: Dict[str, Any]) -> str:
        """Add a routing rule and return its ID."""
        rule_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()

        rule = {
            "id": rule_id,
            "name": rule_data.get("name", ""),
            "enabled": str(rule_data.get("enabled", True)).lower(),
            "priority": str(rule_data.get("priority", 0)),
            "match_field": rule_data.get("match_field", "from"),
            "email_pattern": rule_data.get("email_pattern", ""),
            "notes": rule_data.get("notes", ""),
            "ai_provider_id": rule_data.get("ai_provider_id", "") or "",
            "alert_destination_ids": json.dumps(rule_data.get("alert_destination_ids", [])),
            "resolved_destination_ids": json.dumps(rule_data.get("resolved_destination_ids", [])),
            "severity_destination_ids": json.dumps(rule_data.get("severity_destination_ids", {})),
            "resolution_mode": rule_data.get("resolution_mode", "legacy") or "legacy",
            "created_at": now,
            "updated_at": now,
        }

        self.client.hset(f"routing_rule:{rule_id}", mapping=rule)
        self.client.sadd("routing_rules:index", rule_id)

        return rule_id

    def update_routing_rule(self, rule_id: str, rule_data: Dict[str, Any]) -> bool:
        """Update an existing routing rule."""
        if not self.client.exists(f"routing_rule:{rule_id}"):
            return False

        updates = {
            "name": rule_data.get("name", ""),
            "enabled": str(rule_data.get("enabled", True)).lower(),
            "priority": str(rule_data.get("priority", 0)),
            "match_field": rule_data.get("match_field", "from"),
            "email_pattern": rule_data.get("email_pattern", ""),
            "notes": rule_data.get("notes", ""),
            "ai_provider_id": rule_data.get("ai_provider_id", "") or "",
            "alert_destination_ids": json.dumps(rule_data.get("alert_destination_ids", [])),
            "resolved_destination_ids": json.dumps(rule_data.get("resolved_destination_ids", [])),
            "severity_destination_ids": json.dumps(rule_data.get("severity_destination_ids", {})),
            "resolution_mode": rule_data.get("resolution_mode", "legacy") or "legacy",
            "updated_at": datetime.utcnow().isoformat(),
        }

        self.client.hset(f"routing_rule:{rule_id}", mapping=updates)
        return True

    def get_routing_rule(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Get a routing rule by ID."""
        rule = self.client.hgetall(f"routing_rule:{rule_id}")
        if rule:
            rule = self._normalize_routing_rule(rule)
        return rule if rule else None

    def list_routing_rules(self) -> List[Dict[str, Any]]:
        """List all routing rules (pipelined)."""
        rule_ids = list(self.client.smembers("routing_rules:index") or set())
        if not rule_ids:
            return []
        pipe = self.client.pipeline(transaction=False)
        for rid in rule_ids:
            pipe.hgetall(f"routing_rule:{rid}")
        results = pipe.execute()
        rules = []
        for rule in results:
            if rule:
                rule = self._normalize_routing_rule(rule)
                rules.append(rule)
        return sorted(rules, key=lambda r: r.get("priority", 0))

    def delete_routing_rule(self, rule_id: str) -> bool:
        """Delete a routing rule."""
        if not self.client.exists(f"routing_rule:{rule_id}"):
            return False
        self.client.delete(f"routing_rule:{rule_id}")
        self.client.srem("routing_rules:index", rule_id)
        return True

    def _normalize_routing_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize routing rule data types."""
        if not rule:
            return None
        rule["enabled"] = rule.get("enabled", "true").lower() == "true"
        rule["priority"] = int(rule.get("priority", 0))
        rule["ai_provider_id"] = rule.get("ai_provider_id", "") or None
        rule["resolution_mode"] = rule.get("resolution_mode", "legacy") or "legacy"
        for field in ("alert_destination_ids", "resolved_destination_ids"):
            try:
                rule[field] = json.loads(rule.get(field, "[]") or "[]")
            except (TypeError, json.JSONDecodeError):
                rule[field] = []
        try:
            rule["severity_destination_ids"] = json.loads(rule.get("severity_destination_ids", "{}") or "{}")
        except (TypeError, json.JSONDecodeError):
            rule["severity_destination_ids"] = {}

        return rule

    # ========================
    # Resolution Profiles
    # ========================

    def add_resolution_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        profile_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        profile = {
            "id": profile_id,
            "name": profile_data.get("name", ""),
            "enabled": str(profile_data.get("enabled", True)).lower(),
            "notification_channel_ids": json.dumps(profile_data.get("notification_channel_ids", [])),
            "channel_overrides": json.dumps(profile_data.get("channel_overrides", {})),
            "notes": profile_data.get("notes", ""),
            "created_at": now,
            "updated_at": now,
        }
        self.client.hset(f"resolution_profile:{profile_id}", mapping=profile)
        self.client.sadd("resolution_profiles:index", profile_id)
        return self.get_resolution_profile(profile_id)

    def _normalize_resolution_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        if not profile:
            return None
        profile["enabled"] = profile.get("enabled", "true").lower() == "true"
        for field, fallback in (("notification_channel_ids", []), ("channel_overrides", {})):
            try:
                profile[field] = json.loads(profile.get(field) or json.dumps(fallback))
            except (TypeError, json.JSONDecodeError):
                profile[field] = fallback
        return profile

    def get_resolution_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        return self._normalize_resolution_profile(
            self.client.hgetall(f"resolution_profile:{profile_id}")
        )

    def list_resolution_profiles(self) -> List[Dict[str, Any]]:
        ids = sorted(self.client.smembers("resolution_profiles:index") or set())
        if not ids:
            return []
        pipe = self.client.pipeline(transaction=False)
        for profile_id in ids:
            pipe.hgetall(f"resolution_profile:{profile_id}")
        rules = self.list_routing_rules()
        usage = {}
        for rule in rules:
            profile_id = rule.get("resolution_profile_id")
            if profile_id:
                usage[profile_id] = usage.get(profile_id, 0) + 1
        profiles = []
        for raw in pipe.execute():
            profile = self._normalize_resolution_profile(raw)
            if profile:
                profile["rule_count"] = usage.get(profile["id"], 0)
                profiles.append(profile)
        return sorted(profiles, key=lambda item: item.get("name", "").lower())

    def update_resolution_profile(self, profile_id: str, profile_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = f"resolution_profile:{profile_id}"
        if not self.client.exists(key):
            return None
        self.client.hset(key, mapping={
            "name": profile_data.get("name", ""),
            "enabled": str(profile_data.get("enabled", True)).lower(),
            "notification_channel_ids": json.dumps(profile_data.get("notification_channel_ids", [])),
            "channel_overrides": json.dumps(profile_data.get("channel_overrides", {})),
            "notes": profile_data.get("notes", ""),
            "updated_at": datetime.utcnow().isoformat(),
        })
        return self.get_resolution_profile(profile_id)

    def delete_resolution_profile(self, profile_id: str) -> bool:
        if any(rule.get("resolution_profile_id") == profile_id for rule in self.list_routing_rules()):
            return False
        key = f"resolution_profile:{profile_id}"
        if not self.client.exists(key):
            return False
        self.client.delete(key)
        self.client.srem("resolution_profiles:index", profile_id)
        return True

    # ========================
    # Alerts
    # ========================

    def save_alert(self, alert_data: Dict[str, Any]) -> str:
        """Save a new alert and return its ID."""
        alert_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()

        alert = {
            "id": alert_id,
            "from_email": alert_data.get("from_email", alert_data.get("from", "")),
            "to_email": alert_data.get("to_email", alert_data.get("to", "")),
            "subject": alert_data.get("subject", ""),
            "body": alert_data.get("body", alert_data.get("text", "")),
            "html": alert_data.get("html", ""),
            "channel": alert_data.get("channel", "both"),
            "status": "new",
            "severity": "",
            "category": "",
            "confidence": "",
            "system_name": "",
            "main_message": "",
            "details": "",
            "ai_raw": "",
            "created_at": now,
            "updated_at": now,
        }

        self.client.hset(f"alert:{alert_id}", mapping=alert)
        score = time.time()
        self.client.zadd("alerts:index", {alert_id: score})
        self.client.zadd("alerts:status:new", {alert_id: score})
        self.client.zadd("alerts:severity:unclassified", {alert_id: score})
        self.client.zadd("alerts:category:unclassified", {alert_id: score})

        return alert_id

    def update_alert_ai(self, alert_id: str, ai_result: Dict[str, Any]) -> bool:
        """Update alert with AI analysis results."""
        if not self.client.exists(f"alert:{alert_id}"):
            return False

        analysis = ai_result.get("analysis", {})
        updates = {
            "severity": analysis.get("severity", ""),
            "category": analysis.get("category", ""),
            "confidence": str(analysis.get("confidence", "")),
            "model_confidence": str(analysis.get("model_confidence", analysis.get("confidence", ""))),
            "evidence_confidence": str(analysis.get("evidence_confidence", analysis.get("confidence", ""))),
            "evidence_status": analysis.get("evidence_status", "unknown"),
            "validation_warnings": json.dumps(analysis.get("validation_warnings", [])),
            "taxonomy_overrides": json.dumps(analysis.get("taxonomy_overrides", [])),
            "event_state": analysis.get("event_state", ""),
            "incident_severity": analysis.get("incident_severity", analysis.get("severity", "")),
            "system_name": analysis.get("system_name", ""),
            "main_message": analysis.get("main_message", ""),
            "details": analysis.get("details", ""),
            "ai_raw": json.dumps(ai_result),
            "updated_at": datetime.utcnow().isoformat(),
        }

        self.client.hset(f"alert:{alert_id}", mapping=updates)
        return True

    def update_alert_status(self, alert_id: str, status: str) -> bool:
        """Update alert status."""
        alert = self.client.hgetall(f"alert:{alert_id}")
        if not alert:
            return False

        if alert.get("system_resolved") == "true":
            # Cannot manually update status of system-resolved alerts
            return False

        old_status = alert.get("status", "new").lower()
        score = self.client.zscore("alerts:index", alert_id) or time.time()
        self.client.hset(f"alert:{alert_id}", "status", status)
        self.client.hset(f"alert:{alert_id}", "updated_at", datetime.utcnow().isoformat())
        self.client.zrem(f"alerts:status:{old_status}", alert_id)
        self.client.zadd(f"alerts:status:{status.lower()}", {alert_id: score})
        return True

    def get_alert(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Get a single alert by ID."""
        alert = self.client.hgetall(f"alert:{alert_id}")
        if not alert:
            return alert
        delivery = {}
        for channel_id, value in self.client.hgetall(f"delivery:{alert_id}").items():
            try:
                delivery[channel_id] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                delivery[channel_id] = {"status": "unknown"}
        alert["delivery"] = delivery
        return alert

    def list_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        q: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List alerts using sorted indexes; text search scans bounded chunks."""
        temporary_keys = []
        candidate_key = "alerts:index"

        if status:
            if status == "open":
                open_key = f"alerts:tmp:{uuid.uuid4().hex}"
                self.client.zunionstore(open_key, [
                    "alerts:status:new", "alerts:status:acknowledged", "alerts:status:duplicate"
                ], aggregate="MAX")
                self.client.expire(open_key, 60)
                temporary_keys.append(open_key)
                candidate_key = open_key
            else:
                candidate_key = f"alerts:status:{status.lower()}"

        if severity:
            severity_key = f"alerts:severity:{severity.lower()}"
            if candidate_key == "alerts:index" and not status:
                candidate_key = severity_key
            else:
                intersection_key = f"alerts:tmp:{uuid.uuid4().hex}"
                self.client.zinterstore(intersection_key, [candidate_key, severity_key], aggregate="MAX")
                self.client.expire(intersection_key, 60)
                temporary_keys.append(intersection_key)
                candidate_key = intersection_key

        q_lower = q.lower() if q else None
        if not q_lower:
            alert_ids = self.client.zrevrange(candidate_key, offset, offset + limit - 1)
            if not alert_ids:
                return []
            pipe = self.client.pipeline(transaction=False)
            for alert_id in alert_ids:
                pipe.hgetall(f"alert:{alert_id}")
            return [alert for alert in pipe.execute() if alert]

        alerts = []
        matched_seen = 0
        cursor = 0
        chunk_size = 200
        while len(alerts) < limit:
            alert_ids = self.client.zrevrange(candidate_key, cursor, cursor + chunk_size - 1)
            if not alert_ids:
                break
            pipe = self.client.pipeline(transaction=False)
            for alert_id in alert_ids:
                pipe.hgetall(f"alert:{alert_id}")
            for alert in pipe.execute():
                if not alert:
                    continue
                searchable = " ".join([
                    alert.get("subject", ""), alert.get("system_name", ""),
                    alert.get("main_message", ""), alert.get("body", ""),
                    alert.get("from_email", ""), alert.get("category", ""),
                    alert.get("details", ""),
                ]).lower()
                if q_lower not in searchable:
                    continue
                if matched_seen < offset:
                    matched_seen += 1
                    continue
                alerts.append(alert)
                if len(alerts) >= limit:
                    break
            cursor += len(alert_ids)
        return alerts

    def count_alerts(self) -> int:
        return self.client.zcard("alerts:index")

    # ========================
    # Heartbeats & Health
    # ========================

    def set_heartbeat(self, service: str, status: str = "ok"):
        """Set heartbeat for a service (TTL 15s)."""
        data = json.dumps({"timestamp": time.time(), "status": status})
        self.client.setex(f"heartbeat:{service}", 15, data)

    def get_heartbeat(self, service: str) -> Optional[Dict[str, Any]]:
        """Get heartbeat for a service."""
        data = self.client.get(f"heartbeat:{service}")
        if data:
            return json.loads(data)
        return None

    def check_service_health(self, service: str) -> str:
        """Check if service heartbeat is recent."""
        hb = self.get_heartbeat(service)
        if not hb:
            return "offline"
        age = time.time() - hb.get("timestamp", 0)
        return "online" if age < 20 else "stale"

    # ========================
    # Metrics
    # ========================

    def increment_metric(self, metric: str, amount: int = 1):
        """Increment a metric counter."""
        self.client.hincrby("metrics:processor", metric, amount)

    def get_metrics(self) -> Dict[str, int]:
        """Get all metrics."""
        metrics = self.client.hgetall("metrics:processor") or {}
        result = {k: int(v) for k, v in metrics.items()}
        today = datetime.utcnow().strftime("%Y-%m-%d")
        daily = self.client.hgetall(f"metrics:processor:daily:{today}") or {}
        result.update({f"{k}_24h": int(v) for k, v in daily.items()})
        return result

    # ========================
    # Logs
    # ========================

    def add_log(self, level: str, service: str, message: str, data: Dict[str, Any] = None):
        """Add a structured log entry."""
        entry = {
            "level": level,
            "service": service,
            "message": message,
            "data": json.dumps(data or {}),
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.client.xadd("stream:logs", entry, maxlen=2000)

    def get_recent_logs(self, count: int = 100, service: str = None) -> List[Dict[str, Any]]:
        """Get recent logs from stream."""
        entries = self.client.xrevrange("stream:logs", count=count)
        logs = []
        for entry_id, data in entries:
            log_entry = {
                "id": entry_id,
                "level": data.get("level", ""),
                "service": data.get("service", ""),
                "message": data.get("message", ""),
                "timestamp": data.get("timestamp", ""),
            }
            if service and log_entry["service"] != service:
                continue
            logs.append(log_entry)
        return logs

    # ========================
    # Mutes
    # ========================

    def add_mute(self, mute_type: str, value: str):
        """Add a mute entry (from or domain)."""
        self.client.sadd(f"mute:{mute_type}", value.lower())

    def remove_mute(self, mute_type: str, value: str):
        """Remove a mute entry."""
        self.client.srem(f"mute:{mute_type}", value.lower())

    def list_mutes(self, mute_type: str) -> List[str]:
        """List all mutes of a type."""
        return list(self.client.smembers(f"mute:{mute_type}") or [])

    def is_muted(self, sender: str) -> bool:
        """Check if a sender is muted."""
        sender_lower = sender.lower()
        if self.client.sismember("mute:from", sender_lower):
            return True
        if "@" in sender_lower:
            domain = sender_lower.split("@")[1]
            if self.client.sismember("mute:domain", domain):
                return True
        return False

    # ========================
    # Relay Logs
    # ========================

    def add_relay_log(self, log_data: Dict[str, Any]):
        """Add a relay log entry with 7-day TTL."""
        log_data["id"] = str(uuid.uuid4())[:8]
        log_data["timestamp"] = datetime.utcnow().isoformat()
        self.client.zadd("relay_logs", {json.dumps(log_data): time.time()})
        # Trim logs older than 7 days
        week_ago = time.time() - (7 * 24 * 3600)
        self.client.zremrangebyscore("relay_logs", 0, week_ago)

    def get_relay_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent relay logs."""
        entries = self.client.zrevrange("relay_logs", 0, limit - 1)
        logs = []
        for entry in entries:
            try:
                logs.append(json.loads(entry))
            except:
                pass
        return logs

    # ========================
    # Config
    # ========================

    def get_config(self, key: str) -> Optional[str]:
        return self.client.hget("config:app", key)

    def set_config(self, key: str, value: str):
        self.client.hset("config:app", key, value)

    def get_all_config(self) -> Dict[str, str]:
        return self.client.hgetall("config:app") or {}

    # ========================
    # AI Providers
    # ========================

    def add_ai_provider(self, provider_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new AI provider."""
        provider_id = str(uuid.uuid4())[:8]

        provider = {
            "id": provider_id,
            "name": provider_data.get("name", ""),
            "type": provider_data.get("type", "ollama"),
            "base_url": provider_data.get("base_url", ""),
            "model": provider_data.get("model", ""),
            "api_key": provider_data.get("api_key", ""),
            "timeout": str(provider_data.get("timeout", 120)),
            "is_default": str(provider_data.get("is_default", False)).lower(),
            "is_fallback": str(provider_data.get("is_fallback", False)).lower(),
        }

        self.client.hset(f"ai_provider:{provider_id}", mapping=provider)
        self.client.sadd("ai_providers:index", provider_id)

        return self._normalize_provider(provider)

    def update_ai_provider(self, provider_id: str, provider_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an AI provider."""
        updates = {
            "name": provider_data.get("name", ""),
            "type": provider_data.get("type", "ollama"),
            "base_url": provider_data.get("base_url", ""),
            "model": provider_data.get("model", ""),
            "api_key": provider_data.get("api_key", ""),
            "timeout": str(provider_data.get("timeout", 120)),
            "is_default": str(provider_data.get("is_default", False)).lower(),
            "is_fallback": str(provider_data.get("is_fallback", False)).lower(),
        }
        self.client.hset(f"ai_provider:{provider_id}", mapping=updates)
        return self.get_ai_provider(provider_id)

    def get_ai_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """Get an AI provider by ID."""
        provider = self.client.hgetall(f"ai_provider:{provider_id}")
        return self._normalize_provider(provider) if provider else None

    def get_ai_providers(self) -> List[Dict[str, Any]]:
        """Get all AI providers (pipelined)."""
        provider_ids = list(self.client.smembers("ai_providers:index") or set())
        if not provider_ids:
            return []
        pipe = self.client.pipeline(transaction=False)
        for pid in provider_ids:
            pipe.hgetall(f"ai_provider:{pid}")
        results = pipe.execute()
        providers = []
        for provider in results:
            if provider:
                providers.append(self._normalize_provider(provider))
        return providers

    def delete_ai_provider(self, provider_id: str) -> bool:
        """Delete an AI provider."""
        if not self.client.exists(f"ai_provider:{provider_id}"):
            return False
        self.client.delete(f"ai_provider:{provider_id}")
        self.client.srem("ai_providers:index", provider_id)
        return True

    def unset_default_ai_provider(self):
        """Unset all default AI providers."""
        for pid in self.client.smembers("ai_providers:index") or set():
            self.client.hset(f"ai_provider:{pid}", "is_default", "false")

    def unset_fallback_ai_provider(self):
        """Unset all fallback AI providers."""
        for pid in self.client.smembers("ai_providers:index") or set():
            self.client.hset(f"ai_provider:{pid}", "is_fallback", "false")

    def get_default_ai_provider(self) -> Optional[Dict[str, Any]]:
        """Get the default AI provider."""
        for pid in self.client.smembers("ai_providers:index") or set():
            provider = self.client.hgetall(f"ai_provider:{pid}")
            if provider and provider.get("is_default", "false").lower() == "true":
                return self._normalize_provider(provider)
        return None

    def _normalize_provider(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize provider data types."""
        if not provider:
            return None
        provider["timeout"] = int(provider.get("timeout", 120))
        provider["is_default"] = provider.get("is_default", "false").lower() == "true"
        provider["is_fallback"] = provider.get("is_fallback", "false").lower() == "true"
        return provider

    # ========================
    # Notification Channels
    # ========================

    def add_notification_channel(self, channel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Add a new notification channel."""
        channel_id = str(uuid.uuid4())[:8]

        channel = {
            "id": channel_id,
            "name": channel_data.get("name", ""),
            "type": channel_data.get("type", "telegram"),
            "config": json.dumps(channel_data.get("config", {})),
            "is_default": str(channel_data.get("is_default", False)).lower(),
        }

        self.client.hset(f"notification_channel:{channel_id}", mapping=channel)
        self.client.sadd("notification_channels:index", channel_id)

        return self._normalize_channel(channel)

    def update_notification_channel(self, channel_id: str, channel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update a notification channel."""
        updates = {
            "name": channel_data.get("name", ""),
            "type": channel_data.get("type", "telegram"),
            "config": json.dumps(channel_data.get("config", {})),
            "is_default": str(channel_data.get("is_default", False)).lower(),
        }
        self.client.hset(f"notification_channel:{channel_id}", mapping=updates)
        return self.get_notification_channel(channel_id)

    def get_notification_channel(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get a notification channel by ID."""
        channel = self.client.hgetall(f"notification_channel:{channel_id}")
        return self._normalize_channel(channel) if channel else None

    def get_notification_channels(self) -> List[Dict[str, Any]]:
        """Get all notification channels (pipelined)."""
        channel_ids = list(self.client.smembers("notification_channels:index") or set())
        if not channel_ids:
            return []
        pipe = self.client.pipeline(transaction=False)
        for cid in channel_ids:
            pipe.hgetall(f"notification_channel:{cid}")
        results = pipe.execute()
        channels = []
        for channel in results:
            if channel:
                channels.append(self._normalize_channel(channel))
        return channels

    def delete_notification_channel(self, channel_id: str) -> bool:
        """Delete a notification channel."""
        if not self.client.exists(f"notification_channel:{channel_id}"):
            return False
        self.client.delete(f"notification_channel:{channel_id}")
        self.client.srem("notification_channels:index", channel_id)
        return True

    def unset_default_notification_channel(self):
        """Unset all default notification channels."""
        for cid in self.client.smembers("notification_channels:index") or set():
            self.client.hset(f"notification_channel:{cid}", "is_default", "false")

    def _normalize_channel(self, channel: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize channel data types."""
        if not channel:
            return None
        channel["is_default"] = channel.get("is_default", "false").lower() == "true"
        try:
            channel["config"] = json.loads(channel.get("config", "{}"))
        except:
            channel["config"] = {}
        return channel

    # ========================
    # Notification Destinations
    # ========================

    def add_notification_destination(self, data: Dict[str, Any]) -> Dict[str, Any]:
        destination_id = str(uuid.uuid4())[:8]
        now = datetime.utcnow().isoformat()
        item = {
            "id": destination_id, "name": data.get("name", ""),
            "channel_id": data.get("channel_id", ""), "type": data.get("type", ""),
            "target": json.dumps(data.get("target", {})),
            "enabled": str(data.get("enabled", True)).lower(),
            "created_at": now, "updated_at": now,
        }
        self.client.hset(f"notification_destination:{destination_id}", mapping=item)
        self.client.sadd("notification_destinations:index", destination_id)
        return self._normalize_destination(item)

    def _normalize_destination(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not item:
            return None
        item["enabled"] = item.get("enabled", "true").lower() == "true"
        try:
            item["target"] = json.loads(item.get("target", "{}") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["target"] = {}
        return item

    def get_notification_destination(self, destination_id: str) -> Optional[Dict[str, Any]]:
        return self._normalize_destination(self.client.hgetall(f"notification_destination:{destination_id}"))

    def get_notification_destinations(self) -> List[Dict[str, Any]]:
        ids = sorted(self.client.smembers("notification_destinations:index") or set())
        if not ids:
            return []
        pipe = self.client.pipeline(transaction=False)
        for destination_id in ids:
            pipe.hgetall(f"notification_destination:{destination_id}")
        return [self._normalize_destination(x) for x in pipe.execute() if x]

    def update_notification_destination(self, destination_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = f"notification_destination:{destination_id}"
        if not self.client.exists(key):
            return None
        self.client.hset(key, mapping={
            "name": data.get("name", ""), "channel_id": data.get("channel_id", ""),
            "type": data.get("type", ""), "target": json.dumps(data.get("target", {})),
            "enabled": str(data.get("enabled", True)).lower(), "updated_at": datetime.utcnow().isoformat(),
        })
        return self.get_notification_destination(destination_id)

    def destination_usage(self, destination_id: str) -> int:
        return sum(
            destination_id in (
                rule.get("alert_destination_ids", [])
                + rule.get("resolved_destination_ids", [])
                + [item for items in rule.get("severity_destination_ids", {}).values() for item in items]
            )
            for rule in self.list_routing_rules()
        )

    def delete_notification_destination(self, destination_id: str) -> bool:
        if self.destination_usage(destination_id):
            return False
        key = f"notification_destination:{destination_id}"
        if not self.client.exists(key):
            return False
        self.client.delete(key)
        self.client.srem("notification_destinations:index", destination_id)
        return True

    # ========================
    # Users (Authentication)
    # ========================

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get a user by username."""
        user = self.client.hgetall(f"user:{username}")
        return user if user else None

    def get_users(self) -> List[Dict[str, Any]]:
        """Get all users using index set (avoids KEYS command)."""
        usernames = list(self.client.smembers("users:index") or set())

        # Migration: if index is empty but users exist (legacy data), rebuild index
        if not usernames:
            self._migrate_users_index()
            usernames = list(self.client.smembers("users:index") or set())

        if not usernames:
            return []

        pipe = self.client.pipeline(transaction=False)
        for username in usernames:
            pipe.hgetall(f"user:{username}")
        results = pipe.execute()

        users = []
        for user in results:
            if user:
                user_safe = {
                    "username": user.get("username"),
                    "role": user.get("role", "operator"),
                }
                users.append(user_safe)
        return users

    def _migrate_users_index(self):
        """One-time migration: rebuild users:index from existing user:* keys using SCAN."""
        cursor = 0
        while True:
            cursor, keys = self.client.scan(cursor, match="user:*", count=100)
            for key in keys:
                username = key.replace("user:", "", 1)
                self.client.sadd("users:index", username)
            if cursor == 0:
                break

    def save_user(self, username: str, password_hash: str, role: str = "operator") -> bool:
        """Save or update a user."""
        user = {
            "username": username,
            "password_hash": password_hash,
            "role": role,
        }
        self.client.hset(f"user:{username}", mapping=user)
        self.client.sadd("users:index", username)
        return True

    def update_user_password(self, username: str, password_hash: str) -> bool:
        """Update a user's password."""
        if not self.client.exists(f"user:{username}"):
            return False
        self.client.hset(f"user:{username}", "password_hash", password_hash)
        return True

    def delete_user(self, username: str) -> bool:
        """Delete a user."""
        if not self.client.exists(f"user:{username}"):
            return False
        self.client.delete(f"user:{username}")
        self.client.srem("users:index", username)
        return True

    def has_any_users(self) -> bool:
        """Check if any users exist in Redis."""
        if self.client.scard("users:index") > 0:
            return True
        # Fallback: check with SCAN for legacy data (one-time)
        cursor, keys = self.client.scan(0, match="user:*", count=10)
        return len(keys) > 0


# Singleton instance
_redis_service: Optional[RedisService] = None


def get_redis_service() -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service
