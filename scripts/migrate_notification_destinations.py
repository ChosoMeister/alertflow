#!/usr/bin/env python3
"""Convert legacy rule channel overrides into reusable endpoint records."""
import argparse
import hashlib
import json
import os
import redis
from datetime import datetime


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
        host=os.getenv("REDIS_HOST", "redis"), port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True,
    )
    channels = {cid: client.hgetall(f"notification_channel:{cid}") for cid in client.smembers("notification_channels:index")}
    existing = {}
    for did in client.smembers("notification_destinations:index"):
        item = client.hgetall(f"notification_destination:{did}")
        signature = item.get("migration_signature")
        if signature:
            existing[signature] = did
    created = attached = 0
    for rule_id in sorted(client.smembers("routing_rules:index")):
        key = f"routing_rule:{rule_id}"
        rule = client.hgetall(key)
        current = loads(rule.get("alert_destination_ids"), [])
        if current:
            continue
        overrides = loads(rule.get("channel_overrides"), {})
        destination_ids = []
        for channel_id in loads(rule.get("notification_channel_ids"), []):
            channel = channels.get(channel_id) or {}
            ctype = channel.get("type", "")
            config = loads(channel.get("config"), {})
            target = dict(overrides.get(channel_id, {}) or {})
            if ctype == "telegram":
                target["chat_id"] = target.get("chat_id") or config.get("chat_id") or config.get("default_chat_id")
                target["thread_id"] = str(target.get("thread_id") or config.get("default_thread_id") or "0")
            elif ctype == "matrix":
                target["room_id"] = target.get("room_id") or config.get("default_room_id") or config.get("room_id")
            elif ctype == "webhook":
                target["url"] = target.get("url") or config.get("url")
            elif ctype == "sms":
                target["receptor"] = target.get("receptor") or config.get("receptor") or config.get("default_recipient")
            signature = hashlib.sha256(f"{channel_id}:{json.dumps(target, sort_keys=True)}".encode()).hexdigest()[:16]
            destination_id = existing.get(signature) or f"m{signature[:7]}"
            if signature not in existing:
                created += 1
                existing[signature] = destination_id
                if args.apply:
                    now = datetime.utcnow().isoformat()
                    label = target.get("chat_id") or target.get("room_id") or target.get("url") or target.get("receptor") or destination_id
                    if ctype == "telegram" and str(target.get("thread_id", "0")) != "0":
                        label = f"{label} / thread {target['thread_id']}"
                    client.hset(f"notification_destination:{destination_id}", mapping={
                        "id": destination_id, "name": f"{channel.get('name', ctype)} — {label}",
                        "channel_id": channel_id, "type": ctype, "target": json.dumps(target),
                        "enabled": "true", "migration_signature": signature,
                        "created_at": now, "updated_at": now,
                    })
                    client.sadd("notification_destinations:index", destination_id)
            destination_ids.append(destination_id)
        if destination_ids:
            attached += 1
            if args.apply:
                client.hset(key, mapping={
                    "alert_destination_ids": json.dumps(destination_ids),
                    "resolved_destination_ids": rule.get("resolved_destination_ids") or "[]",
                    "resolution_mode": rule.get("resolution_mode") or "legacy",
                    "updated_at": datetime.utcnow().isoformat(),
                })
    print(json.dumps({"apply": args.apply, "destinations_created": created, "rules_attached": attached}))


if __name__ == "__main__":
    main()
