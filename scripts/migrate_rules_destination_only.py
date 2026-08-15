#!/usr/bin/env python3
"""Remove legacy rule routing after every rule has destination endpoints."""
import argparse
import json
import os
from datetime import datetime

import redis


LEGACY_FIELDS = (
    "telegram_chat_id", "telegram_thread_id", "matrix_room_id", "channels",
    "notification_channel_ids", "channel_overrides", "severity_matrix",
    "resolution_profile_id", "resolution_behavior", "delete_active_after_resolve",
)


def loads(value, fallback):
    try:
        return json.loads(value or json.dumps(fallback))
    except (TypeError, json.JSONDecodeError):
        return fallback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
    )
    destination_ids = set(client.smembers("notification_destinations:index"))
    changes = []
    blockers = []
    for rule_id in sorted(client.smembers("routing_rules:index")):
        key = f"routing_rule:{rule_id}"
        rule = client.hgetall(key)
        active = loads(rule.get("alert_destination_ids"), [])
        resolved = loads(rule.get("resolved_destination_ids"), [])
        severity = loads(rule.get("severity_destination_ids"), {})
        referenced = active + resolved + [item for items in severity.values() for item in items]
        missing = sorted(set(referenced) - destination_ids)
        if not active or missing:
            blockers.append({"id": rule_id, "name": rule.get("name"), "no_alert_destination": not active, "missing": missing})
            continue
        present = [field for field in LEGACY_FIELDS if client.hexists(key, field)]
        changes.append({"id": rule_id, "name": rule.get("name"), "remove": present})
    result = {"apply": args.apply, "rules": len(changes), "blockers": blockers}
    if blockers:
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(2)
    if args.apply:
        for item in changes:
            key = f"routing_rule:{item['id']}"
            if item["remove"]:
                client.hdel(key, *item["remove"])
            client.hset(key, mapping={
                "severity_destination_ids": client.hget(key, "severity_destination_ids") or "{}",
                "updated_at": datetime.utcnow().isoformat(),
            })
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
