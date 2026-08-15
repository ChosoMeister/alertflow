"""
AI Service - Dynamic AI provider support with Ollama and OpenAI.
"""
import time as _time
import os
import json
import logging
import requests
from source_adapters import normalize_alert, normalize_resource_identifiers, preserve_resources, prompt_context, validate_analysis
import redis

logger = logging.getLogger("AI-Service")

VALID_SEVERITIES = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "info": "Info"}
VALID_CATEGORIES = {
    value.lower(): value for value in (
        "Auth", "Backup", "Database", "Network", "System", "Service", "Storage",
        "Hardware", "DNS", "Virtualization", "Security", "Phishing", "Unclassified",
    )
}


def normalize_analysis_taxonomy(analysis: dict) -> None:
    """Constrain model labels to stable analytics/routing enums."""
    severity = str(analysis.get("severity", "")).strip().lower()
    category = str(analysis.get("category", "")).strip().lower()
    if category in {"other", "unknown", "uncategorized", ""}:
        category = "unclassified"
    analysis["severity"] = VALID_SEVERITIES.get(severity, "Unknown")
    analysis["category"] = VALID_CATEGORIES.get(category, "Unclassified")


def _record_provider_metric(provider: dict, outcome: str, duration: float = 0.0, error: str = "", fallback: bool = False):
    """Record provider health and latency without storing prompts or credentials."""
    try:
        client = get_redis_client()
        provider_id = provider.get("id") or "environment-default"
        key = f"metrics:ai:provider:{provider_id}"
        pipe = client.pipeline(transaction=False)
        pipe.hset(key, mapping={
            "provider_id": provider_id,
            "name": provider.get("name", "unknown"),
            "model": provider.get("model", ""),
            "last_outcome": outcome,
            "last_checked_at": str(_time.time()),
        })
        pipe.hincrby(key, "attempts", 1)
        pipe.hincrby(key, outcome, 1)
        pipe.hincrbyfloat(key, "latency_total_seconds", float(duration or 0))
        if fallback:
            pipe.hincrby(key, "fallback_uses", 1)
        if outcome == "success":
            pipe.hset(key, mapping={"last_success_at": str(_time.time()), "last_error": ""})
        elif error:
            pipe.hset(key, mapping={"last_failure_at": str(_time.time()), "last_error": error[:500]})
        pipe.expire(key, 86400 * 30)
        pipe.execute()
    except Exception:
        logger.debug("Could not record AI provider metric", exc_info=True)


def normalize_recommended_actions(analysis: dict) -> None:
    """Apply a deterministic safety classification to model recommendations."""
    normalized = []
    destructive_terms = ("delete", "recreate", "format", "force-attach", "force attach", "detach", "kubectl patch")
    diagnostic_terms = ("check", "inspect", "describe", "review", "verify", "get ", "list ", "query")
    for raw in analysis.get("recommended_actions", [])[:2]:
        if isinstance(raw, dict):
            text = str(raw.get("text", "")).strip()
            action_type = str(raw.get("type", "")).lower()
        else:
            text = str(raw).strip()
            action_type = ""
        if not text:
            continue
        lowered = text.lower()
        if any(term in lowered for term in destructive_terms):
            action_type = "destructive"
        elif not action_type:
            action_type = "diagnostic" if any(term in lowered for term in diagnostic_terms) else "reversible"
        if action_type not in {"diagnostic", "reversible", "destructive"}:
            action_type = "reversible"
        normalized.append({
            "text": text,
            "type": action_type,
            "requires_approval": action_type != "diagnostic",
        })
    analysis["recommended_actions"] = normalized


def action_display(action) -> str:
    if not isinstance(action, dict):
        return str(action)
    prefix = "[Requires approval] " if action.get("requires_approval") else ""
    return prefix + str(action.get("text", ""))

# Redis Config
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Default Fallback Config (used if no providers in Redis)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1/chat/completions")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

# Message Verbosity
MESSAGE_VERBOSITY = os.getenv("MESSAGE_VERBOSITY", "standard")

# Singleton Redis client
_redis_client = None


def get_redis_client():
    """Get singleton Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


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
                    "is_fallback": provider.get("is_fallback", "false").lower() == "true",
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
                    "is_fallback": provider.get("is_fallback", "false").lower() == "true",
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


def build_system_prompt(active_incidents_text=""):
    """Build system prompt for email analysis."""
    active_incidents_text = active_incidents_text[:2000]

    context_instruction = ""
    if active_incidents_text:
        context_instruction = f"""
Here is a list of currently ACTIVE (open) incidents for this sender:
{active_incidents_text}

CRITICAL MATCHING TASK:
You must determine if this new alert is related to any of the ACTIVE incidents above.
- If it resolves an active incident, set action="RESOLVE" and target_incident_id="[the ID from the list]".
- If it is an update/repetition of an active incident, set action="UPDATE" and target_incident_id="[the ID from the list]".
- If it is a completely new and unrelated issue, set action="NEW" and target_incident_id="".
- Match both the alert rule AND the concrete target resources. Similar subjects with disjoint PVCs, hosts, VMs, databases, paths, or services are different incidents.
- If the active incident has unknown resources but this alert names them, UPDATE it and preserve every named resource.
- If this is an "UP" or "RESOLVED" alert but there is no matching active incident, set action="RESOLVE" with an empty target_incident_id. It is a standalone recovery and must never become a new active outage.
"""
    else:
        context_instruction = """
There are currently no active incidents for this sender. A firing alert must be NEW. A recovered/resolved alert must be RESOLVE with an empty target_incident_id.
"""

    return f"""You are an expert IT operations alert analyst. Your job is to read raw alert emails and produce a concise, actionable summary that an engineer can read in 10 seconds and immediately know what is broken and how to fix it.

Rules:
- Be extremely concise. No filler words. No obvious advice.
- The "main_message" must be ONE sentence describing WHAT failed and WHY.
- The "details" must be a list of short bullet-point strings with ONLY the key technical facts (hostnames, IPs, file paths, error codes, counts, timestamps). Never dump raw dicts or JSON.
- Copy every concrete hostname, IP, PVC, VM, database, path, error code, and resource identifier from the input into "target_resources" or "details". Never replace named resources with generic wording.
- The "recommended_actions" must be 1-2 SPECIFIC objects with text, type (diagnostic|reversible|destructive), and requires_approval. Read-only diagnostics do not require approval; every change does.
- Never invent a namespace, node, command, annotation, API, or remediation not supported by the input. Prefer safe read-only diagnostics when the cause is uncertain.
- Never recommend deleting, recreating, formatting, patching, detaching, or force-attaching storage unless the alert itself explicitly provides that verified remediation. Mark uncertain remediation as requiring operator validation.
- If the alert is about a partial failure (e.g. 3 of 12 files failed), mention the ratio.
{context_instruction}
Extract these fields:
1. severity: One of "Critical", "High", "Medium", "Low", "Info"
2. category: One of "Auth", "Backup", "Database", "Network", "System", "Service", "Storage", "Hardware", "DNS", "Virtualization", "Security", "Phishing", "Unclassified"
3. status: Either "FIRING" (a new issue/error), "RESOLVED" (issue has recovered/fixed) or "INFO"
4. action: MUST be one of "NEW", "RESOLVE", or "UPDATE" based on the ACTIVE incidents list.
5. target_incident_id: The UUID of the matched active incident (if action is RESOLVE or UPDATE). Otherwise empty string.
6. confidence: Float 0.0 to 1.0
7. system_name: The source system or application name (e.g. "Syncovery v11.3.1", "Zabbix", "Veeam")
8. source_host: The hostname or IP where the alert originated
9. target_resource: The specific broken component, pipeline name, VM name, or alert rule (e.g., "example_daily_pipeline", "EXAMPLE-DB-SRV"). Must be specific to differentiate from other unrelated alerts.
10. target_resources: A list containing every concrete affected resource identifier. Use an empty list only when the input contains none.
11. main_message: One concise sentence (WHAT failed + WHY)
12. details: A list of short strings, each a key fact bullet point
13. recommended_actions: 1-2 structured, safe actions grounded in the input
14. emoji: A single expressive emoji representing the state (e.g. ✅ for Up/Resolved, 🔴 for Critical Down, ⚠️ for Warning, ℹ️ for Info).

Respond in JSON format ONLY:
{{
    "analysis": {{
        "severity": "...",
        "category": "...",
        "status": "FIRING",
        "action": "NEW",
        "target_incident_id": "",
        "confidence": 0.0,
        "system_name": "...",
        "source_host": "...",
        "target_resource": "...",
        "target_resources": ["..."],
        "main_message": "...",
        "details": ["fact 1", "fact 2", "fact 3"],
        "recommended_actions": [{{"text": "specific action 1", "type": "diagnostic", "requires_approval": false}}],
        "emoji": "🔴"
    }}
}}

Example input (Syncovery backup failure):
Subject: Syncovery Report - INCOMPLETE
Body: Profile EXAMPLE-DB-SRV ... 9 copied of 12 ... Errors with 3 File(s) ... permission denied ...

Example output:
{{
    "analysis": {{
        "severity": "Medium",
        "category": "Backup",
        "status": "FIRING",
        "confidence": 0.95,
        "system_name": "Syncovery v11.3.1",
        "source_host": "EXAMPLE-SYNC-SRV",
        "target_resource": "EXAMPLE-DB-SRV",
        "target_resources": ["EXAMPLE-DB-SRV", "192.0.2.10:/var/backups/postgres/jira/"],
        "main_message": "Backup profile EXAMPLE-DB-SRV incomplete: 3/12 files failed with permission denied on SFTP source.",
        "details": [
            "Source: sftp://192.0.2.10/var/backups/postgres/jira/",
            "Failed: confluence, jira, postgres dumps (2026-02-08)",
            "Dest: \\\\192.0.2.20\\DB-Backups\\EXAMPLE-DB-SRV",
            "Copied: 9 files (621.7MB) in 1m32s"
        ],
        "recommended_actions": [
            {{"text": "Inspect read permissions on 192.0.2.10:/var/backups/postgres/jira/ for the SFTP backup user", "type": "diagnostic", "requires_approval": false}}
        ],
        "emoji": "⚠️"
    }}
}}"""


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
                "failover_priority": int(provider.get("failover_priority", 100)),
                "is_fallback": provider.get("is_fallback", "false").lower() == "true",
            }
    except Exception as e:
        logger.warning(f"Could not get provider {provider_id} from Redis: {e}")
    return None


def get_failover_providers(primary_id: str = None):
    """Return enabled providers after the primary, without exposing credentials."""
    providers = []
    try:
        r = get_redis_client()
        for provider_id in r.smembers("ai_providers:index") or set():
            if provider_id == primary_id:
                continue
            provider = get_provider_by_id(provider_id)
            if provider and provider.get("base_url") and provider.get("model"):
                providers.append(provider)
    except Exception as exc:
        logger.warning("Could not load AI failover providers: %s", exc)
    # Prefer the operator-selected fallback, then emergency tertiary providers.
    providers.sort(key=lambda item: (
        0 if item.get("is_fallback") else 1,
        int(item.get("failover_priority", 100)),
        item.get("name", "")
    ))
    return providers


def probe_fallback_provider() -> dict:
    """Exercise the selected fallback without analysis, correlation, or notification side effects."""
    primary = get_default_provider()
    fallback = next((item for item in get_failover_providers(primary.get("id")) if item.get("is_fallback")), None)
    if not fallback:
        return {"status": "unknown", "detail": "No fallback provider configured", "provider": ""}
    base_url = fallback.get("base_url", "")
    if fallback.get("type", "").lower() in {"openai", "vllm"} and not base_url.endswith("/chat/completions"):
        base_url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": fallback.get("model"),
        "messages": [{"role": "user", "content": "AlertFlow health probe. Reply with OK only."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    headers = {"Content-Type": "application/json"}
    if fallback.get("api_key"):
        headers["Authorization"] = f"Bearer {fallback['api_key']}"
    started = _time.time()
    try:
        response = requests.post(base_url, json=payload, headers=headers, timeout=min(int(fallback.get("timeout", 30)), 30))
        latency = round(_time.time() - started, 2)
        ok = response.status_code == 200 and bool(response.json().get("choices"))
        detail = "Fallback probe succeeded" if ok else f"Fallback probe HTTP {response.status_code}"
        return {"status": "healthy" if ok else "critical", "detail": detail, "provider": fallback.get("name", ""), "latency": latency}
    except (requests.RequestException, ValueError) as exc:
        return {"status": "critical", "detail": f"Fallback probe failed: {type(exc).__name__}", "provider": fallback.get("name", ""), "latency": round(_time.time() - started, 2)}


def analyze_email(sender: str, subject: str, body: str, provider_id: str = None, active_incidents_context: str = "") -> tuple:
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

        body_max_chars = int(os.getenv("AI_BODY_MAX_CHARS", "2500"))
        normalized = normalize_alert(sender, subject, body)
        user_content = f"""
Analyze this alert email:

FROM: {sender}
SUBJECT: {subject}

DETERMINISTIC EXTRACTED FACTS (preserve these exact values):
{prompt_context(normalized)}

BODY:
{body[:body_max_chars]}
"""

        candidates = [provider] + get_failover_providers(provider.get("id"))
        max_attempts = int(os.getenv("AI_MAX_PROVIDER_ATTEMPTS", "3"))
        last_error = "all providers failed"

        for attempt, candidate in enumerate(candidates[:max_attempts], start=1):
            model = candidate["model"]
            base_url = candidate["base_url"]
            api_key = candidate.get("api_key", "")
            timeout = int(candidate.get("timeout", 120))
            provider_type = candidate.get("type", "ollama").lower()
            provider_name = f"{candidate.get('name', 'unknown')} ({model})"
            if provider_type in {"openai", "vllm"} and not base_url.endswith("/chat/completions"):
                base_url = f"{base_url.rstrip('/')}/chat/completions"

            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": build_system_prompt(active_incidents_context)},
                    {"role": "user", "content": user_content}
                ],
                "temperature": 0.1
            }
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            logger.info("⏳ AI analysis started | Provider: %s | Attempt: %s/%s",
                        provider_name, attempt, min(len(candidates), max_attempts))
            try:
                response = requests.post(base_url, json=payload, headers=headers, timeout=timeout)
                duration = round(_time.time() - start_time, 1)
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}: {response.text[:500]}"
                    _record_provider_metric(candidate, "failure", duration, last_error, fallback=attempt > 1)
                    logger.error("❌ AI provider failed (%ss) | %s | %s", duration, provider_name, last_error)
                    continue

                result = response.json()
                choices = result.get("choices", [])
                content = choices[0].get("message", {}).get("content", "") if choices else ""
                if not content:
                    last_error = "empty model response"
                    logger.error("❌ AI provider failed | %s | %s", provider_name, last_error)
                    continue

                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
                else:
                    start_idx, end_idx = content.find('{'), content.rfind('}')
                    if start_idx != -1 and end_idx > start_idx:
                        content = content[start_idx:end_idx + 1]

                parsed = preserve_resources(json.loads(content), normalized)
                analysis = parsed.get("analysis")
                if not isinstance(analysis, dict):
                    raise ValueError("response does not contain an analysis object")
                analysis.setdefault("target_resources", [])
                analysis["target_resources"] = normalize_resource_identifiers(analysis["target_resources"])
                normalize_analysis_taxonomy(analysis)
                normalize_recommended_actions(analysis)
                if not analysis["target_resources"] and analysis.get("target_resource"):
                    analysis["target_resources"] = [analysis["target_resource"]]
                try:
                    quality_metrics_client = get_redis_client()
                except Exception:
                    quality_metrics_client = None
                parsed = validate_analysis(
                    parsed, sender, subject, body, normalized,
                    metrics_client=quality_metrics_client,
                )
                analysis = parsed["analysis"]
                duration = round(_time.time() - start_time, 1)
                severity = analysis.get("severity", "Unknown")
                logger.info("✅ AI analysis complete | %ss | Provider: %s | Severity: %s",
                            duration, provider_name, severity)
                _record_provider_metric(candidate, "success", duration, fallback=attempt > 1)
                return parsed, provider_name, duration
            except (requests.exceptions.RequestException, ValueError, KeyError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                duration = round(_time.time() - start_time, 1)
                _record_provider_metric(candidate, "failure", duration, last_error, fallback=attempt > 1)
                logger.error("❌ AI provider failed | %s | %s", provider_name, last_error)
                continue

        duration = round(_time.time() - start_time, 1)
        logger.error("❌ All AI providers failed (%ss): %s", duration, last_error)
        return None, provider_name, duration

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

    # Get dynamic emoji directly from AI, fallback to severity-based if missing
    dynamic_emoji = analysis.get("emoji", "")
    if not dynamic_emoji:
        dynamic_emoji = {
            "Critical": "🔴",
            "High": "🟠",
            "Medium": "🟡",
            "Low": "🟢",
            "Info": "ℹ️"
        }.get(severity, "⚪")

    # Build message
    lines = []

    # Recovery is an event state; severity remains the incident impact.
    if str(analysis.get("event_state", "")).lower() == "resolved":
        dynamic_emoji = "✅"
        lines.append(
            f"{dynamic_emoji} *Resolved* \\| Previously {escape_markdown_v2(severity)} \\| {escape_markdown_v2(category)}"
        )
    else:
        lines.append(f"{dynamic_emoji} *{escape_markdown_v2(severity)}* \\| {escape_markdown_v2(category)}")

    # System + Host: 📌 Syncovery v11.3.1 — EXAMPLE-SYNC-SRV
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
                lines.append(f"→ {escape_markdown_v2(action_display(action))}")

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

    header = (
        f"✅ Resolved | Previously {severity} | {category}"
        if str(analysis.get("event_state", "")).lower() == "resolved"
        else f"{severity_emoji} {severity} | {category}"
    )
    lines = [
        header,
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
            lines.append(f"→ {action_display(action)}")

    return "\n".join(lines)
