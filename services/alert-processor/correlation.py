import re
import hashlib
import time
import json
import logging
import uuid

logger = logging.getLogger("CorrelationService")

class IncidentTracker:
    MAX_INCIDENT_RESOURCES = 12
    MAX_RESOURCE_LENGTH = 180

    def __init__(self, redis_client):
        self.redis = redis_client

    def generate_exact_hash(self, email_data):
        """Generates a fast hash to drop identical emails immediately."""
        sender = str(email_data.get("from", "")).strip()
        subject = str(email_data.get("subject", "")).strip()

        # Remove volatile timestamps from subject for exact deduplication
        subject_clean = re.sub(r'\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M', '', subject)

        body = str(email_data.get("text", email_data.get("html", "")))[:200].strip()

        raw_sig = f"{sender}::{subject_clean}::{body}"
        return hashlib.sha256(raw_sig.encode()).hexdigest()

    def _get_domain(self, sender):
        domain = sender.split('@')[-1].lower() if '@' in sender else sender.lower()
        return re.sub(r'[^a-z0-9\.]', '', domain)

    @staticmethod
    def _normalize_resources(resources):
        """Return stable, comparable resource identifiers from AI output."""
        if isinstance(resources, str):
            resources = [resources]
        normalized = []
        for resource in resources or []:
            value = re.sub(r'\s+', ' ', str(resource)).strip().lower()
            if value and value not in {"unknown", "n/a", "none"}:
                normalized.append(value)
        return sorted(set(normalized))

    def _resources_compatible(self, existing, incoming):
        """Reject correlation only when both sides are specific and disjoint."""
        old = set(self._normalize_resources(existing))
        new = set(self._normalize_resources(incoming))
        if not old or not new:
            return True
        return bool(old.intersection(new))

    def _cap_resources(self, resources):
        normalized = self._normalize_resources(resources)
        values = [value[:self.MAX_RESOURCE_LENGTH] for value in normalized[:self.MAX_INCIDENT_RESOURCES]]
        return values, max(0, len(normalized) - len(values))

    def _identity_registry_key(self, sender, correlation_key):
        return f"incident_identity:{self._get_domain(sender)}:{correlation_key}"

    def find_open_by_correlation_key(self, sender, correlation_key):
        if not correlation_key:
            return ""
        registry_key = self._identity_registry_key(sender, correlation_key)
        incident_id = self.redis.get(registry_key) or ""
        if not incident_id:
            return ""
        raw = self.redis.get(f"incident:{incident_id}")
        if not raw:
            self.redis.delete(registry_key)
            return ""
        state = json.loads(raw)
        if state.get("status") != "OPEN" or state.get("correlation_key") != correlation_key:
            self.redis.delete(registry_key)
            return ""
        return incident_id

    def get_similar_open_incidents(self, sender, subject, body="", limit=10):
        """
        Fetches open incidents for the sender's domain and returns the most textually similar ones
        based on the Subject and Body to optimize the AI's context window.
        """
        domain = self._get_domain(sender)
        open_list_key = f"open_incidents:{domain}"

        # Get all open incident UUIDs for this domain
        open_ids = self.redis.smembers(open_list_key)
        if not open_ids:
            return []

        candidates = []
        # Use both subject and a chunk of body for query words to catch specific resource names
        query_text = subject + " " + str(body)[:1000]
        query_words = set(re.findall(r'\w+', query_text.lower()))

        for inc_id_bytes in open_ids:
            inc_id = inc_id_bytes.decode('utf-8') if isinstance(inc_id_bytes, bytes) else str(inc_id_bytes)
            state_json = self.redis.get(f"incident:{inc_id}")
            if state_json:
                state = json.loads(state_json)
                if state.get("status") == "OPEN":
                    inc_subject = state.get("subject", "")
                    inc_target = state.get("target_resource", "")

                    # Target resource helps immensely if subject is generic (like kuma-inside)
                    inc_words = set(re.findall(r'\w+', (inc_subject + " " + inc_target).lower()))

                    # Calculate simple overlap score
                    overlap = len(query_words.intersection(inc_words))
                    candidates.append({
                        "id": inc_id,
                        "subject": inc_subject,
                        "target": inc_target,
                        "score": overlap,
                        "occurrences": state.get("occurrences", 1),
                        "resources": state.get("target_resources", []),
                        "main_message": state.get("latest_main_message", "")
                    })
                else:
                    # Clean up orphaned closed IDs just in case
                    self.redis.srem(open_list_key, inc_id)

        # Sort by similarity score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]

    def process_incident_state_ai(self, sender, subject, action, target_incident_id=None,
                                  target_resource="unknown", target_resources=None,
                                  main_message="", details=None, track_open=True,
                                  source_fingerprint="", correlation_key="",
                                  correlation_identity=""):
        """
        Handles the lifecycle based strictly on AI's output.
        action: "NEW" | "UPDATE" | "RESOLVE"
        Returns: {
            "action": "NEW" | "MERGE" | "RESOLVE" | "IGNORE",
            "incident_key": <uuid>,
            "message_ids": { "telegram_1234": "msg_99", ... }
        }
        """
        domain = self._get_domain(sender)
        open_list_key = f"open_incidents:{domain}"
        now = time.time()
        incoming_resources = self._normalize_resources(
            target_resources or ([target_resource] if target_resource else [])
        )
        stored_resources, omitted_resources = self._cap_resources(incoming_resources)

        # A recovery without a known target is evidence, not a new active outage.
        if action == "RESOLVE" and not target_incident_id:
            incident_key = str(uuid.uuid4())
            state = {
                "status": "ORPHAN_RESOLVED", "subject": subject,
                "target_resource": ", ".join(stored_resources) or target_resource,
                "target_resources": stored_resources, "omitted_resource_count": omitted_resources,
                "first_seen": now, "last_updated": now, "resolved_at": now,
                "occurrences": 1, "revision": 1, "channels": {}, "latest_main_message": main_message,
                "merge_occurrences": 0, "suppressed_occurrences": 0,
                "latest_details": details or [], "source_fingerprint": source_fingerprint,
                "history": [],
                "correlation_key": correlation_key,
                "correlation_identity": correlation_identity,
                "correlation_domain": domain,
            }
            self.redis.set(f"incident:{incident_key}", json.dumps(state), ex=86400 * 7)
            return {"action": "ORPHAN_RESOLVE", "incident_key": incident_key, "message_ids": {}, "revision": 1}

        # UPDATE still needs a concrete target; otherwise it is a new incident.
        if action == "UPDATE" and not target_incident_id:
            action = "NEW"

        if action == "NEW":
            incident_key = str(uuid.uuid4())
            redis_key = f"incident:{incident_key}"

            # Since this is the initial creation BEFORE dispatch, we save basic state.
            state = {
                "status": "OPEN" if track_open else "ANALYSIS_FAILED",
                "subject": subject,
                "target_resource": target_resource,
                "first_seen": now,
                "last_updated": now,
                "occurrences": 1,
                "merge_occurrences": 0,
                "suppressed_occurrences": 0,
                "revision": 1,
                "channels": {},
                "target_resources": stored_resources,
                "omitted_resource_count": omitted_resources,
                "latest_main_message": main_message,
                "latest_details": details or [],
                "source_fingerprint": source_fingerprint,
                "history": [],
                "correlation_key": correlation_key,
                "correlation_identity": correlation_identity,
                "correlation_domain": domain,
            }
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
            if track_open:
                self.redis.sadd(open_list_key, incident_key)
                if correlation_key:
                    self.redis.set(self._identity_registry_key(sender, correlation_key), incident_key, ex=86400 * 7)

            return {
                "action": "NEW",
                "incident_key": incident_key,
                "message_ids": {},
                "revision": 1,
            }

        elif action == "UPDATE":
            redis_key = f"incident:{target_incident_id}"
            state_json = self.redis.get(redis_key)

            if not state_json:
                # Target doesn't exist, fallback to NEW
                return self.process_incident_state_ai(
                    sender, subject, "NEW", target_resource=target_resource,
                    target_resources=incoming_resources, main_message=main_message,
                    details=details, source_fingerprint=source_fingerprint,
                    correlation_key=correlation_key, correlation_identity=correlation_identity,
                )

            state = json.loads(state_json)
            if state.get("status") != "OPEN":
                # Already closed, create NEW
                return self.process_incident_state_ai(
                    sender, subject, "NEW", target_resource=target_resource,
                    target_resources=incoming_resources, main_message=main_message,
                    details=details, source_fingerprint=source_fingerprint,
                    correlation_key=correlation_key, correlation_identity=correlation_identity,
                )

            same_identity = bool(correlation_key and state.get("correlation_key") == correlation_key)
            if not same_identity and not self._resources_compatible(state.get("target_resources", []), incoming_resources):
                logger.warning(
                    "Correlation target rejected for %s: existing=%s incoming=%s",
                    target_incident_id, state.get("target_resources", []), incoming_resources
                )
                return self.process_incident_state_ai(
                    sender, subject, "NEW", target_resource=target_resource,
                    target_resources=incoming_resources, main_message=main_message,
                    details=details, source_fingerprint=source_fingerprint,
                    correlation_key=correlation_key, correlation_identity=correlation_identity,
                )

            existing_fingerprint = state.get("source_fingerprint", "")
            if not same_identity and existing_fingerprint and source_fingerprint and existing_fingerprint != source_fingerprint:
                logger.warning(
                    "Correlation fingerprint rejected for %s: existing=%s incoming=%s",
                    target_incident_id, existing_fingerprint, source_fingerprint,
                )
                return self.process_incident_state_ai(
                    sender, subject, "NEW", target_resource=target_resource,
                    target_resources=incoming_resources, main_message=main_message,
                    details=details, source_fingerprint=source_fingerprint,
                    correlation_key=correlation_key, correlation_identity=correlation_identity,
                )

            # Valid UPDATE (MERGE)
            state["occurrences"] = state.get("occurrences", 1) + 1
            state["merge_occurrences"] = int(state.get("merge_occurrences", 0)) + 1
            state["revision"] = int(state.get("revision", 1)) + 1
            state["last_updated"] = now
            history = state.get("history", [])
            history.append({
                "at": now,
                "main_message": state.get("latest_main_message", ""),
                "target_resources": state.get("target_resources", []),
                "details": state.get("latest_details", [])
            })
            state["history"] = history[-10:]
            if incoming_resources:
                state["target_resources"] = stored_resources
                state["target_resource"] = ", ".join(stored_resources)
                state["omitted_resource_count"] = omitted_resources
            state["latest_main_message"] = main_message
            state["latest_details"] = details or []
            if source_fingerprint:
                state["source_fingerprint"] = source_fingerprint
            if correlation_key:
                state["correlation_key"] = correlation_key
                state["correlation_identity"] = correlation_identity
                state["correlation_domain"] = domain
                self.redis.set(self._identity_registry_key(sender, correlation_key), target_incident_id, ex=86400 * 7)
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)

            return {
                "action": "MERGE",
                "incident_key": target_incident_id,
                "message_ids": state.get("channels", {}),
                "occurrences": state["occurrences"],
                "revision": state["revision"],
                "original_text": state.get("current_telegram_text", state.get("original_telegram_text", "")),
                "first_seen": state.get("first_seen", now)
            }

        elif action == "RESOLVE":
            redis_key = f"incident:{target_incident_id}"
            state_json = self.redis.get(redis_key)

            if not state_json:
                return {"action": "IGNORE", "incident_key": target_incident_id, "message_ids": {}}

            state = json.loads(state_json)
            if state.get("status") == "CLOSED":
                return {"action": "IGNORE", "incident_key": target_incident_id, "message_ids": {}}

            # Valid RESOLVE
            state["status"] = "CLOSED"
            state["resolved_at"] = now
            state["revision"] = int(state.get("revision", 1)) + 1
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
            self.redis.srem(open_list_key, target_incident_id)
            correlation_key = state.get("correlation_key", "")
            if correlation_key:
                registry_key = self._identity_registry_key(sender, correlation_key)
                if self.redis.get(registry_key) == target_incident_id:
                    self.redis.delete(registry_key)

            return {
                "action": "RESOLVE",
                "incident_key": target_incident_id,
                "message_ids": state.get("channels", {}),
                "revision": state["revision"],
                "original_text": state.get("current_telegram_text", state.get("original_telegram_text", ""))
            }

        return {"action": "IGNORE", "incident_key": "", "message_ids": {}}

    def record_suppressed_occurrence(self, incident_key, detail="exact_duplicate"):
        """Count a suppressed exact duplicate without AI analysis or notification."""
        if not incident_key:
            return False
        redis_key = f"incident:{incident_key}"
        state_json = self.redis.get(redis_key)
        if not state_json:
            return False
        state = json.loads(state_json)
        if state.get("status") != "OPEN":
            return False
        now = time.time()
        state["occurrences"] = int(state.get("occurrences", 1)) + 1
        state["suppressed_occurrences"] = int(state.get("suppressed_occurrences", 0)) + 1
        state["last_updated"] = now
        state["last_suppressed_reason"] = detail
        self.redis.set(redis_key, json.dumps(state), ex=86400 * 7)
        correlation_key = state.get("correlation_key", "")
        correlation_domain = state.get("correlation_domain", "")
        if correlation_key and correlation_domain:
            self.redis.set(f"incident_identity:{correlation_domain}:{correlation_key}", incident_key, ex=86400 * 7)
        self.redis.xadd(f"incident:events:{incident_key}", {
            "action": "SUPPRESSED", "status": detail, "occurred_at": str(now),
        }, maxlen=1000, approximate=True)
        self.redis.expire(f"incident:events:{incident_key}", 86400 * 7)
        return True

    def save_message_ids(self, incident_key, channel_records, telegram_text=None):
        """
        Saves sent message IDs (e.g. from Telegram) into the incident so we can edit it later.
        """
        if not incident_key:
            return

        redis_key = f"incident:{incident_key}"
        state_json = self.redis.get(redis_key)

        if state_json:
            state = json.loads(state_json)
            channels = state.get("channels", {})
            channels.update(channel_records)
            state["channels"] = channels
            if telegram_text:
                state.setdefault("original_telegram_text", telegram_text)
                state["current_telegram_text"] = telegram_text
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
            correlation_key = state.get("correlation_key", "")
            correlation_domain = state.get("correlation_domain", "")
            if correlation_key and correlation_domain and state.get("status") == "OPEN":
                self.redis.set(f"incident_identity:{correlation_domain}:{correlation_key}", incident_key, ex=86400 * 7)

    def mark_stale_open_incidents(self, max_age_seconds=259200):
        """Remove inactive incidents from correlation without claiming resolution."""
        now = time.time()
        marked = 0
        for open_list_key in self.redis.scan_iter(match="open_incidents:*"):
            for incident_id in list(self.redis.smembers(open_list_key) or set()):
                state_json = self.redis.get(f"incident:{incident_id}")
                if not state_json:
                    self.redis.srem(open_list_key, incident_id)
                    continue
                state = json.loads(state_json)
                if state.get("status") != "OPEN":
                    self.redis.srem(open_list_key, incident_id)
                    continue
                last_seen = float(state.get("last_updated") or state.get("first_seen") or now)
                if now - last_seen < max_age_seconds:
                    continue
                state["status"] = "STALE"
                state["stale_at"] = now
                state["stale_reason"] = "no_update_within_policy"
                self.redis.set(f"incident:{incident_id}", json.dumps(state), ex=86400 * 7)
                self.redis.srem(open_list_key, incident_id)
                correlation_key = state.get("correlation_key", "")
                if correlation_key:
                    domain = str(open_list_key).split(":", 1)[-1]
                    registry_key = f"incident_identity:{domain}:{correlation_key}"
                    if self.redis.get(registry_key) == incident_id:
                        self.redis.delete(registry_key)
                marked += 1
        return marked
