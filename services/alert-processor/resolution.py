"""Deterministic, size-bounded resolved incident cards."""
from datetime import datetime, timezone
import re

TELEGRAM_LIMIT = 3500
MATRIX_LIMIT = 12000


def _text(value, fallback="Not provided"):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value or fallback


def _time(value):
    if not value:
        return "Not provided by source"
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    return _text(value)


def _duration(start, end):
    try:
        seconds = max(0, int(float(end) - float(start)))
    except (TypeError, ValueError):
        return "Unknown"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def extract_source_timestamp(*values):
    patterns = (
        r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}[ T,]+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[+-]\d{4})?",
        r"\b\d{1,2}/\d{1,2}/20\d{2},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?",
    )
    for value in values:
        text = str(value or "")
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
    return ""


def _bounded(lines, limit):
    required_tail = lines[-10:]
    head = lines[:-10]
    result = []
    for line in head:
        candidate = "\n".join(result + [line] + required_tail)
        if len(candidate) <= limit:
            result.append(line)
        else:
            available = limit - len("\n".join(result + required_tail)) - 20
            if available > 40:
                result.append(line[:available].rstrip() + "…")
            result.append("… additional detail omitted")
            break
    output = "\n".join(result + required_tail)
    return output[:limit]


def _escape_markdown_v2(value):
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}.!])", r"\\\1", str(value))


def build_resolution_cards(incident_key, state, analysis, alert_data, events=None, now=None):
    """Return Telegram and Matrix cards plus their audit metadata."""
    events = events or []
    now = now or datetime.now(tz=timezone.utc).timestamp()
    first_delivery = ""
    for event in events:
        if event.get("action") == "DELIVERY" and event.get("status") == "delivered":
            first_delivery = event.get("occurred_at", "")
            break
    original = state.get("initial_main_message")
    if not original:
        history = state.get("history") or []
        original = history[0].get("main_message") if history else state.get("latest_main_message")
    resources = state.get("target_resources") or analysis.get("target_resources") or []
    if isinstance(resources, str):
        resources = [resources]
    visible = [_text(x) for x in resources[:5]]
    omitted = max(0, len(resources) - len(visible)) + int(state.get("omitted_resource_count", 0) or 0)
    first_seen = state.get("first_seen")
    resolved_at = state.get("resolved_at") or now
    source_resolved = extract_source_timestamp(
        analysis.get("main_message"), analysis.get("details"), alert_data.get("text"), alert_data.get("html")
    )
    lines = [
        "🟢 RESOLVED INCIDENT",
        f"System: {_text(analysis.get('system_name') or state.get('system_name'), 'Unknown')}",
        f"Category: {_text(analysis.get('category') or state.get('category'), 'Unknown')}",
        "",
        "Problem",
        _text(original, "Original problem text was not retained"),
        "",
        "Resolution",
        _text(analysis.get("main_message"), "Issue reported as resolved"),
        "",
        "Affected resources",
    ]
    lines.extend([f"• {item}" for item in visible] or ["• Not provided"])
    if omitted:
        lines.append(f"• +{omitted} more resource(s)")
    lines.extend([
        "",
        "Timeline",
        f"• Source first observed: {_time(state.get('source_first_observed'))}",
        f"• AlertFlow first seen: {_time(first_seen)}",
        f"• First notification: {_time(first_delivery)}",
        f"• Last occurrence: {_time(state.get('last_updated'))}",
        f"• Source resolved: {_time(source_resolved)}",
        f"• Resolution processed: {_time(now)}",
        f"• Total duration: {_duration(first_seen, resolved_at)}",
        f"• Occurrences: {int(state.get('occurrences', 1) or 1)}",
        f"• Merged updates: {int(state.get('merge_occurrences', 0) or 0)}",
        f"• Suppressed duplicates: {int(state.get('suppressed_occurrences', 0) or 0)}",
        f"Incident ID: {incident_key}",
    ])
    metadata = {"source_resolved": source_resolved, "rendered_at": now, "resource_count": len(resources)}
    telegram_lines = [_escape_markdown_v2(line) for line in lines]
    return _bounded(telegram_lines, TELEGRAM_LIMIT), _bounded(lines, MATRIX_LIMIT), metadata
