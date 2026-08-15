#!/usr/bin/env python3
"""Repair legacy incident state from immutable alert records; dry-run by default."""
import argparse
import json
import re
import time
from collections import defaultdict

import os
import redis


def normalized_subject(value):
    value = re.sub(r"\b(firing|resolved|reset|critical|warning|error|problem)\b", " ", value or "", flags=re.I)
    value = re.sub(r"\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M)?", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="/tmp/alertflow-incident-state-backup.json")
    args = parser.parse_args()
    client = redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"), port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD") or None, decode_responses=True,
    )

    incident_alerts = defaultdict(list)
    for alert_id in client.zrange("alerts:index", 0, -1):
        alert = client.hgetall(f"alert:{alert_id}")
        if alert.get("incident_key"):
            alert["id"] = alert_id
            alert["score"] = float(client.zscore("alerts:index", alert_id) or 0)
            incident_alerts[alert["incident_key"]].append(alert)

    open_membership = defaultdict(set)
    for key in client.scan_iter("open_incidents:*"):
        open_membership[key] = set(client.smembers(key) or set())

    originals = {}
    repaired = closed_orphans = superseded = 0
    candidates = {}
    for incident_id, alerts in incident_alerts.items():
        raw = client.get(f"incident:{incident_id}")
        if not raw:
            continue
        state = json.loads(raw)
        originals[incident_id] = state
        latest = max(alerts, key=lambda item: item["score"])
        try:
            analysis = (json.loads(latest.get("ai_raw") or "{}") or {}).get("analysis", {})
        except Exception:
            analysis = {}
        changed = False
        for state_key, analysis_key in (
            ("latest_main_message", "main_message"), ("latest_details", "details"),
            ("target_resources", "target_resources"), ("source_fingerprint", "source_fingerprint"),
        ):
            if not state.get(state_key) and analysis.get(analysis_key):
                state[state_key] = analysis[analysis_key]
                changed = True
        if not state.get("target_resource") and state.get("target_resources"):
            state["target_resource"] = ", ".join(map(str, state["target_resources"]))
            changed = True

        ai_status = str(analysis.get("status", "")).upper()
        if state.get("status") == "OPEN" and ai_status == "RESOLVED" and latest.get("correlation_action") == "NEW":
            state["status"] = "ORPHAN_RESOLVED"
            state["resolved_at"] = latest["score"] or time.time()
            state["repair_reason"] = "legacy_resolved_without_target"
            changed = True
            closed_orphans += 1
            for open_key, members in open_membership.items():
                if incident_id in members and args.apply:
                    client.srem(open_key, incident_id)

        if changed:
            repaired += 1
            candidates[incident_id] = state
            if args.apply:
                client.set(f"incident:{incident_id}", json.dumps(state), ex=86400 * 7)

    # Supersede only semantically identical OPEN incidents with the same concrete resources.
    groups = defaultdict(list)
    for open_key, members in open_membership.items():
        for incident_id in members:
            state = candidates.get(incident_id)
            if state is None:
                raw = client.get(f"incident:{incident_id}")
                state = json.loads(raw) if raw else {}
            resources = tuple(sorted(str(v).strip().lower() for v in state.get("target_resources", []) if str(v).strip()))
            if state.get("status") == "OPEN" and resources:
                groups[(open_key, normalized_subject(state.get("subject", "")), resources)].append((incident_id, state))
    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda item: float(item[1].get("last_updated") or 0), reverse=True)
        canonical_id = group[0][0]
        for incident_id, state in group[1:]:
            originals.setdefault(incident_id, state)
            state["status"] = "SUPERSEDED"
            state["superseded_by"] = canonical_id
            state["repair_reason"] = "duplicate_open_incident"
            superseded += 1
            if args.apply:
                client.set(f"incident:{incident_id}", json.dumps(state), ex=86400 * 7)
                for open_key, members in open_membership.items():
                    if incident_id in members:
                        client.srem(open_key, incident_id)

    with open(args.backup, "w", encoding="utf-8") as handle:
        json.dump(originals, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run", "states_examined": len(originals),
        "states_repaired": repaired, "orphan_resolves_closed": closed_orphans,
        "duplicates_superseded": superseded, "backup": args.backup,
    }, indent=2))


if __name__ == "__main__":
    main()
