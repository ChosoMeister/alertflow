import re
import hashlib
import time
import json
import logging
import uuid

logger = logging.getLogger("CorrelationService")

class IncidentTracker:
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
                        "occurrences": state.get("occurrences", 1)
                    })
                else:
                    # Clean up orphaned closed IDs just in case
                    self.redis.srem(open_list_key, inc_id)

        # Sort by similarity score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]

    def process_incident_state_ai(self, sender, subject, action, target_incident_id=None, target_resource="unknown"):
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

        # If AI says RESOLVE or UPDATE but gives no target, treat as NEW.
        if action in ["RESOLVE", "UPDATE"] and not target_incident_id:
            action = "NEW"

        if action == "NEW":
            incident_key = str(uuid.uuid4())
            redis_key = f"incident:{incident_key}"

            # Since this is the initial creation BEFORE dispatch, we save basic state.
            state = {
                "status": "OPEN",
                "subject": subject,
                "target_resource": target_resource,
                "first_seen": now,
                "last_updated": now,
                "occurrences": 1,
                "channels": {}
            }
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
            self.redis.sadd(open_list_key, incident_key)

            return {
                "action": "NEW",
                "incident_key": incident_key,
                "message_ids": {}
            }

        elif action == "UPDATE":
            redis_key = f"incident:{target_incident_id}"
            state_json = self.redis.get(redis_key)

            if not state_json:
                # Target doesn't exist, fallback to NEW
                return self.process_incident_state_ai(sender, subject, "NEW", target_resource=target_resource)

            state = json.loads(state_json)
            if state.get("status") != "OPEN":
                # Already closed, create NEW
                return self.process_incident_state_ai(sender, subject, "NEW", target_resource=target_resource)

            # Valid UPDATE (MERGE)
            state["occurrences"] = state.get("occurrences", 1) + 1
            state["last_updated"] = now
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)

            return {
                "action": "MERGE",
                "incident_key": target_incident_id,
                "message_ids": state.get("channels", {}),
                "occurrences": state["occurrences"],
                "original_text": state.get("original_telegram_text", "")
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
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
            self.redis.srem(open_list_key, target_incident_id)

            return {
                "action": "RESOLVE",
                "incident_key": target_incident_id,
                "message_ids": state.get("channels", {}),
                "original_text": state.get("original_telegram_text", "")
            }

        return {"action": "IGNORE", "incident_key": "", "message_ids": {}}

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
            if telegram_text and "original_telegram_text" not in state:
                state["original_telegram_text"] = telegram_text
            self.redis.set(redis_key, json.dumps(state), ex=86400*7)
