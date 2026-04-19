"""
Sentinel-AI-Core Alert Processor

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
from datetime import datetime

from ai_service import analyze_email, format_alert, format_for_matrix
from routing import get_routing_targets
from utils import html_to_text, send_telegram, send_telegram_auto, send_matrix_message, send_webhook, send_sms

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Alert-Processor")

# Config
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_QUEUE = "alert_queue"
REDIS_DLQ = "alert_dead_letter_queue"

# Default destinations
TELEGRAM_DEFAULT_CHAT_ID = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
TELEGRAM_DEFAULT_THREAD_ID = os.getenv("TELEGRAM_DEFAULT_THREAD_ID", "0")
MATRIX_DEFAULT_ROOM_ID = os.getenv("MATRIX_DEFAULT_ROOM_ID", "")
DEFAULT_NOTIFICATION_CHANNEL = os.getenv("DEFAULT_NOTIFICATION_CHANNEL", "both").lower()
FAILOVER_ENABLED = os.getenv("FAILOVER_ENABLED", "true").lower() == "true"

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
    except:
        pass


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
        # Trim old logs
        week_ago = time.time() - (7 * 24 * 3600)
        redis_client.zremrangebyscore("relay_logs", 0, week_ago)
    except:
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


def increment_metric(metric: str, amount: int = 1):
    """Increment a metric counter."""
    global redis_client
    try:
        if redis_client:
            redis_client.hincrby("metrics:processor", metric, amount)
    except:
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

        if channel == "dynamic":
            nc_ids = retry_data.get("notification_channel_ids", [])
            overrides = retry_data.get("channel_overrides", {})
            if nc_ids:
                success, destination = dispatch_dynamic_alert(
                    telegram_msg, matrix_msg, nc_ids, overrides
                )
        else:
            # Legacy path
            from utils import send_telegram_auto, send_matrix_message
            chat_id = retry_data.get("chat_id", "")
            thread_id = retry_data.get("thread_id", "0")
            room_id = retry_data.get("room_id", "")
            legacy_statuses = []

            if channel in ["telegram", "both"]:
                if send_telegram_auto(chat_id, int(thread_id), telegram_msg):
                    legacy_statuses.append("Telegram:OK")
                    success = True
                else:
                    legacy_statuses.append("Telegram:FAILED")

            if channel in ["matrix", "both"]:
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
    except:
        return False


def get_routing_rules():
    """Get all routing rules from Redis."""
    global redis_client
    try:
        rule_ids = redis_client.smembers("routing_rules:index") or set()
        rules = []
        for rid in rule_ids:
            rule = redis_client.hgetall(f"routing_rule:{rid}")
            if rule:
                rules.append(rule)
        return rules
    except:
        return []


def save_alert(alert_data: dict, ai_result: dict, channel: str) -> str:
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
            "created_at": now,
            "updated_at": now,
        }
        
        redis_client.hset(f"alert:{alert_id}", mapping=alert)
        redis_client.zadd("alerts:index", {alert_id: time.time()})
        
        logger.info(f"Alert saved: {alert_id}")
        return alert_id
    except Exception as e:
        logger.error(f"Failed to save alert: {e}")
        return ""

def get_channel_config(channel_id: str) -> dict:
    """Get channel configuration from Redis."""
    global redis_client
    try:
        return redis_client.hgetall(f"notification_channel:{channel_id}")
    except:
        return {}


def dispatch_dynamic_alert(telegram_text: str, matrix_text: str, 
                         channel_ids: list, overrides: dict = None) -> tuple:
    """
    Dispatch alert to multiple dynamic channels.
    Returns (success, destination_string)
    """
    if overrides is None:
        overrides = {}
    success = False
    status_parts = []
    
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
            raw_config = config.get("config", "{}")
            try:
                # Parse config JSON if it's a string
                token_data = {}
                if isinstance(raw_config, str):
                    try:
                        token_data = json.loads(raw_config)
                    except:
                        pass
                elif isinstance(raw_config, dict):
                    token_data = raw_config
                    
                bot_token = token_data.get("bot_token")
                chat_id = token_data.get("chat_id")
                proxy_url = token_data.get("proxy_base_url", "") or None
                
                # Use override if available, else channel default
                target_chat_id = override.get("chat_id") or chat_id
                target_thread_id = override.get("thread_id") or "0"
                
                if target_chat_id:
                    if send_telegram_auto(target_chat_id, int(target_thread_id), telegram_text, bot_token=bot_token, proxy_base_url=proxy_url):
                        success = True
                        status_parts.append(f"Telegram:{c_name}:OK")
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
                raw_config = config.get("config", "{}")
                conf = {}
                if isinstance(raw_config, str):
                     try:
                        conf = json.loads(raw_config)
                     except:
                        pass
                elif isinstance(raw_config, dict):
                    conf = raw_config
                     
                homeserver_url = conf.get("homeserver_url")
                access_token = conf.get("access_token")
                default_room_id = conf.get("default_room_id")
                
                target_room_id = override.get("room_id") or default_room_id
                
                if send_matrix_message(matrix_text, room_id=target_room_id, homeserver_url=homeserver_url, access_token=access_token):
                     success = True
                     status_parts.append(f"Matrix:{c_name}:OK")
                else:
                     status_parts.append(f"Matrix:{c_name}:FAILED")
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
    return success, destination


def process_message(payload_str: str) -> bool:
    """Process a single message from the queue."""
    global redis_client
    
    try:
        data = json.loads(payload_str)
        sender = data.get("from", "")
        subject = data.get("subject", "")
        
        # Check mute list
        if is_muted(sender):
            logger.info(f"Muted sender: {sender}")
            add_log("INFO", f"Skipped muted sender: {sender}")
            increment_metric("muted")
            return True
        
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
        
        
        # ── Phase 2: AI Analysis ──
        ai_provider_id = routing.get("ai_provider_id")
        ai_result, ai_provider_name, ai_duration = analyze_email(sender, subject, body, provider_id=ai_provider_id)
        
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
        
        # Save alert to Redis
        save_alert(data, ai_result, channel)
        
        # ── Phase 3: Format & Dispatch ──
        dispatch_start = time.time()
        telegram_msg = format_alert(ai_result, sender, subject, body)
        matrix_msg = format_for_matrix(ai_result, sender, subject, body)
        
        success = False
        destination = "None"
        
        if channel == "dynamic":
             logger.info(f"📤 Dispatching to {len(notification_channel_ids)} dynamic channel(s)...")
             success, destination = dispatch_dynamic_alert(
                 telegram_msg, matrix_msg, 
                 notification_channel_ids, channel_overrides
             )
        else:
             logger.info(f"📤 Dispatching via legacy channel: {channel}...")
             legacy_statuses = []
             
             try:
                 # Telegram Legacy
                 if channel in ["telegram", "both"]:
                     if send_telegram_auto(chat_id, int(thread_id), telegram_msg):
                         legacy_statuses.append("Telegram:OK")
                         success = True
                     else:
                         legacy_statuses.append("Telegram:FAILED")
                 
                 # Matrix Legacy
                 if channel in ["matrix", "both"]:
                     if send_matrix_message(matrix_msg, room_id):
                         legacy_statuses.append("Matrix:OK")
                         success = True
                     else:
                         legacy_statuses.append("Matrix:FAILED")
                         
                 destination = ", ".join(legacy_statuses)
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
            return True
        else:
            logger.error(f"❌ Failed to relay: {destination} ({dispatch_duration}s)")
            increment_metric("errors")
            add_log("ERROR", f"Relay failed: {destination}", {"dispatch_time": f"{dispatch_duration}s"})
            return False
    
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON payload")
        add_log("ERROR", "Invalid JSON payload")
        increment_metric("errors")
        return False
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        add_log("ERROR", f"Processing error: {str(e)}")
        increment_metric("errors")
        return False


def main():
    global redis_client
    
    # Connect to Redis
    try:
        logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        redis_client.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return
    
    # Start heartbeat
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()
    
    # Start retry worker
    retry_thread = threading.Thread(target=retry_worker_loop, daemon=True)
    retry_thread.start()
    
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
                success = process_message(payload)
                
                if not success:
                    # Build retry data from the original payload
                    try:
                        msg_data = json.loads(payload)
                        retry_data = {
                            "sender": msg_data.get("from", ""),
                            "subject": msg_data.get("subject", ""),
                            "original_payload": payload,
                            "retry_count": 0,
                        }
                        # Get dispatch context from the last process attempt
                        # Re-extract routing and formatted messages for retry
                        sender = msg_data.get("from", "")
                        subject = msg_data.get("subject", "")
                        body = msg_data.get("text", "")
                        if not body:
                            html_body = msg_data.get("html", "")
                            body = html_to_text(html_body) if html_body else ""
                        
                        # Re-route to get channel info
                        recipient_emails_retry = msg_data.get("rcpt_tos", [])
                        if not recipient_emails_retry:
                            to_email_retry = msg_data.get("to", "")
                            if to_email_retry:
                                recipient_emails_retry = [to_email_retry]
                        
                        rules = get_routing_rules()
                        routing = get_routing_targets(
                            sender, rules,
                            TELEGRAM_DEFAULT_CHAT_ID, TELEGRAM_DEFAULT_THREAD_ID,
                            MATRIX_DEFAULT_ROOM_ID, DEFAULT_NOTIFICATION_CHANNEL,
                            recipient_emails=recipient_emails_retry
                        )
                        
                        # Re-format messages (cheap, no AI needed)
                        # Use a minimal fallback since AI already ran
                        ai_result = None
                        try:
                            # Try to get saved AI result from alert
                            alert_keys = redis_client.zrevrange("alerts:index", 0, 0)
                            if alert_keys:
                                alert = redis_client.hgetall(f"alert:{alert_keys[0]}")
                                if alert and alert.get("ai_raw"):
                                    ai_result = json.loads(alert["ai_raw"])
                        except:
                            pass
                        
                        telegram_msg = format_alert(ai_result, sender, subject, body)
                        matrix_msg = format_for_matrix(ai_result, sender, subject, body)
                        
                        retry_data.update({
                            "telegram_msg": telegram_msg,
                            "matrix_msg": matrix_msg,
                            "channel": routing["channel"],
                            "chat_id": routing.get("telegram_chat_id", ""),
                            "thread_id": routing.get("telegram_thread_id", "0"),
                            "room_id": routing.get("matrix_room_id", ""),
                            "notification_channel_ids": routing.get("notification_channel_ids", []),
                            "channel_overrides": routing.get("channel_overrides", {}),
                        })
                        
                        schedule_retry(retry_data)
                        
                    except Exception as retry_err:
                        logger.error(f"Failed to schedule retry, moving to DLQ: {retry_err}")
                        try:
                            redis_client.rpush(REDIS_DLQ, payload)
                            add_log("WARNING", "Message moved to DLQ (retry schedule failed)")
                        except:
                            pass
        
        except redis.ConnectionError:
            logger.error("Redis connection lost, retrying in 5s...")
            add_log("ERROR", "Redis connection lost")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Loop error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
