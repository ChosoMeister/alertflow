"""
Utility functions for alert processor.
"""
import os
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("Alert-Processor")

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Matrix Config
MATRIX_HOMESERVER_URL = os.getenv("MATRIX_HOMESERVER_URL", "")
MATRIX_ACCESS_TOKEN = os.getenv("MATRIX_ACCESS_TOKEN", "")
MATRIX_DEFAULT_ROOM_ID = os.getenv("MATRIX_DEFAULT_ROOM_ID", "")


def html_to_text(html: str) -> str:
    """Convert HTML to plain text."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")

        # Remove script and style elements
        for tag in soup(["script", "style"]):
            tag.decompose()

        # Get text with newlines preserved
        text = soup.get_text(separator="\n")

        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line)
    except Exception as e:
        logger.warning(f"Failed to parse HTML: {e}")
        return html



def send_telegram(chat_id: str, thread_id: int, text: str, bot_token: str = None) -> tuple[bool, int]:
    """Send message to Telegram and return (success, message_id)."""
    try:
        token = bot_token or TELEGRAM_BOT_TOKEN
        if not token:
            logger.error("No Telegram bot token provided")
            return False, None

        if not chat_id:
            logger.error("No Telegram chat_id provided")
            return False, None

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        if thread_id and int(thread_id) > 0:
            payload["message_thread_id"] = int(thread_id)

        response = requests.post(url, json=payload, timeout=10, proxies={"http": None, "https": None})

        if response.status_code == 200:
            result_data = response.json()
            message_id = result_data.get("result", {}).get("message_id")
            logger.info(f"Telegram message sent to {chat_id} (msg_id: {message_id})")
            return True, message_id
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False, None

    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False, None


def send_matrix_message(text: str, room_id: str = None,
                       homeserver_url: str = None, access_token: str = None) -> tuple[bool, str]:
    """Send message to Matrix room and return (success, event_id)."""
    try:
        hs_url = homeserver_url or MATRIX_HOMESERVER_URL
        token = access_token or MATRIX_ACCESS_TOKEN

        if not hs_url or not token:
            logger.warning("Matrix credentials missing (HS URL or Token)")
            return False, None

        target_room = room_id or MATRIX_DEFAULT_ROOM_ID
        if not target_room:
            logger.error("No Matrix room_id provided")
            return False, None

        # Ensure no trailing slash
        hs_url = hs_url.rstrip("/")

        # Encode room ID for URL
        encoded_room = target_room.replace("!", "%21").replace(":", "%3A")

        url = f"{hs_url}/_matrix/client/r0/rooms/{encoded_room}/send/m.room.message"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "msgtype": "m.text",
            "body": text,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code in [200, 201]:
            result_data = response.json()
            event_id = result_data.get("event_id")
            logger.info(f"Matrix message sent to {target_room} (event_id: {event_id})")
            return True, event_id
        else:
            logger.error(f"Matrix API error: {response.status_code} - {response.text}")
            return False, ""

    except Exception as e:
        logger.error(f"Failed to send Matrix message: {e}")
        return False, ""

def edit_matrix_message(text: str, event_id: str, room_id: str = None,
                       homeserver_url: str = None, access_token: str = None) -> bool:
    """Edit an existing message in a Matrix room."""
    try:
        hs_url = homeserver_url or MATRIX_HOMESERVER_URL
        token = access_token or MATRIX_ACCESS_TOKEN

        if not hs_url or not token or not event_id:
            logger.warning("Matrix credentials missing or event_id not provided for edit")
            return False

        target_room = room_id or MATRIX_DEFAULT_ROOM_ID
        if not target_room:
            logger.error("No Matrix room_id provided")
            return False

        hs_url = hs_url.rstrip("/")
        encoded_room = target_room.replace("!", "%21").replace(":", "%3A")

        url = f"{hs_url}/_matrix/client/r0/rooms/{encoded_room}/send/m.room.message"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "msgtype": "m.text",
            "body": f" * {text}",
            "m.new_content": {
                "msgtype": "m.text",
                "body": text
            },
            "m.relates_to": {
                "rel_type": "m.replace",
                "event_id": event_id
            }
        }

        logger.info(f"✏️ Editing Matrix message {event_id} in {target_room}")
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code in [200, 201]:
            logger.info(f"✅ Matrix message {event_id} edited successfully")
            return True
        else:
            logger.error(f"❌ Matrix Edit API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Failed to edit Matrix message: {e}")
        return False


def send_webhook(url: str, payload: dict) -> bool:
    """Send payload to a webhook URL."""
    try:
        if not url:
            logger.error("No Webhook URL provided")
            return False

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code in [200, 201, 202, 204]:
            logger.info(f"Webhook sent to {url}")
            return True
        else:
            logger.error(f"Webhook failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Webhook: {e}")
        return False


def send_sms(receptor: str, message: str, api_key: str, sender: str = None) -> bool:
    """Send SMS via Kavenegar."""
    try:
        if not api_key:
            logger.error("No Kavenegar API Key provided")
            return False

        if not receptor:
            logger.error("No SMS receptor (phone number) provided")
            return False

        url = f"https://api.kavenegar.com/v1/{api_key}/sms/send.json"
        data = {
            "receptor": receptor,
            "message": message,
        }

        if sender:
            data["sender"] = sender

        response = requests.post(url, data=data, timeout=10)
        result = response.json()

        if result.get("return", {}).get("status") == 200:
            logger.info(f"SMS sent to {receptor}")
            return True
        else:
            logger.error(f"Kavenegar API error: {result}")
            return False

    except Exception as e:
        logger.error(f"Failed to send SMS: {e}")
        return False


# ============================================
# Telegram Proxy Support (Cloudflare Worker)
# ============================================
# When enabled, Telegram API calls are routed through a proxy:
#   Direct:  https://api.telegram.org/bot{TOKEN}/sendMessage
#   Proxy:   https://tg.mydomain.ir/bot{TOKEN}/sendMessage
#
# Configuration priority:
#   1. Per-call proxy_base_url parameter (highest)
#   2. Global env vars USE_TELEGRAM_PROXY + TELEGRAM_PROXY_BASE_URL
#   3. Direct api.telegram.org (default)
# ============================================

USE_TELEGRAM_PROXY = os.getenv("USE_TELEGRAM_PROXY", "false").lower() == "true"
TELEGRAM_PROXY_BASE_URL = os.getenv("TELEGRAM_PROXY_BASE_URL", "").rstrip("/")


def send_telegram_proxied(chat_id: str, thread_id: int, text: str,
                          bot_token: str = None, proxy_base_url: str = None) -> tuple[bool, int]:
    """Send message to Telegram via Cloudflare Worker proxy and return (success, message_id).

    Identical behavior to send_telegram() but routes through the proxy URL.
    The proxy simply forwards all Telegram Bot API requests:
        {proxy_base_url}/bot{TOKEN}/sendMessage
    """
    try:
        token = bot_token or TELEGRAM_BOT_TOKEN
        if not token:
            logger.error("No Telegram bot token provided (proxy mode)")
            return False, None

        if not chat_id:
            logger.error("No Telegram chat_id provided (proxy mode)")
            return False, None

        base = (proxy_base_url or TELEGRAM_PROXY_BASE_URL).rstrip("/")
        if not base:
            logger.error("No proxy base URL configured")
            return False, None

        url = f"{base}/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        if thread_id and int(thread_id) > 0:
            payload["message_thread_id"] = int(thread_id)

        logger.info(f"📡 Sending Telegram via proxy: {base}")
        response = requests.post(url, json=payload, timeout=15)

        if response.status_code == 200:
            result_data = response.json()
            message_id = result_data.get("result", {}).get("message_id")
            logger.info(f"✅ Telegram proxy message sent to {chat_id} (msg_id: {message_id})")
            return True, message_id
        else:
            logger.error(f"❌ Telegram proxy API error: {response.status_code} - {response.text}")
            return False, None

    except Exception as e:
        logger.error(f"Failed to send Telegram message via proxy: {e}")
        return False, None


def send_telegram_auto(chat_id: str, thread_id: int, text: str,
                       bot_token: str = None, proxy_base_url: str = None) -> tuple[bool, int]:
    """Smart dispatcher — uses proxy if configured, else direct.

    Priority:
        1. If proxy_base_url is passed (per-channel config) → use proxy
        2. If USE_TELEGRAM_PROXY env is true → use global proxy
        3. Otherwise → use direct api.telegram.org
    """
    # If the user explicitly requested direct API, bypass proxy logic and system proxies
    if proxy_base_url and "api.telegram.org" in proxy_base_url.lower():
        return send_telegram(chat_id, thread_id, text, bot_token=bot_token)

    # Per-channel proxy takes highest priority
    if proxy_base_url:
        return send_telegram_proxied(chat_id, thread_id, text,
                                     bot_token=bot_token,
                                     proxy_base_url=proxy_base_url)

    # Global proxy
    if USE_TELEGRAM_PROXY and TELEGRAM_PROXY_BASE_URL:
        return send_telegram_proxied(chat_id, thread_id, text,
                                     bot_token=bot_token)

    # Direct (original behavior — send_telegram is untouched)
    return send_telegram(chat_id, thread_id, text, bot_token=bot_token)


def edit_telegram_message(chat_id: str, message_id: int, text: str, bot_token: str = None, proxy_base_url: str = None) -> bool:
    """Smart dispatcher to edit an existing Telegram message."""
    try:
        token = bot_token or TELEGRAM_BOT_TOKEN
        if not token or not chat_id or not message_id:
            logger.error(f"Missing credentials or message_id for Edit Message - token:{bool(token)} chat:{chat_id} msg_id:{message_id}")
            return False

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }

        # Check routing
        base = None
        if proxy_base_url and "api.telegram.org" not in proxy_base_url.lower():
            base = proxy_base_url.rstrip("/")
        elif USE_TELEGRAM_PROXY and TELEGRAM_PROXY_BASE_URL:
            base = TELEGRAM_PROXY_BASE_URL.rstrip("/")

        if base:
            url = f"{base}/bot{token}/editMessageText"
        else:
            url = f"https://api.telegram.org/bot{token}/editMessageText"

        logger.info(f"✏️ Editing Telegram message {message_id} in {chat_id}")

        # If it's direct to api.telegram.org, ignore system proxies
        req_proxies = {"http": None, "https": None} if "api.telegram.org" in url else None
        response = requests.post(url, json=payload, timeout=15, proxies=req_proxies)

        if response.status_code == 200:
            logger.info(f"✅ Telegram message {message_id} edited successfully")
            return True
        else:
            logger.error(f"❌ Telegram Edit API error: {response.status_code} - {response.text}")
            return False

    except Exception as e:
        logger.error(f"Failed to edit Telegram message: {e}")
        return False
