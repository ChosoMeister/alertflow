"""
Routing - Pattern matching and rule evaluation for alert processor.
"""
import fnmatch
from typing import Optional, List, Dict, Any


def match_pattern(pattern: str, email: str) -> bool:
    """
    Match email against glob pattern (case-insensitive).

    Supported patterns:
    - Exact: alert@system.local
    - Domain wildcard: *@domain.tld
    - Prefix wildcard: security-*@corp.com
    """
    pattern = pattern.lower().strip()
    email = email.lower().strip()
    return fnmatch.fnmatch(email, pattern)


def find_matching_rule(
    sender_email: str,
    rules: List[Dict[str, Any]],
    recipient_emails: List[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Find the first matching rule for an email, considering both FROM and TO rules.

    Rules are evaluated in priority order (lower number = higher priority).
    For match_field="from" rules, matches against sender_email.
    For match_field="to" rules, matches against any recipient in recipient_emails.
    """
    if recipient_emails is None:
        recipient_emails = []

    # Filter enabled rules, sort by priority
    filtered_rules = [
        r for r in rules
        if str(r.get("enabled", "true")).lower() == "true"
    ]
    filtered_rules.sort(key=lambda r: int(r.get("priority", 0)))

    for rule in filtered_rules:
        pattern = rule.get("email_pattern", "")
        match_field = rule.get("match_field", "from")

        if match_field == "to":
            # Match against any recipient
            for recipient in recipient_emails:
                if recipient and match_pattern(pattern, recipient):
                    return rule
        else:
            # match_field == "from" (default)
            if sender_email and match_pattern(pattern, sender_email):
                return rule

    return None


def get_routing_targets(
    sender_email: str,
    rules: List[Dict[str, Any]],
    default_tg_chat: str,
    default_tg_thread: str,
    default_mx_room: str,
    default_channel: str,
    recipient_emails: List[str] = None
) -> Dict[str, Any]:
    """
    Get routing targets for an email.

    Matches rules against both sender (match_field="from") and
    recipients (match_field="to") in priority order.

    Returns dict with:
    - matched_rule: rule name or None
    - channel: "telegram", "matrix", "both", "dynamic"
    - notification_channel_ids: List[str] (for dynamic)
    - channel_overrides: Dict[channel_id, Dict] (chat_id/thread_id per channel)
    - telegram_chat_id (legacy fallback)
    - telegram_thread_id (legacy fallback)
    - matrix_room_id (legacy fallback)
    """
    matched_rule = find_matching_rule(sender_email, rules, recipient_emails or [])

    if matched_rule:
        # Deserialize JSON fields if they are strings
        nc_ids = matched_rule.get("notification_channel_ids", [])
        if isinstance(nc_ids, str):
            try:
                import json
                nc_ids = json.loads(nc_ids)
            except:
                nc_ids = []

        c_overrides = matched_rule.get("channel_overrides", {})
        if isinstance(c_overrides, str):
            try:
                import json
                c_overrides = json.loads(c_overrides)
            except:
                c_overrides = {}

        return {
            "matched_rule": matched_rule.get("name"),
            "channel": matched_rule.get("channels", "telegram"),
            # New fields for dynamic routing
            "notification_channel_ids": nc_ids,
            "channel_overrides": c_overrides,
            "severity_matrix": matched_rule.get("severity_matrix", {}),
            "ai_provider_id": matched_rule.get("ai_provider_id"),
            # Legacy fields (for backward compatibility)
            "telegram_chat_id": matched_rule.get("telegram_chat_id", ""),
            "telegram_thread_id": matched_rule.get("telegram_thread_id", "0"),
            "matrix_room_id": matched_rule.get("matrix_room_id", ""),
        }
    else:
        return {
            "matched_rule": None,
            "channel": default_channel,
            "notification_channel_ids": [],
            "channel_overrides": {},
            "telegram_chat_id": default_tg_chat,
            "telegram_thread_id": default_tg_thread,
            "matrix_room_id": default_mx_room,
        }
