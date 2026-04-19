"""
AI Service - Dynamic AI provider support with Ollama and OpenAI.
"""
import time as _time
import os
import json
import logging
import requests
import redis

logger = logging.getLogger("AI-Service")

# Redis Config
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Default Fallback Config (used if no providers in Redis)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1/chat/completions")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

# Message Verbosity
MESSAGE_VERBOSITY = os.getenv("MESSAGE_VERBOSITY", "standard")


def get_redis_client():
    """Get Redis client."""
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


def get_default_provider():
    """Get the default AI provider from Redis, or use env vars as fallback."""
    try:
        r = get_redis_client()
        # Find default provider
        provider_ids = r.smembers("ai_providers:index") or set()
        for pid in provider_ids:
            provider = r.hgetall(f"ai_provider:{pid}")
            if provider and provider.get("is_default", "false").lower() == "true":
                return {
                    "id": provider.get("id"),
                    "name": provider.get("name"),
                    "type": provider.get("type", "ollama"),
                    "base_url": provider.get("base_url"),
                    "model": provider.get("model"),
                    "api_key": provider.get("api_key", ""),
                    "timeout": int(provider.get("timeout", 120)),
                }
        
        # If no default, use first available
        for pid in provider_ids:
            provider = r.hgetall(f"ai_provider:{pid}")
            if provider:
                return {
                    "id": provider.get("id"),
                    "name": provider.get("name"),
                    "type": provider.get("type", "ollama"),
                    "base_url": provider.get("base_url"),
                    "model": provider.get("model"),
                    "api_key": provider.get("api_key", ""),
                    "timeout": int(provider.get("timeout", 120)),
                }
    except Exception as e:
        logger.warning(f"Could not get provider from Redis: {e}")
    
    # Fallback to environment variables
    return {
        "id": "env-fallback",
        "name": "Environment Fallback",
        "type": "ollama",
        "base_url": OLLAMA_BASE_URL,
        "model": OLLAMA_MODEL,
        "api_key": "",
        "timeout": 120,
    }


def build_system_prompt():
    """Build system prompt for email analysis."""
    return """You are an expert IT operations alert analyst. Your job is to read raw alert emails and produce a concise, actionable summary that an engineer can read in 10 seconds and immediately know what is broken and how to fix it.

Rules:
- Be extremely concise. No filler words. No obvious advice.
- The "main_message" must be ONE sentence describing WHAT failed and WHY.
- The "details" must be a list of short bullet-point strings with ONLY the key technical facts (hostnames, IPs, file paths, error codes, counts, timestamps). Never dump raw dicts or JSON.
- The "recommended_actions" must be 1-2 SPECIFIC actions. Do NOT give generic advice like "check logs" or "verify permissions". Instead say exactly WHAT to check WHERE, e.g. "Fix read permissions on 10.20.41.23:/var/backups/postgres/jira/ for the backup user".
- If the alert is about a partial failure (e.g. 3 of 12 files failed), mention the ratio.

Extract these fields:
1. severity: One of "Critical", "High", "Medium", "Low", "Info"
2. category: One of "Auth", "Backup", "Database", "Network", "System", "Service", "Storage", "Hardware", "DNS", "Virtualization", "Security", "Phishing", "Other"
3. confidence: Float 0.0 to 1.0
4. system_name: The source system or application name (e.g. "Syncovery v11.3.1", "Zabbix", "Veeam")
5. source_host: The hostname or IP where the alert originated
6. main_message: One concise sentence (WHAT failed + WHY)
7. details: A list of short strings, each a key fact bullet point
8. recommended_actions: 1-2 specific, actionable steps

Respond in JSON format ONLY:
{
    "analysis": {
        "severity": "...",
        "category": "...",
        "confidence": 0.0,
        "system_name": "...",
        "source_host": "...",
        "main_message": "...",
        "details": ["fact 1", "fact 2", "fact 3"],
        "recommended_actions": ["specific action 1"]
    }
}

Example input (Syncovery backup failure):
Subject: Syncovery Report - INCOMPLETE
Body: Profile OP-DB-PG03-SRV ... 9 copied of 12 ... Errors with 3 File(s) ... permission denied ...

Example output:
{
    "analysis": {
        "severity": "Medium",
        "category": "Backup",
        "confidence": 0.95,
        "system_name": "Syncovery v11.3.1",
        "source_host": "mail.local",
        "main_message": "Backup profile OP-DB-PG03-SRV incomplete: 3/12 files failed with permission denied on SFTP source.",
        "details": [
            "Source: sftp://10.20.41.23/var/backups/postgres/jira/",
            "Failed: confluence, jira, postgres dumps (2026-02-08)",
            "Dest: \\\\172.17.44.200\\DB-Backups\\OP-DB-PSG03-SRV",
            "Copied: 9 files (621.7MB) in 1m32s"
        ],
        "recommended_actions": [
            "Fix read permissions on 10.20.41.23:/var/backups/postgres/jira/ for the SFTP backup user"
        ]
    }
}"""


def get_provider_by_id(provider_id: str):
    """Get specific AI provider by ID."""
    try:
        r = get_redis_client()
        provider = r.hgetall(f"ai_provider:{provider_id}")
        if provider:
            return {
                "id": provider.get("id"),
                "name": provider.get("name"),
                "type": provider.get("type", "ollama"),
                "base_url": provider.get("base_url"),
                "model": provider.get("model"),
                "api_key": provider.get("api_key", ""),
                "timeout": int(provider.get("timeout", 120)),
            }
    except Exception as e:
        logger.warning(f"Could not get provider {provider_id} from Redis: {e}")
    return None


def analyze_email(sender: str, subject: str, body: str, provider_id: str = None) -> tuple:
    """
    Analyze email using dynamic AI provider (Ollama, OpenAI, or custom).
    Returns (analysis_dict, provider_name, duration_seconds) or (None, provider_name, duration_seconds) if failed.
    """
    start_time = _time.time()
    provider_name = "unknown"
    
    try:
        # Get provider dynamically
        provider = None
        if provider_id:
            provider = get_provider_by_id(provider_id)
        
        if not provider:
            provider = get_default_provider()
            
        base_url = provider["base_url"]
        model = provider["model"]
        api_key = provider.get("api_key", "")
        timeout = provider.get("timeout", 120)
        provider_type = provider.get("type", "ollama").lower()
        provider_name = f"{provider.get('name', 'unknown')} ({model})"

        # Fix OpenAI/Compatible URL
        if provider_type == "openai" and not base_url.endswith("/chat/completions"):
            base_url = f"{base_url.rstrip('/')}/chat/completions"
        
        user_content = f"""
Analyze this alert email:

FROM: {sender}
SUBJECT: {subject}

BODY:
{body[:4000]}  
"""
        
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.1
        }
        
        headers = {"Content-Type": "application/json"}
        
        # Add API key for OpenAI or other providers that need it
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        logger.info(f"⏳ AI analysis started | Provider: {provider_name}")
        
        response = requests.post(
            base_url,
            json=payload,
            headers=headers,
            timeout=timeout
        )
        
        duration = round(_time.time() - start_time, 1)
        
        if response.status_code != 200:
            logger.error(f"❌ AI API error ({duration}s): {response.status_code} - {response.text}")
            return None, provider_name, duration
        
        result = response.json()
        logger.debug(f"AI raw response: {result}")
        
        # Extract content from OpenAI-compatible response
        choices = result.get("choices", [])
        if not choices:
            logger.error(f"❌ No choices in AI response ({duration}s)")
            return None, provider_name, duration
        
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            logger.error(f"❌ Empty content in AI response ({duration}s)")
            return None, provider_name, duration
        
        # Try to parse JSON from content
        # Sometimes content might have markdown code blocks
        if content.startswith("```"):
            # Remove markdown code blocks
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
        
        parsed = json.loads(content)
        severity = parsed.get('analysis', {}).get('severity', 'Unknown')
        logger.info(f"✅ AI analysis complete | {duration}s | Provider: {provider_name} | Severity: {severity}")
        return parsed, provider_name, duration
    
    except json.JSONDecodeError as e:
        duration = round(_time.time() - start_time, 1)
        logger.error(f"❌ AI JSON parse failed ({duration}s): {e}")
        return None, provider_name, duration
    except requests.exceptions.RequestException as e:
        duration = round(_time.time() - start_time, 1)
        logger.error(f"❌ AI request failed ({duration}s): {e}")
        return None, provider_name, duration
    except Exception as e:
        duration = round(_time.time() - start_time, 1)
        logger.error(f"❌ AI error ({duration}s): {e}", exc_info=True)
        return None, provider_name, duration


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not text:
        return ""
    
    # Ensure text is string
    if not isinstance(text, str):
        try:
            text = str(text)
        except:
            return ""

    chars_to_escape = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars_to_escape:
        text = text.replace(char, f'\\{char}')
    return text


def format_alert(ai_result: dict, sender: str, subject: str, body: str = None) -> str:
    """
    Format the AI result into a Telegram MarkdownV2 message.
    """
    if not ai_result:
        return format_alert_fallback(sender, subject, body)
    
    analysis = ai_result.get("analysis", {})
    
    severity = analysis.get("severity", "Unknown")
    category = analysis.get("category", "Unknown")
    system_name = analysis.get("system_name", "Unknown")
    source_host = analysis.get("source_host", "")
    main_message = analysis.get("main_message", subject)
    details = analysis.get("details", [])
    confidence = analysis.get("confidence", 0)
    actions = analysis.get("recommended_actions", [])
    
    # Severity emoji
    severity_emoji = {
        "Critical": "🔴",
        "High": "🟠",
        "Medium": "🟡",
        "Low": "🟢",
        "Info": "ℹ️"
    }.get(severity, "⚪")
    
    # Build message
    lines = []
    
    # Header: 🟡 Medium | Backup
    lines.append(f"{severity_emoji} *{escape_markdown_v2(severity)}* \\| {escape_markdown_v2(category)}")
    
    # System + Host: 📌 Syncovery v11.3.1 — OP-SYNC-SRV
    header_line = system_name
    if source_host:
        header_line = f"{system_name} — {source_host}"
    lines.append(f"📌 *{escape_markdown_v2(header_line)}*")
    lines.append("")
    
    # Main message
    lines.append(escape_markdown_v2(main_message))
    
    if MESSAGE_VERBOSITY in ["standard", "debug"]:
        # Details as structured bullet points
        if details:
            lines.append("")
            # Handle both list and string formats
            if isinstance(details, list):
                for detail in details[:6]:
                    lines.append(f"• {escape_markdown_v2(str(detail))}")
            elif isinstance(details, str):
                lines.append(f"📋 {escape_markdown_v2(details)}")
            else:
                lines.append(f"📋 {escape_markdown_v2(str(details))}")
        
        # Actions (1-2 specific)
        if actions and len(actions) > 0:
            lines.append("")
            lines.append("*Action:*")
            for action in actions[:2]:
                lines.append(f"→ {escape_markdown_v2(str(action))}")
    
    if MESSAGE_VERBOSITY == "debug":
        lines.append("")
        lines.append(f"_Confidence: {confidence:.0%}_")
        lines.append(f"_From: {escape_markdown_v2(sender)}_")
    
    return "\n".join(lines)


def format_alert_fallback(sender: str, subject: str, body: str = None) -> str:
    """Fallback formatting when AI is unavailable."""
    lines = [
        f"⚠️ *Alert*",
        "",
        f"*Subject:* {escape_markdown_v2(subject)}",
        f"*From:* {escape_markdown_v2(sender)}",
    ]
    
    if body:
        preview = body[:200] + "..." if len(body) > 200 else body
        lines.append("")
        lines.append(escape_markdown_v2(preview))
    
    return "\n".join(lines)


def format_for_matrix(ai_result: dict, sender: str, subject: str, body: str = None) -> str:
    """Format alert for Matrix (plain text)."""
    if not ai_result:
        return f"⚠️ Alert\n\nSubject: {subject}\nFrom: {sender}\n\n{body[:500] if body else ''}"
    
    analysis = ai_result.get("analysis", {})
    
    severity = analysis.get("severity", "Unknown")
    category = analysis.get("category", "Unknown")
    system_name = analysis.get("system_name", "Unknown")
    source_host = analysis.get("source_host", "")
    main_message = analysis.get("main_message", subject)
    details = analysis.get("details", [])
    actions = analysis.get("recommended_actions", [])
    
    severity_emoji = {
        "Critical": "🔴",
        "High": "🟠",
        "Medium": "🟡",
        "Low": "🟢",
        "Info": "ℹ️"
    }.get(severity, "⚪")
    
    # Header
    header_line = system_name
    if source_host:
        header_line = f"{system_name} — {source_host}"
    
    lines = [
        f"{severity_emoji} {severity} | {category}",
        f"📌 {header_line}",
        "",
        main_message,
    ]
    
    # Details as bullet points
    if details:
        lines.append("")
        if isinstance(details, list):
            for detail in details[:6]:
                lines.append(f"• {str(detail)}")
        elif isinstance(details, str):
            lines.append(f"📋 {details}")
        else:
            lines.append(f"📋 {str(details)}")
    
    # Actions
    if actions and len(actions) > 0:
        lines.append("")
        lines.append("Action:")
        for action in actions[:2]:
            lines.append(f"→ {str(action)}")
    
    return "\n".join(lines)
