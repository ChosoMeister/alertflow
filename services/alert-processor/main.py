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
import threading
import pytz
from datetime import datetime

from ai_service import analyze_email, format_alert, format_for_matrix
from routing import get_routing_targets
from utils import html_to_text, send_telegram, send_telegram_auto, send_matrix_message, send_webhook, send_sms
from correlation import IncidentTracker

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
REDIS_DLQ = "alert_dead_letter_queue"

# Default destinations
TELEGRAM_DEFAULT_CHAT_ID = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
TELEGRAM_DEFAULT_THREAD_ID = os.getenv("TELEGRAM_DEFAULT_THREAD_ID", "0")
MATRIX_DEFAULT_ROOM_ID = os.getenv("MATRIX_DEFAULT_ROOM_ID", "")
DEFAULT_NOTIFICATION_CHANNEL = os.getenv("DEFAULT_NOTIFICATION_CHANNEL", "both").lower()
FAILOVER_ENABLED = os.getenv("FAILOVER_ENABLED", "true").lower() == "true"
DAILY_SUMMARY_TIME = os.getenv("DAILY_SUMMARY_TIME", "08:00")
DAILY_SUMMARY_TIMEZONE = os.getenv("DAILY_SUMMARY_TIMEZONE", "Asia/Tehran")

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
                        pipe = redis_client.pipeline(transaction=False)
                        for aid in old_ids_str:
                            pipe.delete(f"alert:{aid}")
                        pipe.execute()

                        # Remove from index
                        redis_client.zremrangebyscore("alerts:index", 0, cutoff_time)
                        logger.info(f"Cleaned up {len(old_ids_str)} old alerts")

                    # 2. Clean up relay_logs
                    redis_client.zremrangebyscore("relay_logs", 0, cutoff_time)

        except Exception as e:
            logger.error(f"Cleanup error: {e}")

        # Run cleanup every hour
        time.sleep(3600)


def increment_metric(metric: str, amount: int = 1):
    """Increment a metric counter."""
    global redis_client
    try:
        if redis_client:
            redis_client.hincrby("metrics:processor", metric, amount)
    except Exception:
        pass


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
            redis_client.rpush(REDIS_DLQ, json.dumps(retry_data))
            increment_metric("dlq")
            return False

        delay = RETRY_BACKOFF_SECONDS[retry_count]
        next_retry_at = time.time() + delay
        retry_data["retry_count"] = retry_count + 1
        retry_data["next_retry_at"] = next_retry_at
        retry_data["scheduled_at"] = datetime.utcnow().isoformat()

        redis_client.zadd(RETRY_QUEUE, {json.dumps(retry_data): next_retry_at})

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

        if channel == "dynamic":
            nc_ids = retry_data.get("notification_channel_ids", [])
            overrides = retry_data.get("channel_overrides", {})
            if nc_ids:
                success, destination, new_msg_ids = dispatch_dynamic_alert(
                    telegram_msg, matrix_msg, nc_ids, overrides,
                    action=action, incident_key=incident_key, known_message_ids=known_message_ids
                )
        else:
            # Legacy path
            from utils import send_telegram_auto, send_matrix_message, edit_telegram_message, edit_matrix_message
            chat_id = retry_data.get("chat_id", "")
            thread_id = retry_data.get("thread_id", "0")
            room_id = retry_data.get("room_id", "")
            legacy_statuses = []

            if channel in ["telegram", "both"]:
                channel_key = f"telegram_{chat_id}"
                existing_msg_id = known_message_ids.get(channel_key)

                if action in ["RESOLVE", "MERGE", "UPDATE"] and existing_msg_id:
                    if edit_telegram_message(chat_id, existing_msg_id, telegram_msg):
                        legacy_statuses.append("TelegramEdit:OK")
                        success = True
                    else:
                        legacy_statuses.append("TelegramEdit:FAILED")
                else:
                    if send_telegram_auto(chat_id, int(thread_id), telegram_msg):
                        legacy_statuses.append("Telegram:OK")
                        success = True
                    else:
                        legacy_statuses.append("Telegram:FAILED")

            if channel in ["matrix", "both"]:
                channel_key = f"matrix_{room_id}"
                existing_msg_id = known_message_ids.get(channel_key)

                if action in ["RESOLVE", "MERGE", "UPDATE"] and existing_msg_id:
                    if edit_matrix_message(matrix_msg, existing_msg_id, room_id):
                        legacy_statuses.append("MatrixEdit:OK")
                        success = True
                    else:
                        legacy_statuses.append("MatrixEdit:FAILED")
                else:
                    if send_matrix_message(matrix_msg, room_id):
                        legacy_statuses.append("Matrix:OK")
                        success = True
                    else:
                        legacy_statuses.append("Matrix:FAILED")

            destination = ", ".join(legacy_statuses) if legacy_statuses else "Legacy:NONE"

        # Log result
        add_relay_log(sender, subject, channel, f"RETRY-{retry_num}:{destination}", success)

        if success:
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

    while True:
        try:
            now = time.time()
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


def save_alert(alert_data: dict, ai_result: dict, channel: str, incident_key: str = "", action: str = "NEW") -> str:
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
            "body": alert_data.get("text", "") or alert_data.get("body", ""),
            "html": alert_data.get("html", ""),
            "channel": channel,
            "status": "new",
            "severity": str(analysis.get("severity", "")),
            "category": str(analysis.get("category", "")),
            "confidence": str(analysis.get("confidence", "")),
            "system_name": str(analysis.get("system_name", "")),
            "main_message": str(analysis.get("main_message", "")),
            "details": str(analysis.get("details", "")),
            "ai_raw": json.dumps(ai_result) if ai_result else "",
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

        redis_client.hset(f"alert:{alert_id}", mapping=alert)
        redis_client.zadd("alerts:index", {alert_id: time.time()})

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


from utils import edit_telegram_message, edit_matrix_message

def dispatch_dynamic_alert(telegram_text: str, matrix_text: str,
                         channel_ids: list, overrides: dict = None,
                         action: str = "NEW", incident_key: str = "",
                         known_message_ids: dict = None) -> tuple:
    """
    Dispatch alert to multiple dynamic channels.
    Returns (success, destination_string, new_message_ids)
    """
    if overrides is None:
        overrides = {}
    if known_message_ids is None:
        known_message_ids = {}

    success = False
    status_parts = []
    new_message_ids = {}

    if not channel_ids:
        return False, "No dynamic channels configured"

    for channel_id in channel_ids:
        config = get_channel_config(channel_id)
        if not config:
            status_parts.append(f"MissingConfig({channel_id})")
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
                chat_id = token_data.get("chat_id")
                proxy_url = token_data.get("proxy_base_url", "") or None

                # Use override if available, else channel default
                target_chat_id = override.get("chat_id") or chat_id
                target_thread_id = override.get("thread_id") or "0"

                if target_chat_id:
                    # Check if we should edit instead of send
                    channel_key = f"telegram_{target_chat_id}"
                    existing_msg_id = known_message_ids.get(channel_key)

                    if (action in ["RESOLVE", "MERGE", "UPDATE"]) and existing_msg_id:
                        if edit_telegram_message(target_chat_id, existing_msg_id, telegram_text, bot_token=bot_token, proxy_base_url=proxy_url):
                            success = True
                            status_parts.append(f"TelegramEdit:{c_name}:OK")
                        else:
                            status_parts.append(f"TelegramEdit:{c_name}:FAILED")
                    else:
                        # Standard send
                        send_ok, msg_id = send_telegram_auto(target_chat_id, int(target_thread_id), telegram_text, bot_token=bot_token, proxy_base_url=proxy_url)
                        if send_ok:
                            success = True
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
                             status_parts.append(f"MatrixEdit:{c_name}:OK")
                        else:
                             status_parts.append(f"MatrixEdit:{c_name}:FAILED")
                    else:
                        send_ok, msg_id = send_matrix_message(matrix_text, room_id=target_room_id, homeserver_url=homeserver_url, access_token=access_token)
                        if send_ok:
                             success = True
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
                    status_parts.append(f"SMS:{c_name}:OK")
                else:
                    status_parts.append(f"SMS:{c_name}:FAILED")
            except Exception as e:
                status_parts.append(f"SMS:{c_name}:ERR")
                logger.error(f"SMS dispatch error: {e}")

    destination = ", ".join(status_parts) if status_parts else "No successful dispatch"
    return success, destination, new_message_ids


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

            suffix += "\n_\\(Monitoring system still reports error\\)_"

            updated_text = original_text + suffix

            from utils import edit_telegram_message, edit_matrix_message

            # Pre-fetch all channel configs to prevent N+1 queries
            channel_keys = redis_client.keys("notification_channel:*")
            all_configs = []
            if channel_keys:
                pipe = redis_client.pipeline(transaction=False)
                for ck in channel_keys:
                    pipe.hgetall(ck)
                all_configs = pipe.execute()

            telegram_configs = []
            matrix_configs = []
            for cfg in all_configs:
                try:
                    conf = parse_channel_config_data(cfg.get("config", "{}"))
                    c_type = cfg.get("type")
                    if c_type == "telegram":
                        telegram_configs.append(conf)
                    elif c_type == "matrix":
                        matrix_configs.append(conf)
                except Exception as e:
                    logger.debug(f"Failed to parse channel config json: {e}")

            for channel_key, msg_id in incident_message_ids.items():
                if channel_key.startswith("telegram_"):
                    chat_id = channel_key.replace("telegram_", "")

                    bot_token, proxy_url = None, None
                    fb_bot_token, fb_proxy_url = None, None

                    for conf in telegram_configs:
                        if not fb_bot_token and conf.get("bot_token"):
                            fb_bot_token = conf.get("bot_token")
                            fb_proxy_url = conf.get("proxy_base_url", "") or None
                        if str(conf.get("chat_id")) == str(chat_id):
                            bot_token = conf.get("bot_token")
                            proxy_url = conf.get("proxy_base_url", "") or None
                            break

                    bot_token = bot_token or fb_bot_token
                    proxy_url = proxy_url or fb_proxy_url
                    edit_telegram_message(chat_id, msg_id, updated_text, bot_token=bot_token, proxy_base_url=proxy_url)

                elif channel_key.startswith("matrix_"):
                    room_id = channel_key.replace("matrix_", "")

                    hs_url, access_token = None, None
                    fb_hs_url, fb_access_token = None, None

                    for conf in matrix_configs:
                        if not fb_hs_url and conf.get("homeserver_url") and conf.get("access_token"):
                            fb_hs_url = conf.get("homeserver_url")
                            fb_access_token = conf.get("access_token")
                        if str(conf.get("default_room_id")) == str(room_id):
                            hs_url = conf.get("homeserver_url")
                            access_token = conf.get("access_token")
                            break

                    hs_url = hs_url or fb_hs_url
                    access_token = access_token or fb_access_token
                    edit_matrix_message(updated_text, msg_id, room_id, homeserver_url=hs_url, access_token=access_token)

            return True, payload_str

        sender = data.get("from", "")
        subject = data.get("subject", "")

        # Check mute list
        if is_muted(sender):
            logger.info(f"Muted sender: {sender}")
            add_log("INFO", f"Skipped muted sender: {sender}")
            increment_metric("muted")
            return True, payload_str

        # Get body
        body = data.get("text", "")
        if not body:
            html_body = data.get("html", "")
            body = html_to_text(html_body) if html_body else ""

        logger.info(f"📩 Processing: From={sender}, Subject={subject[:50]}")

        # Extract recipient emails for TO-based routing
        recipient_emails = data.get("rcpt_tos", [])
        if not recipient_emails:
            to_email = data.get("to", "")
            if to_email:
                recipient_emails = [to_email]

        tracker = IncidentTracker(redis_client)

        # ── Hook 1: Exact Dedup Check ──
        is_reprocess = "reprocess_alert_id" in data or "resend_alert_id" in data
        if not is_reprocess:
            exact_hash = tracker.generate_exact_hash(data)
            exact_key = f"dedup:exact:{exact_hash}"
            if redis_client.exists(exact_key):
                logger.info(f"🚫 Exact Drop: Duplicate of {exact_hash}")
                redis_client.incr(exact_key)
                # Update expiry
                redis_client.expire(exact_key, 1800) # 30 min rolling window
                increment_metric("muted")
                add_log("INFO", f"Exact duplicate dropped", {"hash": exact_hash})
                return True, payload_str
            else:
                redis_client.setex(exact_key, 1800, 1)

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
        channel = routing["channel"]  # "telegram", "matrix", "both", "dynamic"

        # Legacy single-channel vars
        chat_id = routing.get("telegram_chat_id")
        thread_id = routing.get("telegram_thread_id")
        room_id = routing.get("matrix_room_id")

        # New dynamic vars
        notification_channel_ids = routing.get("notification_channel_ids", [])
        channel_overrides = routing.get("channel_overrides", {})
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
                lines.append(f"- ID: {c['id']} | Subject: {c['subject']} | Target: {c['target']} | Occurrences: {c['occurrences']}")
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


        # ── Phase 2.5: Severity-Based Routing (New) ──
        # If the matched rule has specific actions for this severity, override targets
        severity_matrix = routing.get("severity_matrix", {})

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

            if sev_entry is not None:
                # Support new nested format: { channels: [...], channel_overrides: {...} }
                # and old flat format: [channel_id_1, channel_id_2]
                if isinstance(sev_entry, dict):
                    sev_channels = sev_entry.get("channels", [])
                    sev_overrides = sev_entry.get("channel_overrides", {})
                elif isinstance(sev_entry, list):
                    sev_channels = sev_entry
                    sev_overrides = {}
                else:
                    sev_channels = []
                    sev_overrides = {}

                if sev_channels:
                    channel = "dynamic"
                    notification_channel_ids = sev_channels
                    # Merge severity-specific overrides on top of rule-level overrides
                    channel_overrides = {**channel_overrides, **sev_overrides}
                    logger.info(f"🚨 Severity override applied: {detected_severity} → {len(notification_channel_ids)} channels, {len(sev_overrides)} overrides")
                    add_log("INFO", f"Severity override: {detected_severity}", {"channels": len(notification_channel_ids), "overrides": len(sev_overrides)})
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
                        "original_text": state.get("original_text", "")
                    }

        if not correlation_result:
            if ai_result and "analysis" in ai_result:
                ai_analysis = ai_result["analysis"]
                ai_action = ai_analysis.get("action", "NEW").upper()
                target_id = ai_analysis.get("target_incident_id", "")
                target_resource = ai_analysis.get("target_resource", "unknown")

                # AI makes the decision
                correlation_result = tracker.process_incident_state_ai(
                    sender, subject, ai_action, target_incident_id=target_id, target_resource=target_resource
                )
            else:
                # Fallback if AI fails
                correlation_result = tracker.process_incident_state_ai(
                    sender, subject, "NEW", target_resource="unknown"
                )

        action = correlation_result.get("action", "NEW")
        incident_key = correlation_result.get("incident_key", "")
        incident_message_ids = correlation_result.get("message_ids", {})

        # Save alert to Redis with Correlation Data
        alert_id = save_alert(data, ai_result, channel, incident_key, action)

        if action == "IGNORE":
            logger.info(f"🔇 Redundant Resolve Dropped: {incident_key}")
            return True, payload_str
        elif action == "MERGE":
            logger.info(f"🔕 Muted Spammer: {incident_key} (already open, incrementing count)")
            # Add occurrence count to original telegram text
            occurrences = correlation_result.get("occurrences", 2)
            original_text = correlation_result.get("original_text", "")
            if incident_message_ids and original_text:
                updated_text = f"{original_text}\n\n📌 *تعداد هشدارهای مشابه:* `{occurrences}`"
            elif incident_message_ids and not original_text:
                logger.warning(f"⚠️ MERGE: original_text missing for incident {incident_key}, cannot edit")
                add_log("WARNING", "MERGE edit skipped: original_text missing", {"incident_key": incident_key})

                # Dispatch the edit using dynamic routing to ensure we have the tokens
                if channel == "dynamic":
                    dispatch_dynamic_alert(
                        telegram_text=updated_text, matrix_text=updated_text,
                        channel_ids=notification_channel_ids, overrides=channel_overrides,
                        action="MERGE", incident_key=incident_key, known_message_ids=incident_message_ids
                    )
                else:
                    # Legacy dispatch edit fallback
                    if channel in ["telegram", "both"]:
                        for channel_key, msg_id in incident_message_ids.items():
                            if channel_key.startswith("telegram_"):
                                target_chat_id = channel_key.replace("telegram_", "")
                                from utils import edit_telegram_message
                                edit_telegram_message(target_chat_id, msg_id, updated_text)
                    if channel in ["matrix", "both"]:
                        for channel_key, msg_id in incident_message_ids.items():
                            if channel_key.startswith("matrix_"):
                                target_room_id = channel_key.replace("matrix_", "")
                                from utils import edit_matrix_message
                                edit_matrix_message(updated_text, msg_id, target_room_id)
            return True, payload_str

        # ── Phase 3: Format & Dispatch ──
        dispatch_start = time.time()
        telegram_msg = format_alert(ai_result, sender, subject, body)
        matrix_msg = format_for_matrix(ai_result, sender, subject, body)

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

        if channel == "dynamic":
             logger.info(f"📤 Dispatching to {len(notification_channel_ids)} dynamic channel(s)...")
             success, destination, new_msg_ids = dispatch_dynamic_alert(
                 telegram_msg, matrix_msg,
                 notification_channel_ids, channel_overrides,
                 action=action, incident_key=incident_key, known_message_ids=incident_message_ids
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
                "channel": channel,
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
                "channel": channel,
                "chat_id": chat_id,
                "thread_id": thread_id,
                "room_id": room_id,
                "notification_channel_ids": notification_channel_ids,
                "channel_overrides": channel_overrides,
                "action": action,
                "incident_key": incident_key,
                "known_message_ids": incident_message_ids,
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
                success, dest_str, _ = dispatch_dynamic_alert(
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

def daily_summary_loop():
    logger.info(f"Starting daily summary scheduler for {DAILY_SUMMARY_TIME} {DAILY_SUMMARY_TIMEZONE}")
    while True:
        try:
            tz = pytz.timezone(DAILY_SUMMARY_TIMEZONE)
            now = datetime.now(tz)

            current_time_str = now.strftime("%H:%M")
            if current_time_str == DAILY_SUMMARY_TIME:
                generate_daily_summary()
                time.sleep(61)
            else:
                time.sleep(30)
        except Exception as e:
            logger.error(f"Summary loop error: {e}")
            time.sleep(60)

def main():
    global redis_client

    # Connect to Redis
    try:
        logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD or None, decode_responses=True)
        redis_client.ping()
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

    logger.info("Starting Alert Processor...")
    logger.info(f"Default channel: {DEFAULT_NOTIFICATION_CHANNEL}")
    logger.info(f"Default Telegram: {TELEGRAM_DEFAULT_CHAT_ID or 'Not Set'}")
    logger.info(f"Default Matrix: {MATRIX_DEFAULT_ROOM_ID or 'Not Set'}")
    logger.info(f"Failover enabled: {FAILOVER_ENABLED}")

    add_log("INFO", "Alert Processor started")

    while True:
        try:
            item = redis_client.blpop(REDIS_QUEUE, timeout=5)
            if item:
                queue_name, payload = item
                success, payload = process_message(payload)
                if not success:
                    # If process_message completely failed (exception), send to DLQ
                    logger.error(f"Message processing failed critically, moving to DLQ")
                    redis_client.rpush(REDIS_DLQ, payload)
                    add_log("WARNING", "Message moved to DLQ (critical processing failure)")

        except redis.ConnectionError:
            logger.error("Redis connection lost, retrying in 5s...")
            add_log("ERROR", "Redis connection lost")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
