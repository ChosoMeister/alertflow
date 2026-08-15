#!/usr/bin/env python3
"""Backfill stable correlation identities and supersede only identical open groups."""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import redis

sys.path.insert(0, os.getenv("PROCESSOR_PATH", str(Path(__file__).resolve().parents[1] / "services" / "alert-processor")))
from source_adapters import build_correlation_identity, normalize_resource_identifiers  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="/tmp/correlation-identities-backup.json")
    args = parser.parse_args()
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"), port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True,
    )

    alert_groups = defaultdict(list)
    for alert_id in client.zrange("alerts:index", 0, -1):
        alert = client.hgetall(f"alert:{alert_id}")
        if alert.get("incident_key"):
            alert["id"] = alert_id
            alert["score"] = float(client.zscore("alerts:index", alert_id) or 0)
            alert_groups[alert["incident_key"]].append(alert)

    open_items = []
    originals = {}
    for open_key in client.scan_iter("open_incidents:*"):
        domain = open_key.split(":", 1)[-1]
        for incident_id in client.smembers(open_key) or set():
            raw = client.get(f"incident:{incident_id}")
            if not raw or not alert_groups.get(incident_id):
                continue
            state = json.loads(raw)
            if state.get("status") != "OPEN":
                continue
            latest = max(alert_groups[incident_id], key=lambda item: item["score"])
            try:
                analysis = (json.loads(latest.get("ai_raw") or "{}") or {}).get("analysis", {})
            except Exception:
                analysis = {}
            identity = build_correlation_identity(
                latest.get("from_email", ""), latest.get("subject", ""), latest.get("body", ""), analysis,
            )
            if not identity.get("correlation_key"):
                continue
            originals[incident_id] = state
            open_items.append({
                "open_key": open_key, "domain": domain, "incident_id": incident_id,
                "state": state, "latest": latest, **identity,
            })

    groups = defaultdict(list)
    for item in open_items:
        groups[(item["domain"], item["correlation_key"])].append(item)

    report_groups = []
    superseded = 0
    now = time.time()
    for (domain, key), items in groups.items():
        items.sort(key=lambda item: (
            bool(item["state"].get("channels")), int(item["state"].get("occurrences", 1)),
            float(item["state"].get("last_updated") or 0),
        ), reverse=True)
        canonical = items[0]
        canonical_state = canonical["state"]
        latest_item = max(items, key=lambda item: float(item["state"].get("last_updated") or 0))
        canonical_state["correlation_key"] = key
        canonical_state["correlation_identity"] = canonical["correlation_identity"]
        canonical_state["correlation_domain"] = domain
        if len(items) > 1:
            canonical_state["occurrences"] = sum(int(item["state"].get("occurrences", 1)) for item in items)
            canonical_state["first_seen"] = min(float(item["state"].get("first_seen") or now) for item in items)
            canonical_state["last_updated"] = max(float(item["state"].get("last_updated") or 0) for item in items)
            for field in ("latest_main_message", "latest_details"):
                if latest_item["state"].get(field):
                    canonical_state[field] = latest_item["state"][field]
            combined_resources = []
            for item in items:
                combined_resources.extend(item["state"].get("target_resources", []) or [])
            canonical_state["target_resources"] = normalize_resource_identifiers(combined_resources)
            canonical_state["target_resource"] = ", ".join(canonical_state["target_resources"])
            report_groups.append({
                "identity": canonical["correlation_identity"], "canonical": canonical["incident_id"],
                "members": [item["incident_id"] for item in items],
                "occurrences": canonical_state["occurrences"],
            })

        if args.apply:
            client.set(f"incident:{canonical['incident_id']}", json.dumps(canonical_state), ex=86400 * 7)
            client.set(f"incident_identity:{domain}:{key}", canonical["incident_id"], ex=86400 * 7)
        for duplicate in items[1:]:
            state = duplicate["state"]
            state["status"] = "SUPERSEDED_IDENTITY"
            state["superseded_by"] = canonical["incident_id"]
            state["superseded_at"] = now
            state["correlation_key"] = key
            state["correlation_identity"] = duplicate["correlation_identity"]
            state["correlation_domain"] = domain
            superseded += 1
            if args.apply:
                client.set(f"incident:{duplicate['incident_id']}", json.dumps(state), ex=86400 * 7)
                client.srem(duplicate["open_key"], duplicate["incident_id"])

    with open(args.backup, "w", encoding="utf-8") as handle:
        json.dump(originals, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run", "open_with_identity": len(open_items),
        "identity_groups": len(groups), "duplicate_groups": len(report_groups),
        "superseded": superseded, "groups": sorted(report_groups, key=lambda value: len(value["members"]), reverse=True),
        "backup": args.backup,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
