import json
import logging
import redis
from fastapi import APIRouter, Request, Header, HTTPException, status
from config import get_settings

router = APIRouter(prefix="/webhook", tags=["Webhook"])
logger = logging.getLogger("API-Webhook")
settings = get_settings()

# Singleton Redis client connection
_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password or None,
                decode_responses=True
            )
            _redis_client.ping()
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise HTTPException(status_code=503, detail="Service Unavailable (Redis)")
    return _redis_client

@router.post("/{source_name}")
async def receive_webhook(
    source_name: str,
    request: Request,
    x_webhook_token: str = Header(None, alias="X-Webhook-Token")
):
    """
    Receive alerts via HTTP POST webhooks (e.g. from Grafana, Zabbix).
    Parses JSON directly to simulate an email and queues it for the AI processor.
    """
    # 1. Hardening: Authentication Check
    if not settings.webhook_auth_token:
        logger.error("Webhook endpoint called but WEBHOOK_AUTH_TOKEN is not configured.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook receiver is disabled (token not configured)"
        )

    if x_webhook_token != settings.webhook_auth_token:
        logger.warning(f"Unauthorized webhook attempt from {request.client.host}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )

    # 2. Hardening: Payload Size Limit (512KB)
    body_bytes = await request.body()
    if len(body_bytes) > 512 * 1024:
        logger.warning(f"Webhook payload too large from {request.client.host} ({len(body_bytes)} bytes)")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload too large (max 512KB)"
        )

    # 3. Parse JSON flexibly
    try:
        data = await request.json()
    except Exception:
        # Fallback to plain text if invalid JSON
        data = {"raw_text": body_bytes.decode('utf-8', errors='ignore')}

    # 4. Extract Subject / Title heuristically
    subject = f"Alert from {source_name}"
    if isinstance(data, dict):
        subject = (
            data.get("title") or
            data.get("subject") or
            data.get("message") or
            data.get("alertname") or
            subject
        )

        # Hardening for "Resolved" state: if JSON natively says status is resolved,
        # force the subject to have [RESOLVED] so main.py catches it deterministically.
        status_val = str(data.get("status", "")).lower()
        if status_val == "resolved" and "[RESOLVED]" not in subject.upper():
            subject = f"[RESOLVED] {subject}"

    # 5. Format the entire payload as standard text body for AI analysis
    text_content = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)

    # 6. Standardize Queue Payload (Mock SMTP format)
    payload = {
        "from": f"{source_name}@webhook.local",
        "subject": str(subject)[:200],  # Limit subject length
        "text": text_content,
        "html": "",
        "to": "webhook-receiver@alertflow",
        "rcpt_tos": ["webhook-receiver@alertflow"]
    }

    # 7. Push to Redis queue
    try:
        r = get_redis()
        r.lpush("alert_queue", json.dumps(payload))
        logger.info(f"Queued webhook alert from {source_name} (Subject: {subject[:50]})")
    except Exception as e:
        logger.error(f"Error queueing webhook alert: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

    return {"status": "accepted", "queued": True, "source": source_name}
