"""
Sentinel-AI-Core SMTP Ingestor

Listens for incoming SMTP emails, authenticates, parses, and queues them for processing.
"""
import os
import json
import redis
import logging
import asyncio
import time
import threading
from datetime import datetime
from email import message_from_bytes
from email.policy import default
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, AuthResult, LoginPassword

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SMTP-Ingestor")

# Config
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
SMTP_HOST = os.getenv("SMTP_LISTEN_HOST", "0.0.0.0")
SMTP_PORT = int(os.getenv("SMTP_LISTEN_PORT", 25))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "admin")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
REDIS_QUEUE = "alert_queue"

# Redis client
redis_client = None


def add_log(level: str, message: str, data: dict = None):
    """Add structured log to Redis stream."""
    global redis_client
    try:
        if redis_client:
            entry = {
                "level": level,
                "service": "smtp-ingestor",
                "message": message,
                "data": json.dumps(data or {}),
                "timestamp": datetime.utcnow().isoformat(),
            }
            redis_client.xadd("stream:logs", entry, maxlen=2000)
    except:
        pass


def set_heartbeat():
    """Set heartbeat in Redis."""
    global redis_client
    try:
        if redis_client:
            data = json.dumps({"timestamp": time.time(), "status": "ok"})
            redis_client.setex("heartbeat:smtp-ingestor", 15, data)
    except:
        pass


def heartbeat_loop():
    """Background thread for heartbeat."""
    while True:
        set_heartbeat()
        time.sleep(5)


class Authenticator:
    """Simple username/password authenticator."""
    
    def __call__(self, server, session, envelope, mechanism, auth_data):
        """Authenticate the user."""
        fail = AuthResult(success=False, handled=False)
        
        if mechanism not in ("LOGIN", "PLAIN"):
            return fail
        
        if not isinstance(auth_data, LoginPassword):
            return fail
        
        username = auth_data.login.decode("utf-8")
        password = auth_data.password.decode("utf-8")
        
        if username == SMTP_USERNAME and password == SMTP_PASSWORD:
            logger.info(f"Authentication successful for user: {username}")
            add_log("INFO", f"Auth success: {username}")
            return AuthResult(success=True)
        
        logger.warning(f"Authentication failed for user: {username}")
        add_log("WARNING", f"Auth failed: {username}")
        return fail


class EmailHandler:
    """Handle incoming emails."""
    
    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return "250 OK"
    
    async def handle_DATA(self, server, session, envelope):
        global redis_client
        
        try:
            # Parse email
            msg = message_from_bytes(envelope.content, policy=default)
            
            sender = envelope.mail_from or str(msg.get("From", ""))
            subject = str(msg.get("Subject", ""))
            rcpt_tos = envelope.rcpt_tos
            
            # Get body
            text_body = ""
            html_body = ""
            
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "text/plain":
                        text_body = part.get_content()
                    elif content_type == "text/html":
                        html_body = part.get_content()
            else:
                content_type = msg.get_content_type()
                if content_type == "text/plain":
                    text_body = msg.get_content()
                elif content_type == "text/html":
                    html_body = msg.get_content()
            
            # Prepare payload
            payload = {
                "from": sender,
                "subject": subject,
                "text": text_body,
                "html": html_body,
                "rcpt_tos": rcpt_tos,
                "received_at": datetime.utcnow().isoformat(),
            }
            
            # Push to Redis queue
            redis_client.rpush(REDIS_QUEUE, json.dumps(payload))
            
            logger.info(f"Email queued: From={sender}, Subject={subject[:50]}")
            add_log("INFO", f"Email queued from {sender}", {"subject": subject[:100]})
            
            return "250 Message accepted for delivery"
        
        except Exception as e:
            logger.error(f"Error processing email: {e}", exc_info=True)
            add_log("ERROR", f"Error processing email: {str(e)}")
            return "451 Requested action aborted: error in processing"


def main():
    global redis_client
    
    # Connect to Redis
    try:
        logger.info(f"Connecting to Redis at {REDIS_HOST}:{REDIS_PORT}...")
        redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        redis_client.ping()
        logger.info("Connected to Redis successfully")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return
    
    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()
    
    # Start SMTP server
    handler = EmailHandler()
    
    # If username/password are set, enable authentication; otherwise open relay (for internal use)
    auth_enabled = bool(SMTP_USERNAME and SMTP_PASSWORD)
    
    controller_kwargs = dict(
        hostname=SMTP_HOST,
        port=SMTP_PORT,
    )
    
    if auth_enabled:
        auth = Authenticator()
        controller_kwargs["authenticator"] = auth
        controller_kwargs["auth_required"] = True
        controller_kwargs["auth_require_tls"] = False  # For internal networks
    
    controller = Controller(handler, **controller_kwargs)
    controller.start()
    
    if auth_enabled:
        logger.info(f"SMTP Ingestor started on {SMTP_HOST}:{SMTP_PORT} (auth: user={SMTP_USERNAME})")
        add_log("INFO", f"SMTP Ingestor started on port {SMTP_PORT} with authentication")
    else:
        logger.info(f"SMTP Ingestor started on {SMTP_HOST}:{SMTP_PORT} (NO authentication)")
        add_log("INFO", f"SMTP Ingestor started on port {SMTP_PORT} WITHOUT authentication")
    
    try:
        # Keep running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        controller.stop()


if __name__ == "__main__":
    main()
