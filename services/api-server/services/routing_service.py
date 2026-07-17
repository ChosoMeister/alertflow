"""
Routing Service - Pattern matching and rule evaluation for email routing.
"""
import fnmatch
from typing import Optional, List
from models import RoutingRule, RoutingTestResponse
from config import get_settings

settings = get_settings()


def match_pattern(pattern: str, email: str) -> bool:
    """
    Match email against glob pattern (case-insensitive).

    Supported patterns:
    - Exact: alert@system.local
    - Domain wildcard: *@domain.tld
    - Prefix wildcard: security-*@corp.com
    - Suffix wildcard: *-alert@domain.com
    """
    pattern = pattern.lower().strip()
    email = email.lower().strip()

    # Use fnmatch for glob-style matching
    return fnmatch.fnmatch(email, pattern)


def find_matching_rule(
    email: str,
    match_field: str,
    rules: List[RoutingRule]
) -> Optional[RoutingRule]:
    """
    Find the first matching rule for an email address.

    Rules are evaluated in priority order (lower number = higher priority).
    Only enabled rules with matching match_field are considered.
    """
    # Filter enabled rules with correct match_field, sort by priority
    filtered_rules = [
        r for r in rules
        if r.get("enabled", True) and r.get("match_field", "from") == match_field
    ]
    filtered_rules.sort(key=lambda r: r.get("priority", 0))

    for rule in filtered_rules:
        pattern = rule.get("email_pattern", "")
        if match_pattern(pattern, email):
            return rule

    return None


def get_routing_result(
    email: str,
    match_field: str,
    rules: List[dict]
) -> RoutingTestResponse:
    """
    Get routing result for an email address.

    Returns matched rule info or defaults if no match.
    """
    matched_rule = find_matching_rule(email, match_field, rules)

    if matched_rule:
        return RoutingTestResponse(
            matched=True,
            rule_id=matched_rule.get("id"),
            rule_name=matched_rule.get("name"),
            telegram_chat_id=matched_rule.get("telegram_chat_id", ""),
            telegram_thread_id=matched_rule.get("telegram_thread_id", "0"),
            matrix_room_id=matched_rule.get("matrix_room_id", ""),
            channels=matched_rule.get("channels", "telegram")
        )
    else:
        # Return default destinations
        return RoutingTestResponse(
            matched=False,
            rule_id=None,
            rule_name=None,
            telegram_chat_id=settings.telegram_default_chat_id,
            telegram_thread_id=settings.telegram_default_thread_id,
            matrix_room_id=settings.matrix_default_room_id,
            channels=settings.default_notification_channel
        )
