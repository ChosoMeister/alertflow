"""
Analytics API - Aggregated alert statistics.
"""
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends

from auth import User, get_current_user
from services.redis_service import get_redis_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("")
async def get_analytics(user: User = Depends(get_current_user)):
    """Compute analytics from all alerts in Redis.

    Returns severity distribution, daily trend, hourly distribution,
    top senders, status breakdown, and AI performance metrics.
    """
    redis_svc = get_redis_service()

    # Fetch all alerts (14-day retention means manageable dataset)
    all_alerts = redis_svc.list_alerts(limit=10000, offset=0)
    delivery_pipe = redis_svc.client.pipeline(transaction=False)
    for alert in all_alerts:
        delivery_pipe.hgetall(f"delivery:{alert['id']}")
    delivery_by_alert = dict(zip(
        (alert["id"] for alert in all_alerts),
        delivery_pipe.execute() if all_alerts else [],
    ))

    now = datetime.now()

    # Initialize accumulators
    severity_counts = defaultdict(int)
    status_counts = defaultdict(int)
    sender_stats = defaultdict(lambda: {"total": 0, "resolved": 0, "open": 0})
    daily_counts = defaultdict(int)  # "YYYY-MM-DD" -> count
    hourly_counts = defaultdict(int)  # hour (0-23) -> count
    ai_durations = []
    resolution_seconds = []
    correlation_counts = defaultdict(int)
    suppression_counts = defaultdict(int)
    ai_complete = 0
    explainable_decisions = 0
    final_delivery = defaultdict(int)

    for alert in all_alerts:
        # Severity
        sev = alert.get("severity") or "Unknown"
        severity_counts[sev] += 1

        # Status
        st = alert.get("status", "unknown")
        status_counts[st] += 1
        action = (alert.get("correlation_action") or "UNKNOWN").upper()
        correlation_counts[action] += 1
        suppression = alert.get("notification_suppressed", "")
        if suppression:
            suppression_counts[suppression] += 1
        if alert.get("analysis_status") == "complete" and alert.get("ai_raw"):
            ai_complete += 1
        if alert.get("incident_key") and alert.get("correlation_action"):
            explainable_decisions += 1
        delivery_states = []
        for raw_delivery in (delivery_by_alert.get(alert.get("id")) or {}).values():
            try:
                delivery_states.append(json.loads(raw_delivery).get("status", "unknown"))
            except (TypeError, json.JSONDecodeError):
                delivery_states.append("invalid")
        if delivery_states:
            final_delivery["observed"] += 1
            if all(state == "delivered" for state in delivery_states):
                final_delivery["fully_delivered"] += 1
                final_delivery["reached_any_channel"] += 1
            elif any(state == "delivered" for state in delivery_states):
                final_delivery["partially_delivered"] += 1
                final_delivery["reached_any_channel"] += 1
            else:
                final_delivery["not_delivered"] += 1

        # Per-sender stats (total, resolved, open)
        sender = alert.get("from_email", "unknown")
        if sender:
            sender_stats[sender]["total"] += 1
            if st == "resolved":
                sender_stats[sender]["resolved"] += 1
            elif st in ("new", "acknowledged", "duplicate"):
                sender_stats[sender]["open"] += 1

        # Timestamp parsing for time-based charts
        ts = alert.get("created_at") or alert.get("timestamp") or alert.get("received_at", "")
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    dt = datetime.fromtimestamp(float(ts))
                else:
                    # Try ISO format
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])

                # Daily trend (last 7 days)
                day_key = dt.strftime("%Y-%m-%d")
                daily_counts[day_key] += 1

                # Hourly distribution (last 24h only)
                if (now - dt).total_seconds() < 86400:
                    hourly_counts[dt.hour] += 1
            except (ValueError, TypeError, OSError):
                pass

        # AI duration
        ai_dur = alert.get("analysis_duration") or alert.get("ai_duration")
        if ai_dur:
            try:
                ai_durations.append(float(ai_dur))
            except (ValueError, TypeError):
                pass
        if st == "resolved" and alert.get("resolved_at") and ts:
            try:
                created = datetime.fromisoformat(str(ts).replace("Z", "+00:00").split("+")[0])
                resolved = datetime.fromisoformat(str(alert["resolved_at"]).replace("Z", "+00:00").split("+")[0])
                resolution_seconds.append(max(0, (resolved - created).total_seconds()))
            except (ValueError, TypeError):
                pass

    # Build daily trend for last 7 days (fill gaps with 0)
    daily_trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_trend.append({
            "date": day,
            "label": (now - timedelta(days=i)).strftime("%a"),  # Mon, Tue, etc.
            "count": daily_counts.get(day, 0),
        })

    # Build hourly distribution (0-23, fill gaps)
    hourly_dist = []
    for h in range(24):
        hourly_dist.append({
            "hour": h,
            "label": f"{h:02d}:00",
            "count": hourly_counts.get(h, 0),
        })

    # Top senders (top 10 by total, with breakdown)
    top_senders = sorted(sender_stats.items(), key=lambda x: x[1]["total"], reverse=True)[:10]

    # Severity distribution (ordered)
    severity_order = ["Critical", "High", "Medium", "Low", "Info", "Unknown"]
    severity_dist = [
        {"severity": s, "count": severity_counts.get(s, 0)}
        for s in severity_order
        if severity_counts.get(s, 0) > 0
    ]

    # Status distribution
    status_dist = [
        {"status": s, "count": c}
        for s, c in sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # AI performance
    avg_ai = round(sum(ai_durations) / len(ai_durations), 2) if ai_durations else 0
    processor_metrics = redis_svc.client.hgetall("metrics:processor") or {}
    slo_metrics = redis_svc.client.hgetall("metrics:slo") or {}
    checks = int(slo_metrics.get("component_checks", 0) or 0)
    healthy_checks = int(slo_metrics.get("healthy_component_checks", 0) or 0)
    delivery_success = int(processor_metrics.get("delivery_successes", 0) or 0)
    delivery_failure = int(processor_metrics.get("delivery_failures", 0) or 0)
    delivery_total = delivery_success + delivery_failure
    provider_ids = list(redis_svc.client.smembers("ai_providers:index") or set())
    ai_attempts = ai_successes = ai_fallback_uses = 0
    for provider_id in provider_ids:
        metrics = redis_svc.client.hgetall(f"metrics:ai:provider:{provider_id}")
        ai_attempts += int(metrics.get("attempts", 0) or 0)
        ai_successes += int(metrics.get("success", 0) or 0)
        ai_fallback_uses += int(metrics.get("fallback_uses", 0) or 0)

    total_alerts = len(all_alerts)
    ai_coverage = round(ai_complete / total_alerts * 100, 2) if total_alerts else None
    decision_coverage = round(explainable_decisions / total_alerts * 100, 2) if total_alerts else None
    delivery_rate = round(delivery_success / delivery_total * 100, 2) if delivery_total else None
    final_delivery_rate = round(final_delivery["reached_any_channel"] / final_delivery["observed"] * 100, 2) if final_delivery["observed"] else None
    full_delivery_rate = round(final_delivery["fully_delivered"] / final_delivery["observed"] * 100, 2) if final_delivery["observed"] else None
    score_inputs = [value for value in (ai_coverage, decision_coverage, final_delivery_rate) if value is not None]
    operational_score = round(sum(score_inputs) / len(score_inputs), 1) if score_inputs else None
    exact_suppressed = int(processor_metrics.get("exact_occurrences_recorded", 0) or 0)
    prevented_notifications = (
        sum(suppression_counts.values())
        + correlation_counts.get("MERGE", 0)
        + correlation_counts.get("IGNORE", 0)
        + exact_suppressed
    )

    return {
        "total_alerts": len(all_alerts),
        "resolved_count": status_counts.get("resolved", 0),
        "severity_distribution": severity_dist,
        "status_distribution": status_dist,
        "daily_trend": daily_trend,
        "hourly_distribution": hourly_dist,
        "top_senders": [
            {"email": email, "total": stats["total"], "resolved": stats["resolved"], "open": stats["open"]}
            for email, stats in top_senders
        ],
        "ai_performance": {
            "avg_duration": avg_ai,
            "total_analyzed": len(ai_durations),
        },
        "slo": {
            "availability_percent": round(healthy_checks / checks * 100, 2) if checks else None,
            "delivery_success_percent": round(delivery_success / delivery_total * 100, 2) if delivery_total else None,
            "final_delivery_success_percent": final_delivery_rate,
            "ai_success_percent": round(ai_successes / ai_attempts * 100, 2) if ai_attempts else None,
            "mean_time_to_resolve_minutes": round(sum(resolution_seconds) / len(resolution_seconds) / 60, 2) if resolution_seconds else None,
            "fallback_uses": ai_fallback_uses,
            "storm_notifications_suppressed": int(processor_metrics.get("storm_suppressed", 0) or 0),
            "storm_groups_started": int(processor_metrics.get("storm_groups_started", 0) or 0),
        },
        "reliability_scorecard": {
            "operational_score_percent": operational_score,
            "ai_analysis_coverage_percent": ai_coverage,
            "decision_trace_coverage_percent": decision_coverage,
            "delivery_success_percent": final_delivery_rate,
            "delivery_attempt_success_percent": delivery_rate,
            "final_delivery_success_percent": final_delivery_rate,
            "full_delivery_success_percent": full_delivery_rate,
            "final_delivery_observed_alerts": final_delivery["observed"],
            "final_delivery_fully_delivered": final_delivery["fully_delivered"],
            "final_delivery_partially_delivered": final_delivery["partially_delivered"],
            "final_delivery_not_delivered": final_delivery["not_delivered"],
            "prevented_notifications": prevented_notifications,
            "exact_duplicates_suppressed": exact_suppressed,
            "merged_updates": correlation_counts.get("MERGE", 0),
            "suppressed_by_reason": dict(suppression_counts),
            "correlation_actions": dict(correlation_counts),
            "scope": "retained alerts plus lifetime processor counters",
            "accuracy_note": "Operational health only; correctness requires operator feedback or a labeled dataset",
        },
    }
